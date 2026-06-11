import re

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import frame_buffer, logger
from utils.maa_types import ocr_results
from utils.params import parse_params


@AgentServer.custom_recognition("APMapAnalyze")
class APMapAnalyze(CustomRecognition):
    """
    活动推图地图分析。

    在地图底部条 OCR 关卡编号，编号右侧邻域找完成星标。
    判别不依赖具体颜色（官方每期会微调星标色调）：
    亮星 = 高饱和且高亮的像素簇；灰星 = 邻域内几乎没有高饱和亮像素。

    参数格式 (custom_recognition_param):
    {
        "query": "stage" | "swipe" | "done"
    }
    - stage: 命中并返回编号最小的未完成关卡的点击区域
    - swipe: 地图可见、无未完成关卡、且尚未确认滑到尽头时命中（供滑动节点使用）
    - done:  连续多次滑动后画面无变化（已到尽头）且无未完成关卡时命中（推图完成）
    """

    # 关卡编号 token：1-2 位数字开头，允许 OCR 把右侧装饰误读进来（如 "01/3"）
    NUM_RE = re.compile(r"^[^\dA-Za-z\u4e00-\u9fff]{0,3}\s*(\d{1,2})([^\d].*)?$")

    # 星标判定阈值（HSV，S/V 范围 0-255），由实机灰星/亮星取样数据确定：
    # 灰星邻域高饱和亮像素 = 0，亮星 ≈ 120+；VAL_MIN 须 >=150 以排除关卡名底下的墨绿圆盘装饰
    SAT_MIN = 100
    VAL_MIN = 160
    LIT_PIXELS = 40

    # 星标搜索区相对编号 OCR 框的扩展（星标位于编号右侧约 30~90px，同行）
    ZONE_PAD_LEFT = 5
    ZONE_PAD_TOP = 30
    ZONE_EXTRA_W = 115
    ZONE_EXTRA_H = 20

    # Keep OCR candidates on the activity stage rail only. This rejects edge
    # UI, route decorations, and partially visible OCR boxes before star checks.
    STAGE_BOX_CENTER_X_MIN = 120
    STAGE_BOX_CENTER_X_MAX = 1160
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

    # 滑动到头检测状态（类属性，跨调用保留）
    _last_signature: bytes | None = None
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

        frame_buffer.remember(argv.image)
        query = parse_params(argv.custom_recognition_param).get("query", "stage")
        tokens = self._stage_numbers(context, argv.image)

        incomplete = []
        for text, num, box in tokens:
            complete, detail = self._stage_complete(argv.image, box, num, text)
            if not complete:
                incomplete.append((text, num, box, detail))

        if query == "stage":
            if not incomplete:
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
            # 滑到头的判定用地图中部网格哈希：滑动中画面必变（含章节交界处），
            # 到头滑不动时画面才静止。编号签名在交界处恒为空，会误判到头
            signature = self._map_signature(argv.image)
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
        """地图页左上角常驻「探索模式」标签，章节交界处也在；对话/主界面没有。"""
        detail = context.run_recognition("APExploreAnchorOCR", image)
        return any("探索" in result.text for result in ocr_results(detail))

    @staticmethod
    def _map_signature(image) -> bytes:
        """地图中部区域 8x8 网格灰度哈希，避开左侧列表/顶部栏/底部条等常驻 UI。"""
        crop = image[150:480, 200:1080].astype(np.int32).max(axis=2)
        h, w = crop.shape
        grid = crop[: h - h % 8, : w - w % 8]
        grid = grid.reshape(8, h // 8, 8, w // 8).mean(axis=(1, 3))
        return (grid // 16).astype(np.uint8).tobytes()

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
            (r >= 120)
            & (g >= 45)
            & (g <= 150)
            & (b <= 95)
            & (s >= 80)
            & (r - g >= 25)
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
        x0 = max(box[0] - 95, 0)
        y0 = max(box[1] - 10, 0)
        x1 = min(box[0] + 25, w_img)
        y1 = min(box[1] + 65, h_img)
        return image[y0:y1, x0:x1]

    def _star_x0(self, box: list[int], image_width: int) -> int:
        number_width = min(box[2], 62)
        return max(min(box[0] + max(number_width - 8, 25), image_width), 0)
