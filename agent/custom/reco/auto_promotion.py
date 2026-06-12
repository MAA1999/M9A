import re

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import logger
from utils.maa_types import ocr_results
from utils.params import ParamOverrideMixin, parse_params


@AgentServer.custom_recognition("APPhaseGate")
class APPhaseGate(CustomRecognition):
    """
    活动推图三阶段（故事模式/小径/探索模式）闸门。

    参数格式 (custom_recognition_param):
    {
        "query": "entry" | "story" | "trail" | "explore"
    }
    - entry: 任务入口，总是命中；同时重置阶段访问记录与各识别类状态，
      保证任务重启后从干净状态开始
    - story/trail/explore: 本次任务尚未进入过该阶段则命中并标记，
      已进入过则不命中（调度自然落到后续阶段）。
      是否启用某阶段由节点 enabled 控制（任务选项 pipeline_override）
    """

    _visited: set = set()

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        query = parse_params(argv.custom_recognition_param).get("query", "entry")

        if query == "entry":
            APPhaseGate._visited = set()
            APMapAnalyze.reset_swipe_state()
            from custom.reco.auto_trail import ATTrailAnalyze

            ATTrailAnalyze.reset_state()
            logger.info("[AutoPromotion] 任务开始，阶段状态已重置")
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        if query in APPhaseGate._visited:
            return None
        APPhaseGate._visited.add(query)
        # 进入新的推图阶段前重置滑动到头计数，避免上一阶段的状态串扰
        APMapAnalyze.reset_swipe_state()
        logger.info(f"[AutoPromotion] 进入阶段: {query}")
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"phase": query})


@AgentServer.custom_recognition("APCardFinder")
class APCardFinder(ParamOverrideMixin, CustomRecognition):
    """
    映像页活动/主线卡片查找，驱动入口导航。

    导航链：主页「入场」-> 世纪末尺度页「映像」-> 卡片横排 -> 目标卡片 ->
    详情页「活动正篇/主线正篇」-> 关卡地图页。

    参数格式 (custom_recognition_param):
    {
        "query": "nav" | "card" | "rewind" | "swipe" | "notfound",
        "card_name": "唐人街影话"   // 目标卡片名（标题子串匹配）
    }
    - nav:      card_name 为空或「当前页面」时不命中（跳过导航直接推图），
                否则命中进入导航循环
    - card:     映像页卡片标题含 card_name 则命中，返回卡片点击区
    - rewind:   先把横排列表回卷到最左（右滑），连续两次标题集合不变即回卷完成
    - swipe:    回卷完成后向右逐屏查找（左滑），到头停止命中
    - notfound: 查找到头仍未发现目标卡片，命中后报错结束
    """

    CARD_NAME = ""

    # 卡片标题行（映像页横排卡片的标题）与卡片体点击区
    CARD_TITLE_Y_MIN = 170
    CARD_TITLE_Y_MAX = 230
    CARD_BODY_Y = 240
    CARD_BODY_H = 220
    CARD_BODY_MIN_W = 200

    # 回卷/查找的到头判定（标题集合连续不变次数）
    REWIND_LIMIT = 2
    FORWARD_LIMIT = 3

    OVERRIDABLE = frozenset(
        {
            "CARD_NAME",
            "CARD_TITLE_Y_MIN",
            "CARD_TITLE_Y_MAX",
            "CARD_BODY_Y",
            "CARD_BODY_H",
            "CARD_BODY_MIN_W",
            "REWIND_LIMIT",
            "FORWARD_LIMIT",
        }
    )

    _rewind_sig: tuple | None = None
    _rewind_same: int = 0
    _rewind_done: bool = False
    _forward_sig: tuple | None = None
    _forward_same: int = 0

    @classmethod
    def reset_nav_state(cls) -> None:
        cls._rewind_sig = None
        cls._rewind_same = 0
        cls._rewind_done = False
        cls._forward_sig = None
        cls._forward_same = 0

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        try:
            params = parse_params(argv.custom_recognition_param)
        except ValueError as e:
            logger.error(f"[AutoPromotion] 导航参数解析失败（{e}），使用默认值")
            params = {}
        query = params.get("query", "nav")
        self.apply_param_overrides(params)

        target = self.CARD_NAME.strip()

        if query == "nav":
            if not target or target == "当前页面":
                return None
            APCardFinder.reset_nav_state()
            logger.info(f"[AutoPromotion] 开始导航至「{target}」")
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        # card/rewind/swipe/notfound 仅在映像页生效（顶部「显影罐」横幅锚定），
        # 防止在地图页/世纪末尺度页误触发滑动
        if not self._is_image_page(context, argv.image):
            return None
        titles = self._card_titles(context, argv.image)

        if query == "card":
            if not target:
                return None
            for text, box in titles:
                if self._title_match(target, text):
                    # 不重置导航状态：若点击未生效（卡片在屏边、过渡动画等），
                    # 下一轮 card 仍会命中并重试点击，而不是被回卷滑走
                    logger.info(f"[AutoPromotion] 找到卡片「{text}」，点击进入")
                    body = [
                        max(box[0], 0),
                        self.CARD_BODY_Y,
                        max(box[2], self.CARD_BODY_MIN_W),
                        self.CARD_BODY_H,
                    ]
                    return CustomRecognition.AnalyzeResult(
                        box=body, detail={"card": text}
                    )
            return None

        if not titles:
            return None  # 不在映像页（卡片标题行无内容）
        signature = tuple(sorted(text for text, _ in titles))

        if query == "rewind":
            if APCardFinder._rewind_done:
                return None
            if signature == APCardFinder._rewind_sig:
                APCardFinder._rewind_same += 1
            else:
                APCardFinder._rewind_sig = signature
                APCardFinder._rewind_same = 0
            if APCardFinder._rewind_same >= self.REWIND_LIMIT:
                APCardFinder._rewind_done = True
                logger.info("[AutoPromotion] 卡片列表已回卷到最左，开始向右查找")
                return None
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        if query == "swipe":
            if not APCardFinder._rewind_done:
                return None
            if APCardFinder._forward_same >= self.FORWARD_LIMIT:
                return None  # 已到头，交给 notfound
            if signature == APCardFinder._forward_sig:
                APCardFinder._forward_same += 1
            else:
                APCardFinder._forward_sig = signature
                APCardFinder._forward_same = 0
            if APCardFinder._forward_same >= self.FORWARD_LIMIT:
                return None
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        if query == "notfound":
            if APCardFinder._rewind_done and (
                APCardFinder._forward_same >= self.FORWARD_LIMIT
            ):
                logger.error(f"[AutoPromotion] 卡片列表已扫完，未找到「{target}」")
                APCardFinder.reset_nav_state()
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
            return None

        logger.error(f"[AutoPromotion] 无效 query: {query}")
        return None

    @staticmethod
    def _title_match(target: str, text: str) -> bool:
        """标题匹配：屏幕边缘的卡片标题会被截断（如「87宇宙组曲」），
        除正向子串外也接受足够长的残缺标题反向匹配。"""
        t = text.replace(" ", "").strip()
        if not t:
            return False
        return target in t or (len(t) >= 4 and t in target)

    def _is_image_page(self, context: Context, image) -> bool:
        detail = context.run_recognition("APImagePageOCR", image)
        return any("显影罐" in result.text for result in ocr_results(detail))

    def _card_titles(self, context: Context, image) -> list[tuple[str, list[int]]]:
        detail = context.run_recognition("APCardTitleOCR", image)
        titles = []
        for result in ocr_results(detail):
            text = result.text.strip()
            box = list(result.box)
            cy = box[1] + box[3] / 2
            if self.CARD_TITLE_Y_MIN <= cy <= self.CARD_TITLE_Y_MAX and len(text) >= 2:
                titles.append((text, box))
        return titles


@AgentServer.custom_recognition("APMapAnalyze")
class APMapAnalyze(ParamOverrideMixin, CustomRecognition):
    """
    活动推图地图分析。

    在地图底部条 OCR 关卡编号，编号右侧邻域找完成星标。
    判别不依赖具体颜色（官方每期会微调星标色调）：
    亮星 = 高饱和且高亮的像素簇；灰星 = 邻域内几乎没有高饱和亮像素。

    参数格式 (custom_recognition_param):
    {
        "query": "stage" | "swipe" | "done",
        // 其余 key 为可选的识别参数覆盖（类常量名小写，如 "sat_min": 90），
        // 见 OVERRIDABLE 白名单与协议文档的契约参数表
    }
    - stage: 命中并返回编号最小的未完成关卡的点击区域
    - swipe: 地图可见、无未完成关卡、且尚未确认滑到尽头时命中（供滑动节点使用）
    - done:  连续多次滑动后画面无变化（已到尽头）且无未完成关卡时命中（推图完成）
    """

    OVERRIDABLE = frozenset(
        {
            "SAT_MIN",
            "VAL_MIN",
            "LIT_PIXELS",
            "ZONE_PAD_LEFT",
            "ZONE_PAD_TOP",
            "ZONE_EXTRA_W",
            "ZONE_EXTRA_H",
            "STAGE_BOX_CENTER_X_MIN",
            "STAGE_BOX_CENTER_X_MAX",
            "STAGE_BOX_CENTER_Y_MIN",
            "STAGE_BOX_CENTER_Y_MAX",
            "STAGE_BOX_H_MIN",
            "STAGE_BOX_H_MAX",
            "MULTI_STAR_WIDTH",
            "MULTI_ZONE_EXTRA_W",
            "STAR_ROW_UP",
            "STAR_ROW_DOWN",
            "MULTI_MARKER_PIXELS",
            "DIFFICULTY_GROUPS",
            "DIFFICULTY_LIT_PIXELS",
            "SIG_POS_QUANT",
            "MARKER_R_MIN",
            "MARKER_G_MIN",
            "MARKER_G_MAX",
            "MARKER_B_MAX",
            "MARKER_S_MIN",
            "MARKER_RG_DIFF",
            "MARKER_PAD_LEFT",
            "MARKER_PAD_TOP",
            "MARKER_EXTRA_W",
            "MARKER_EXTRA_H",
            "STAR_NUM_WIDTH_CAP",
            "STAR_X0_BACKOFF",
            "STAR_X0_MIN_OFFSET",
            "UNCHANGED_LIMIT",
            "ZERO_STAGE_CONFIRM",
        }
    )

    # 关卡编号 token：1-2 位数字开头，允许 OCR 把右侧装饰误读进来（如 "01/3"）
    NUM_RE = re.compile(r"^[^\dA-Za-z\u4e00-\u9fff]{0,3}\s*(\d{1,2})([^\d].*)?$")

    # 星标判定阈值（HSV，S/V 范围 0-255），由实机灰星/亮星取样数据确定：
    # 灰星邻域高饱和亮像素 = 0；亮星当期活动 ≈ 120+，1987 等历史活动的细四角星
    # 仅 ≈ 27-62，故阈值取 15 以跨活动通用。VAL_MIN 须 >=150 以排除关卡名底下的
    # 墨绿圆盘装饰
    SAT_MIN = 100
    VAL_MIN = 160
    LIT_PIXELS = 15

    # 星标搜索区相对编号 OCR 框的扩展（星标位于编号右侧约 30~90px，同行）
    ZONE_PAD_LEFT = 5
    ZONE_PAD_TOP = 30
    ZONE_EXTRA_W = 115
    ZONE_EXTRA_H = 20

    # Keep OCR candidates on the activity stage rail only. This rejects edge
    # UI, route decorations, and partially visible OCR boxes before star checks.
    # X_MAX 须 >=1240：地图滑到尽头时最后一关可能停在屏幕右缘（唐人街影话
    # 21 关 cx=1226），过滤掉会被永久跳过
    STAGE_BOX_CENTER_X_MIN = 120
    STAGE_BOX_CENTER_X_MAX = 1240
    STAGE_BOX_CENTER_Y_MIN = 535
    STAGE_BOX_CENTER_Y_MAX = 620
    STAGE_BOX_H_MIN = 10
    STAGE_BOX_H_MAX = 55

    # Three-difficulty stages show three star pairs. A difficulty is passed
    # once either star in its pair is lit; full-star cleanup is left manual.
    MULTI_STAR_WIDTH = 180
    MULTI_ZONE_EXTRA_W = 240
    STAR_ROW_UP = 35
    STAR_ROW_DOWN = 18
    MULTI_MARKER_PIXELS = 30
    DIFFICULTY_GROUPS = 3
    DIFFICULTY_LIT_PIXELS = 12

    # 地图页锚点：左上模式标签包含任一关键词即视为地图页
    ANCHOR_KEYWORDS = ("探索", "故事")

    # 滑到头签名中编号位置的量化粒度（容忍滑动到头后的像素级回弹）
    SIG_POS_QUANT = 50

    # 三难度红色标记的颜色掩码（BGR 取样自当期活动难度标记）
    MARKER_R_MIN = 120
    MARKER_G_MIN = 45
    MARKER_G_MAX = 150
    MARKER_B_MAX = 95
    MARKER_S_MIN = 80
    MARKER_RG_DIFF = 25

    # 三难度红色标记搜索区相对编号框的偏移
    MARKER_PAD_LEFT = 95
    MARKER_PAD_TOP = 10
    MARKER_EXTRA_W = 25
    MARKER_EXTRA_H = 65

    # 三难度星标行起点相对编号框的推算参数
    STAR_NUM_WIDTH_CAP = 62
    STAR_X0_BACKOFF = 8
    STAR_X0_MIN_OFFSET = 25

    # 滑动到头检测状态（类属性，跨调用保留）
    _last_signature: tuple | None = None
    _unchanged_swipes: int = 0
    _pending_zero_stage: tuple | None = None
    _pending_zero_count: int = 0
    UNCHANGED_LIMIT = 3
    ZERO_STAGE_CONFIRM = 2

    @classmethod
    def reset_swipe_state(cls) -> None:
        cls._last_signature = None
        cls._unchanged_swipes = 0
        cls._pending_zero_stage = None
        cls._pending_zero_count = 0

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        try:
            params = parse_params(argv.custom_recognition_param)
        except ValueError as e:
            logger.error(f"[AutoPromotion] 识别参数解析失败（{e}），使用全部默认值")
            params = {}
        query = params.get("query", "stage")
        self.apply_param_overrides(params)

        tokens = self._stage_numbers(context, argv.image)

        incomplete = []
        for text, num, box in tokens:
            complete, detail = self._stage_complete(argv.image, box, num, text)
            if not complete:
                incomplete.append((text, num, box, detail))

        if query == "stage":
            if not incomplete:
                return None
            # 锚点校验：关卡详情页底部也有缩略关卡条（数字 token），
            # 没有左上模式标签锚点就不是地图页，不能找关点击
            if not self._is_explore_map(context, argv.image):
                return None
            text, num, box, detail = min(incomplete, key=lambda item: item[1])
            if self._needs_zero_stage_confirm(detail):
                signature = (num, box[0] // 20, box[1] // 20)
                if signature == APMapAnalyze._pending_zero_stage:
                    APMapAnalyze._pending_zero_count += 1
                else:
                    APMapAnalyze._pending_zero_stage = signature
                    APMapAnalyze._pending_zero_count = 1
                if APMapAnalyze._pending_zero_count < self.ZERO_STAGE_CONFIRM:
                    logger.info(
                        f"[AutoPromotion] 关卡 {text} 亮星暂为 0，等待下一帧确认"
                    )
                    return None
            logger.info(f"[AutoPromotion] 关卡 {text} 未完成（{detail}），进入")
            APMapAnalyze.reset_swipe_state()
            return CustomRecognition.AnalyzeResult(box=box, detail={"stage": text})

        if incomplete:
            return None  # 还有未完成关卡，无需滑动/结束

        # swipe/done 用「探索模式」标签锚定地图页：章节交界处底部没有关卡编号，
        # 不能拿编号判断是否在地图页
        if not self._is_explore_map(context, argv.image):
            return None

        if query == "swipe":
            if APMapAnalyze._unchanged_swipes >= self.UNCHANGED_LIMIT:
                return None  # 已确认到尽头，交给 done
            # 滑到头判定用底部编号签名：编号集合（含量化位置）连续多次不变
            # 即到头。不能用画面哈希——1987 等活动的星空背景有持续动画，
            # 静止画面的哈希也不稳定。章节交界处编号为空：不计数也不重置，
            # 滑过交界后继续累计
            if tokens:
                signature = tuple(
                    (num, box[0] // self.SIG_POS_QUANT) for _, num, box in tokens
                )
                if signature == APMapAnalyze._last_signature:
                    APMapAnalyze._unchanged_swipes += 1
                else:
                    APMapAnalyze._unchanged_swipes = 0
                    APMapAnalyze._last_signature = signature
            if APMapAnalyze._unchanged_swipes >= self.UNCHANGED_LIMIT:
                return None
            logger.info("[AutoPromotion] 当前画面无未完成关卡，向后滑动地图")
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        if query == "done":
            if APMapAnalyze._unchanged_swipes >= self.UNCHANGED_LIMIT:
                logger.info("[AutoPromotion] 地图已到尽头且无未完成关卡，推图完成")
                APMapAnalyze.reset_swipe_state()
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
            return None

        logger.error(f"[AutoPromotion] 无效 query: {query}")
        return None

    def _is_explore_map(self, context: Context, image) -> bool:
        """地图页左上角常驻模式标签（探索模式/故事模式），章节交界处也在；
        对话/主界面没有。"""
        detail = context.run_recognition("APExploreAnchorOCR", image)
        return any(
            any(word in result.text for word in self.ANCHOR_KEYWORDS)
            for result in ocr_results(detail)
        )

    def _stage_numbers(
        self, context: Context, image
    ) -> list[tuple[str, int, list[int]]]:
        """OCR 地图底部条，返回 (原文, 编号, box)，按编号升序。"""
        detail = context.run_recognition("APStageNumberOCR", image)
        tokens = []
        for result in ocr_results(detail):
            box = list(result.box)
            parsed = self._parse_stage_number(result.text.strip(), box)
            if parsed is None:
                continue
            num, stage_box = parsed
            if self._is_stage_box(stage_box):
                tokens.append((result.text.strip(), num, stage_box))
        tokens.sort(key=lambda item: item[1])
        return tokens

    def _parse_stage_number(
        self, text: str, box: list[int]
    ) -> tuple[int, list[int]] | None:
        text = text.strip()
        m = self.NUM_RE.match(text)
        if m:
            return int(m.group(1)), box

        # OCR can merge the stage number with nearby stars or marker strokes,
        # e.g. stage 13 becomes "A1333". In that shape, the first two digits
        # are the stage number and the trailing repeated digits are star noise.
        if re.search(r"[\u4e00-\u9fff]", text):
            return None

        compact = re.sub(r"\s+", "", text)
        m = re.match(r"^[^\d]{0,3}(\d{2})(\d{2,})$", compact)
        if not m:
            return None

        stage, noise = m.groups()
        if len(set(noise)) == 1:
            return int(stage), box
        return None

    def _is_stage_box(self, box: list[int]) -> bool:
        cx = box[0] + box[2] / 2
        cy = box[1] + box[3] / 2
        return (
            self.STAGE_BOX_CENTER_X_MIN <= cx <= self.STAGE_BOX_CENTER_X_MAX
            and self.STAGE_BOX_CENTER_Y_MIN <= cy <= self.STAGE_BOX_CENTER_Y_MAX
            and self.STAGE_BOX_H_MIN <= box[3] <= self.STAGE_BOX_H_MAX
        )

    def _lit_pixel_count(self, image, box: list[int]) -> int:
        """统计编号邻域内高饱和高亮像素数（亮星像素）。image 为 BGR ndarray。"""
        h_img, w_img = image.shape[:2]
        x0 = max(box[0] - self.ZONE_PAD_LEFT, 0)
        y0 = max(box[1] - self.ZONE_PAD_TOP, 0)
        x1 = min(box[0] + box[2] + self.ZONE_EXTRA_W, w_img)
        y1 = min(box[1] + box[3] + self.ZONE_EXTRA_H, h_img)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return 0
        c = crop.astype(np.int32)
        v = c.max(axis=2)
        s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)
        return int(((v >= self.VAL_MIN) & (s >= self.SAT_MIN)).sum())

    def _stage_complete(
        self, image, box: list[int], stage_num: int, text: str = ""
    ) -> tuple[bool, str]:
        lit = self._lit_pixel_count(image, box)
        groups = self._multi_difficulty_groups(image, box, text)
        if groups is None:
            return lit >= self.LIT_PIXELS, f"亮像素 {lit}"

        complete = all(groups)
        progress = "".join("1" if item else "0" for item in groups)
        return complete, f"三难度 {progress}，亮像素 {lit}"

    def _needs_zero_stage_confirm(self, detail: str) -> bool:
        return detail == "亮像素 0"

    def _multi_difficulty_groups(
        self, image, box: list[int], text: str = ""
    ) -> list[bool] | None:
        if not self._looks_multi_difficulty(image, box, text):
            return None

        crop = self._star_row_crop(image, box)
        if crop.size == 0:
            return None

        c = crop.astype(np.int32)
        v = c.max(axis=2)
        s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)

        lit_mask = (v >= self.VAL_MIN) & (s >= self.SAT_MIN)
        result = []
        for idx in range(self.DIFFICULTY_GROUPS):
            x0 = self.MULTI_STAR_WIDTH * idx // self.DIFFICULTY_GROUPS
            x1 = self.MULTI_STAR_WIDTH * (idx + 1) // self.DIFFICULTY_GROUPS
            result.append(int(lit_mask[:, x0:x1].sum()) >= self.DIFFICULTY_LIT_PIXELS)
        return result

    def _looks_multi_difficulty(self, image, box: list[int], text: str = "") -> bool:
        if self._has_multi_text_prefix(text):
            return True

        crop = self._multi_marker_crop(image, box)
        if crop.size == 0:
            return False

        c = crop.astype(np.int32)
        b = c[..., 0]
        g = c[..., 1]
        r = c[..., 2]
        v = c.max(axis=2)
        s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)
        marker = (
            (r >= self.MARKER_R_MIN)
            & (g >= self.MARKER_G_MIN)
            & (g <= self.MARKER_G_MAX)
            & (b <= self.MARKER_B_MAX)
            & (s >= self.MARKER_S_MIN)
            & (r - g >= self.MARKER_RG_DIFF)
        )
        return int(marker.sum()) >= self.MULTI_MARKER_PIXELS

    def _has_multi_text_prefix(self, text: str) -> bool:
        return bool(
            re.match(r"^[^\dA-Za-z\u4e00-\u9fff]{1,3}\s*\d", text.strip())
        )

    def _star_row_crop(self, image, box: list[int]):
        h_img, w_img = image.shape[:2]
        x0 = self._star_x0(box, w_img)
        y0 = max(box[1] - self.STAR_ROW_UP, 0)
        x1 = min(x0 + self.MULTI_STAR_WIDTH, w_img)
        y1 = min(box[1] + self.STAR_ROW_DOWN, h_img)
        return image[y0:y1, x0:x1]

    def _multi_marker_crop(self, image, box: list[int]):
        h_img, w_img = image.shape[:2]
        x0 = max(box[0] - self.MARKER_PAD_LEFT, 0)
        y0 = max(box[1] - self.MARKER_PAD_TOP, 0)
        x1 = min(box[0] + self.MARKER_EXTRA_W, w_img)
        y1 = min(box[1] + self.MARKER_EXTRA_H, h_img)
        return image[y0:y1, x0:x1]

    def _star_x0(self, box: list[int], image_width: int) -> int:
        number_width = min(box[2], self.STAR_NUM_WIDTH_CAP)
        return max(
            min(
                box[0] + max(number_width - self.STAR_X0_BACKOFF, self.STAR_X0_MIN_OFFSET),
                image_width,
            ),
            0,
        )
