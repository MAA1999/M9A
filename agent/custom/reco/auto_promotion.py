import re
from difflib import SequenceMatcher
from typing import Any

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import logger
from utils.maa_types import is_hit, ocr_results
from utils.params import ParamOverrideMixin, parse_params


def is_stage_map(context: Context, image: Any) -> bool:
    """关卡地图页判定（活动与主线通用）。

    活动地图左上有「探索模式/故事模式」标签；主线地图没有模式按钮，
    退而验证底部有关卡编号 token 且无「开始行动」按钮（关卡详情页底部
    也有缩略编号条，但详情页必有开始行动按钮，以此区分）。
    """
    detail = context.run_recognition("APExploreAnchorOCR", image)
    if any(any(word in r.text for word in ("探索", "探险", "故事")) for r in ocr_results(detail)):
        return True
    if not APMapAnalyze()._stage_numbers(context, image):
        return False
    return not is_hit(context.run_recognition("AP_StartAction", image))


def _stage_map_mode_detail(context: Context, image: Any) -> tuple[str | None, Any | None]:
    """Best-effort map type for mode dispatch.

    Activity maps expose story/explore text near the top-left mode switch.
    Main-story maps do not, so they fall back to the generic stage-map check.
    Single-button activity layouts show the *target* mode on the switch; a
    visible story button means the current page is explore, and vice versa.
    When both labels are visible (known historical dual-button layout), callers
    should click the desired mode explicitly instead of inferring current mode.
    """
    detail = context.run_recognition("APExploreAnchorOCR", image)
    results = ocr_results(detail)
    explore_result = next(
        (r for r in results if any(word in r.text for word in ("探索", "探险"))),
        None,
    )
    story_result = next((r for r in results if "故事" in r.text), None)

    if story_result and explore_result:
        return "activity", None
    if story_result:
        return "explore", story_result.box
    if explore_result:
        return "story", explore_result.box
    if is_stage_map(context, image):
        return "plain", None
    return None, None


def stage_map_mode(context: Context, image: Any) -> str | None:
    mode, _ = _stage_map_mode_detail(context, image)
    return mode


@AgentServer.custom_recognition("APModeGate")
class APModeGate(CustomRecognition):
    """
    活动推图模式调度闸门。

    参数格式 (custom_recognition_param):
    {
        "query": "main"
    }
    - main: 命中主线地图（无故事/探索模式按钮，但 is_stage_map 成立）。
    - story/explore: 命中单按钮切换布局的当前模式，并返回该按钮位置。
      注意单按钮文字表示切换目标：显示「故事」代表当前为 explore，
      显示「探索/探险」代表当前为 story。
      历史活动若同时显示「故事」「探索」，不由此闸门判定当前模式。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        query = parse_params(argv.custom_recognition_param).get("query", "main")
        mode, box = _stage_map_mode_detail(context, argv.image)

        if query == "main":
            if mode == "plain":
                logger.info("[AutoPromotion] 当前为主线地图，直接推图")
                APMapAnalyze.reset_swipe_state()
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={"mode": mode})
            return None

        if query in {"story", "explore"}:
            if mode == query:
                logger.info(f"[AutoPromotion] 当前已在{query}模式")
                APMapAnalyze.reset_swipe_state()
                return CustomRecognition.AnalyzeResult(box=box or [0, 0, 0, 0], detail={"mode": mode})
            return None

        logger.error(f"[AutoPromotion] 无效模式闸门 query: {query}")
        return None


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

    _visited: set[str] = set()

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

        # 探索阶段仅活动地图有效：主线地图没有模式切换按钮，直接跳过。
        # 单按钮活动布局的文字表示切换目标，探索页可能显示「故事」。
        if query == "explore":
            mode = stage_map_mode(context, argv.image)
            if mode in {None, "plain"}:
                logger.info("[AutoPromotion] 当前地图无探索模式，跳过探索阶段")
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
        "query": "nav" | "card" | "rewind" | "swipe" | "notfound" | "pv",
        "card_name": "唐人街影话"   // 目标卡片名（标题子串匹配）
    }
    - nav:      card_name 为空或「当前页面」时不命中（跳过导航直接推图），
                否则命中进入导航循环
    - card:     映像页卡片标题含 card_name 则命中，返回卡片点击区
    - rewind:   先把横排列表回卷到最左（右滑），连续两次标题集合不变即回卷完成
    - swipe:    回卷完成后向右逐屏查找（左滑），到头停止命中
    - notfound: 查找到头仍未发现目标卡片，命中后报错结束
    - pv:       首次进入卡片会播放 PV（全屏几乎无文字），命中后点屏幕中央
                唤出右上角跳过按钮（交给公共 SkipButton 节点点击）
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

    # PV 判定：全屏 OCR 文本 token 数上限（PV 播放中几乎无 UI 文字）与
    # 唤出点击的次数上限（防止在真未知界面无限点击吞掉超时兜底）
    PV_MAX_TOKENS = 3
    PV_TAP_LIMIT = 15
    PV_TAP_BOX = (615, 350, 50, 30)

    # Stable OCR fallbacks observed on real image cards. Keep these explicit so
    # short fragments like "往事" do not become a global fuzzy-match rule.
    TITLE_ALIASES = {
        "朔日手记": ("朔手记", "朔记", "朔日记"),
        "7号往事": ("往事", "号往事"),
    }

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
            "PV_MAX_TOKENS",
            "PV_TAP_LIMIT",
            "PV_TAP_BOX",
        }
    )

    _rewind_sig: tuple[Any, ...] | None = None
    _rewind_same: int = 0
    _rewind_done: bool = False
    _forward_sig: tuple[Any, ...] | None = None
    _forward_same: int = 0
    _pv_taps: int = 0
    _card_pending: tuple[Any, ...] | None = None
    _seen_non_map: bool = False

    @classmethod
    def reset_nav_state(cls) -> None:
        cls._rewind_sig = None
        cls._rewind_same = 0
        cls._rewind_done = False
        cls._forward_sig = None
        cls._forward_same = 0
        cls._pv_taps = 0
        cls._card_pending = None
        cls._seen_non_map = False

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

        if query == "arrived":
            # 必须先离开过地图页再回到地图页才算到达：启动时若已在某张
            # 地图页（可能是别的活动的），直接判到达会在错误的地图上推图
            if not is_stage_map(context, argv.image):
                APCardFinder._seen_non_map = True
                return None
            # 活动入口界面（有「步入剧情」按钮）被 APExploreAnchorOCR 误判为地图页时的防御：
            # 入口界面不是关卡地图，需先点「步入剧情」才进入地图
            if is_hit(context.run_recognition("AP_NavStoryEnter", argv.image)):
                APCardFinder._seen_non_map = True
                return None
            # 卡片详情页（有「活动正篇/主线正篇」按钮）被 APStageNumberOCR 误判为地图页时的防御：
            # 详情页标题含活动编号（如「77号往事」），OCR 把「77」误读为关卡号；
            # 需先点「活动正篇」才进入关卡地图
            if is_hit(context.run_recognition("AP_NavMainEntry", argv.image)):
                APCardFinder._seen_non_map = True
                return None
            if not APCardFinder._seen_non_map:
                return None
            logger.info("[AutoPromotion] 已到达关卡地图页，导航完成")
            APCardFinder.reset_nav_state()
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        if query == "pv":
            if APCardFinder._pv_taps >= self.PV_TAP_LIMIT:
                return None
            detail = context.run_recognition("APNavFullOCR", argv.image)
            tokens = [r for r in ocr_results(detail) if len(r.text.strip()) >= 2]
            if len(tokens) > self.PV_MAX_TOKENS:
                return None
            APCardFinder._pv_taps += 1
            logger.info(f"[AutoPromotion] 疑似 PV 播放中（第 {APCardFinder._pv_taps} 次），点击唤出跳过按钮")
            return CustomRecognition.AnalyzeResult(box=self.PV_TAP_BOX, detail={})

        # 「当期活动」走主页版本名 -> 步入剧情链（AP_NavCurrentEntry /
        # AP_NavStoryEnter 节点），不进映像页查找逻辑
        if target == "当期活动":
            return None

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
                    # 双帧位置确认：滑动动量未停时识别帧与点击时刻画面错位，
                    # 会点中相邻卡片。位置连续两帧一致（量化 30px）才命中
                    sig = (text, box[0] // 30)
                    if sig != APCardFinder._card_pending:
                        APCardFinder._card_pending = sig
                        return None
                    # 不重置导航状态：若点击未生效（卡片在屏边、过渡动画等），
                    # 下一轮 card 仍会命中并重试点击，而不是被回卷滑走
                    logger.info(f"[AutoPromotion] 找到卡片「{text}」，点击进入")
                    body = [
                        max(box[0], 0),
                        self.CARD_BODY_Y,
                        max(box[2], self.CARD_BODY_MIN_W),
                        self.CARD_BODY_H,
                    ]
                    return CustomRecognition.AnalyzeResult(box=body, detail={"card": text})
            APCardFinder._card_pending = None
            return None

        if not titles:
            return None  # 不在映像页（卡片标题行无内容）
        signature = tuple(sorted(self._signature_text(text) for text, _ in titles))

        # 目标卡片已进入双帧确认，滑动节点让位等待 card 确认点击
        if APCardFinder._card_pending is not None and query in ("rewind", "swipe"):
            return None

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
            if APCardFinder._rewind_done and (APCardFinder._forward_same >= self.FORWARD_LIMIT):
                logger.error(f"[AutoPromotion] 卡片列表已扫完，未找到「{target}」")
                APCardFinder.reset_nav_state()
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
            return None

        logger.error(f"[AutoPromotion] 无效 query: {query}")
        return None

    @staticmethod
    def _title_match(target: str, text: str) -> bool:
        """标题匹配：屏幕边缘的卡片标题会被截断（如「87宇宙组曲」），
        除正向子串外也接受足够长的残缺标题反向匹配。

        实机 OCR 偶尔会漏/错单字（如「绿湖噩梦」识别成「绿湖疆梦」、
        「圣火纪行：东区黎明」漏掉「火」）。在长度接近时使用保守的
        相似度兜底，避免可见卡片因为单字漂移而永远找不到。
        """
        t = text.replace(" ", "").strip()
        if not t:
            return False
        if target in t or (len(t) >= 4 and t in target):
            return True
        if t in APCardFinder.TITLE_ALIASES.get(target, ()):
            return True
        if len(target) < 4 or len(t) < 4:
            return False
        if abs(len(target) - len(t)) > max(2, len(target) // 3):
            return False
        return SequenceMatcher(None, target, t).ratio() >= 0.74

    @staticmethod
    def _signature_text(text: str) -> str:
        """Normalize unstable OCR variants used only for scroll-end signatures."""
        return text.replace(" ", "").replace("於", "于").strip()

    def _is_image_page(self, context: Context, image: Any) -> bool:
        detail = context.run_recognition("APImagePageOCR", image)
        return any("显影罐" in result.text for result in ocr_results(detail))

    def _card_titles(self, context: Context, image: Any) -> list[tuple[str, list[int]]]:
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
    - map:   命中关卡地图页，用于战斗等待循环回到地图后的出口
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
            "RIGHT_HALF_X",
            "RIGHT_EMPTY_CONFIRM",
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
            "ZERO_STAGE_CONFIRM",
            "STAGE_NUM_MIN",
            "STAGE_NUM_MAX",
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
    STAGE_NUM_MIN = 1
    STAGE_NUM_MAX = 30

    # Three-difficulty stages show three star pairs. A difficulty is passed
    # once either star in its pair is lit; full-star cleanup is left manual.
    MULTI_STAR_WIDTH = 180
    MULTI_ZONE_EXTRA_W = 240
    STAR_ROW_UP = 35
    STAR_ROW_DOWN = 18
    MULTI_MARKER_PIXELS = 60
    DIFFICULTY_GROUPS = 3
    DIFFICULTY_LIT_PIXELS = 12

    # 地图页锚点：左上模式标签包含任一关键词即视为地图页
    ANCHOR_KEYWORDS = ("探索", "探险", "故事")

    # 滑到头判定：屏幕右半（x > RIGHT_HALF_X）无关卡编号即认为最后一关已过，
    # 连续 RIGHT_EMPTY_CONFIRM 帧确认（章节交界处右半可能短暂无编号）
    RIGHT_HALF_X = 640
    RIGHT_EMPTY_CONFIRM = 2

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
    MARKER_EXTRA_H = 40

    # 三难度星标行起点相对编号框的推算参数
    STAR_NUM_WIDTH_CAP = 62
    STAR_X0_BACKOFF = 8
    STAR_X0_MIN_OFFSET = 25

    # 滑动到头检测状态（类属性，跨调用保留）
    _right_empty_count: int = 0
    _pending_zero_stage: tuple[Any, ...] | None = None
    _pending_zero_count: int = 0
    ZERO_STAGE_CONFIRM = 2

    @classmethod
    def reset_swipe_state(cls) -> None:
        cls._right_empty_count = 0
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

        if query == "map":
            if is_stage_map(context, argv.image):
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
            return None

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
            # 不在地图页（活动模式标签 / 主线编号条判定）不能找关点击
            if not is_stage_map(context, argv.image):
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
                    logger.info(f"[AutoPromotion] 关卡 {text} 亮星暂为 0，等待下一帧确认")
                    return None
            logger.info(f"[AutoPromotion] 关卡 {text} 未完成（{detail}），进入")
            APMapAnalyze.reset_swipe_state()
            return CustomRecognition.AnalyzeResult(box=box, detail={"stage": text})

        if incomplete:
            return None  # 还有未完成关卡，无需滑动/结束

        # swipe/done 锚定地图页（活动模式标签 / 主线编号条判定）：
        # 章节交界处底部没有编号，活动图不能只拿编号判断
        if not is_stage_map(context, argv.image):
            return None

        # 滑到头判定：屏幕右半没有关卡编号 = 最后一关已滑过屏幕中线。
        # 连续两帧确认（章节交界处右半可能短暂无编号）。
        # 不能用画面哈希（1987 星空背景持续动画，静止画面哈希也不稳定）
        right_has_stage = any(box[0] + box[2] / 2 > self.RIGHT_HALF_X for _, _, box in tokens)
        if right_has_stage:
            APMapAnalyze._right_empty_count = 0
        else:
            APMapAnalyze._right_empty_count += 1
        map_end = APMapAnalyze._right_empty_count >= self.RIGHT_EMPTY_CONFIRM

        if query == "swipe":
            if map_end:
                return None  # 已确认到尽头，交给 done
            logger.info("[AutoPromotion] 当前画面无未完成关卡，向后滑动地图")
            return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})

        if query == "done":
            if map_end:
                logger.info("[AutoPromotion] 地图已到尽头且无未完成关卡，推图完成")
                APMapAnalyze.reset_swipe_state()
                return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
            return None

        logger.error(f"[AutoPromotion] 无效 query: {query}")
        return None

    def _is_explore_map(self, context: Context, image: Any) -> bool:
        """地图页左上角常驻模式标签（探索模式/故事模式），章节交界处也在；
        对话/主界面没有。"""
        detail = context.run_recognition("APExploreAnchorOCR", image)
        return any(any(word in result.text for word in self.ANCHOR_KEYWORDS) for result in ocr_results(detail))

    def _stage_numbers(self, context: Context, image: Any) -> list[tuple[str, int, list[int]]]:
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

    def _parse_stage_number(self, text: str, box: list[int]) -> tuple[int, list[int]] | None:
        text = text.strip()
        m = self.NUM_RE.match(text)
        if m:
            return self._valid_stage_number(int(m.group(1)), box)

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
            return self._valid_stage_number(int(stage), box)
        return None

    def _valid_stage_number(self, stage_num: int, box: list[int]) -> tuple[int, list[int]] | None:
        if self.STAGE_NUM_MIN <= stage_num <= self.STAGE_NUM_MAX:
            return stage_num, box
        return None

    def _is_stage_box(self, box: list[int]) -> bool:
        cx = box[0] + box[2] / 2
        cy = box[1] + box[3] / 2
        return (
            self.STAGE_BOX_CENTER_X_MIN <= cx <= self.STAGE_BOX_CENTER_X_MAX
            and self.STAGE_BOX_CENTER_Y_MIN <= cy <= self.STAGE_BOX_CENTER_Y_MAX
            and self.STAGE_BOX_H_MIN <= box[3] <= self.STAGE_BOX_H_MAX
        )

    def _lit_pixel_count(self, image: Any, box: list[int]) -> int:
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

    def _stage_complete(self, image: Any, box: list[int], stage_num: int, text: str = "") -> tuple[bool, str]:
        lit = self._lit_pixel_count(image, box)
        # 单星判定优先：编号邻域有足够亮像素即视为已通关（含两颗星的普通关卡）。
        # 三难度分组仅在亮像素不足时介入，避免背景美术误触发多难度检测
        if lit >= self.LIT_PIXELS:
            return True, f"亮像素 {lit}"

        groups = self._multi_difficulty_groups(image, box, text)
        if groups is None:
            return False, f"亮像素 {lit}"

        complete = all(groups)
        progress = "".join("1" if item else "0" for item in groups)
        return complete, f"三难度 {progress}，亮像素 {lit}"

    def _needs_zero_stage_confirm(self, detail: str) -> bool:
        return detail == "亮像素 0"

    def _multi_difficulty_groups(self, image: Any, box: list[int], text: str = "") -> list[bool] | None:
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

    def _looks_multi_difficulty(self, image: Any, box: list[int], text: str = "") -> bool:
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
        return bool(re.match(r"^[^\dA-Za-z\u4e00-\u9fff]{1,3}\s*\d", text.strip()))

    def _star_row_crop(self, image: Any, box: list[int]) -> Any:
        h_img, w_img = image.shape[:2]
        x0 = self._star_x0(box, w_img)
        y0 = max(box[1] - self.STAR_ROW_UP, 0)
        x1 = min(x0 + self.MULTI_STAR_WIDTH, w_img)
        y1 = min(box[1] + self.STAR_ROW_DOWN, h_img)
        return image[y0:y1, x0:x1]

    def _multi_marker_crop(self, image: Any, box: list[int]) -> Any:
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
