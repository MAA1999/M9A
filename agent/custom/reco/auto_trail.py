import re
from typing import Any

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import logger
from utils.maa_types import ocr_results
from utils.params import ParamOverrideMixin, parse_params


@AgentServer.custom_recognition("ATTrailAnalyze")
class ATTrailAnalyze(ParamOverrideMixin, CustomRecognition):
    """
    活动小径任务流程分析。

    小径任务只有两种形态（用户确认）：
    1. 阅读型：点橙色交互框 -> 弹出米白阅读面板 -> 点面板外关闭 -> 任务完成
    2. 对话型：点橙色交互框 -> 进入对话场景 -> 空白处连点 -> 推完自动退回地图
       橙框变「完成」-> 点击 -> 任务从列表消失

    界面判别全部基于像素统计 + OCR，不依赖具体任务文案：
    - orange:   镜头居中后橙色交互框位置固定，统计 ROI 内高饱和橙色像素
    - reading:  屏幕中央大片米白纸张色（亮且低饱和）
    - dialogue: 非地图页（底部无关卡编号条）且全屏大面积极暗，连续两帧确认
    - task:     地图页且列表区有任务项，返回最上面一项
    - done:     地图页且列表区无任务项，或反复点击同一项无响应（剩余全为锁定项）

    地图页判定复用推图的 APExploreAnchorOCR（左上「探索模式」标签）：
    小径列表完成数量多了会向上滚动，「小径」标题会滚出屏幕，不能作为锚点；
    任务少到一定数量后标题会彻底消失，列表里只剩任务项。
    标题可点击折叠/展开列表——若启动时列表被收起（无任务项但标题在），
    先点标题展开，避免误判全部完成。

    参数格式 (custom_recognition_param):
    {
        "query": "orange" | "reading" | "dialogue" | "task" | "done",
        // 其余 key 为可选的识别参数覆盖（类常量名小写，如 "orange_min_pixels": 1500），
        // 见 OVERRIDABLE 白名单与协议文档的契约参数表
    }
    """

    OVERRIDABLE = frozenset(
        {
            "ORANGE_ROI",
            "ORANGE_MIN_PIXELS",
            "ORANGE_CLICK_BOX",
            "ORANGE_R_MIN",
            "ORANGE_G_MIN",
            "ORANGE_G_MAX",
            "ORANGE_B_MAX",
            "ORANGE_S_MIN",
            "ORANGE_V_MIN",
            "READ_ROI",
            "READ_RATIO",
            "READ_CLOSE_BOX",
            "CREAM_V_MIN",
            "CREAM_S_MAX",
            "DARK_V_MAX",
            "DIALOG_DARK_RATIO",
            "DIALOG_CLICK_BOX",
            "DIALOG_CONFIRM",
            "DIALOG_STUCK_LIMIT",
            "SIG_GRID",
            "SIG_QUANT",
            "ITEM_Y_MIN",
            "ITEM_Y_MAX",
            "ITEM_X_MAX",
            "TASK_REPEAT_LIMIT",
            "TITLE_CLICK_LIMIT",
        }
    )

    # 橙色交互框（倾听讨论/捡起它/完成等），镜头自动居中后位置固定。
    # 实机取样：有框 orange_px≈6500-7000，无框/对话/阅读面板均为 0
    ORANGE_ROI = (730, 295, 180, 100)
    ORANGE_MIN_PIXELS = 2000
    ORANGE_CLICK_BOX = [760, 318, 114, 49]

    # 阅读面板：中央大片米白。实机取样：面板 0.83，其余 ≤0.03
    READ_ROI = (400, 250, 480, 200)
    READ_RATIO = 0.5
    READ_CLOSE_BOX = [1080, 80, 40, 40]

    # 对话场景：实机取样暗像素占比 0.86-0.95（阅读面板 0.43）。
    # 地图页也可能很暗，但地图页底部有关卡编号条被排除。
    # 点击位必须避开对话气泡（长对话气泡会堆满屏幕中部，点气泡不推进），
    # 取右下角空白区
    DIALOG_DARK_RATIO = 0.75
    DIALOG_CLICK_BOX = [1100, 620, 80, 40]
    DIALOG_CONFIRM = 2
    DIALOG_STUCK_LIMIT = 12

    # 橙色交互框像素的颜色掩码（BGR，实机取样）
    ORANGE_R_MIN = 180
    ORANGE_G_MIN = 80
    ORANGE_G_MAX = 170
    ORANGE_B_MAX = 100
    ORANGE_S_MIN = 120
    ORANGE_V_MIN = 180

    # 阅读面板米白像素判定（亮且低饱和）
    CREAM_V_MIN = 180
    CREAM_S_MAX = 60

    # 对话场景暗像素判定
    DARK_V_MAX = 60

    # 对话卡死检测的全屏网格哈希粒度
    SIG_GRID = 8
    SIG_QUANT = 16

    # 地图页锚点关键词（同 APMapAnalyze）
    ANCHOR_KEYWORDS = ("探索", "故事")

    # 小径列表（地图页左侧）。列表会随完成进度向上滚动，任务项 y 范围放宽。
    # 排除词含「模式」：双按钮布局（1987/唐人街影话等）的故事/探索模式按钮
    # 落在列表区内，不能被当成任务项点击
    ITEM_Y_MIN = 170
    ITEM_Y_MAX = 440
    ITEM_X_MAX = 190
    ITEM_EXCLUDES = ("模式", "开启")
    TASK_REPEAT_LIMIT = 4
    TITLE_CLICK_LIMIT = 2

    CJK_RE = re.compile(r"[一-鿿]")

    # 跨调用状态（类属性）
    _task_sig: tuple[Any, ...] | None = None
    _task_repeat: int = 0
    _dialog_sig: bytes | None = None
    _dialog_same: int = 0
    _dialog_pending: int = 0
    _title_clicks: int = 0

    @classmethod
    def reset_state(cls) -> None:
        cls._task_sig = None
        cls._task_repeat = 0
        cls._dialog_sig = None
        cls._dialog_same = 0
        cls._dialog_pending = 0
        cls._title_clicks = 0

    @classmethod
    def _reset_task_counter(cls) -> None:
        cls._task_sig = None
        cls._task_repeat = 0

    @classmethod
    def _reset_dialog_counter(cls) -> None:
        cls._dialog_sig = None
        cls._dialog_same = 0
        cls._dialog_pending = 0

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        try:
            params = parse_params(argv.custom_recognition_param)
        except ValueError as e:
            logger.error(f"[AutoTrail] 识别参数解析失败（{e}），使用全部默认值")
            params = {}
        query = params.get("query", "task")
        self.apply_param_overrides(params)

        if query == "orange":
            return self._analyze_orange(argv.image)
        if query == "reading":
            return self._analyze_reading(argv.image)
        if query == "dialogue":
            return self._analyze_dialogue(context, argv.image)
        if query == "task":
            return self._analyze_task(context, argv.image)
        if query == "done":
            return self._analyze_done(context, argv.image)

        logger.error(f"[AutoTrail] 无效 query: {query}")
        return None

    # ---- 像素统计（image 为 BGR ndarray） ----

    @staticmethod
    def _crop(image: Any, roi: tuple[int, int, int, int]) -> Any:
        x, y, w, h = roi
        return image[y : y + h, x : x + w].astype(np.int32)

    def _orange_pixels(self, image: Any) -> int:
        c = self._crop(image, self.ORANGE_ROI)
        b, g, r = c[..., 0], c[..., 1], c[..., 2]
        v = c.max(axis=2)
        s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)
        mask = (
            (r >= self.ORANGE_R_MIN)
            & (g >= self.ORANGE_G_MIN)
            & (g <= self.ORANGE_G_MAX)
            & (b <= self.ORANGE_B_MAX)
            & (s >= self.ORANGE_S_MIN)
            & (v >= self.ORANGE_V_MIN)
        )
        return int(mask.sum())

    def _cream_ratio(self, image: Any) -> float:
        c = self._crop(image, self.READ_ROI)
        v = c.max(axis=2)
        s = (v - c.min(axis=2)) * 255 // np.maximum(v, 1)
        return float(((v >= self.CREAM_V_MIN) & (s <= self.CREAM_S_MAX)).mean())

    def _dark_ratio(self, image: Any) -> float:
        v = image.astype(np.int32).max(axis=2)
        return float((v < self.DARK_V_MAX).mean())

    def _screen_signature(self, image: Any) -> bytes:
        h, w = image.shape[:2]
        gray = image.astype(np.int32).max(axis=2)
        n = self.SIG_GRID
        grid = gray[: h - h % n, : w - w % n]
        grid = grid.reshape(n, h // n, n, w // n).mean(axis=(1, 3))
        return (grid // self.SIG_QUANT).astype(np.uint8).tobytes()

    # ---- 地图页判定与列表区 OCR ----

    def _is_map_page(self, context: Context, image: Any) -> bool:
        """地图页判定（活动模式标签 / 主线编号条），复用推图的通用判定。"""
        from custom.reco.auto_promotion import is_stage_map

        return is_stage_map(context, image)

    def _scan_list(self, context: Context, image: Any) -> tuple[list[Any] | None, list[Any]]:
        """返回 (「小径」标题 box 或 None, 任务项列表[(text, box)])，任务项按 y 升序。"""
        detail = context.run_recognition("ATTrailListOCR", image)
        title_box = None
        items = []
        for result in ocr_results(detail):
            text = result.text.strip()
            box = list(result.box)
            cy = box[1] + box[3] / 2
            if "小径" in text:
                title_box = box
                continue
            if any(word in text for word in self.ITEM_EXCLUDES):
                continue
            if (
                self.ITEM_Y_MIN <= cy <= self.ITEM_Y_MAX
                and box[0] + box[2] / 2 <= self.ITEM_X_MAX
                and self.CJK_RE.search(text)
            ):
                items.append((text, box))
        items.sort(key=lambda item: item[1][1])
        return title_box, items

    # ---- 各 query ----

    def _analyze_orange(self, image: Any) -> CustomRecognition.AnalyzeResult | RectType | None:
        count = self._orange_pixels(image)
        if count < self.ORANGE_MIN_PIXELS:
            return None
        ATTrailAnalyze._reset_task_counter()
        ATTrailAnalyze._reset_dialog_counter()
        logger.info(f"[AutoTrail] 命中橙色交互框（橙像素 {count}），点击")
        return CustomRecognition.AnalyzeResult(box=self.ORANGE_CLICK_BOX, detail={"orange": count})

    def _analyze_reading(self, image: Any) -> CustomRecognition.AnalyzeResult | RectType | None:
        ratio = self._cream_ratio(image)
        if ratio < self.READ_RATIO:
            return None
        ATTrailAnalyze._reset_task_counter()
        ATTrailAnalyze._reset_dialog_counter()
        logger.info(f"[AutoTrail] 命中阅读面板（米白占比 {ratio:.2f}），点击关闭")
        return CustomRecognition.AnalyzeResult(box=self.READ_CLOSE_BOX, detail={"cream": round(ratio, 2)})

    def _analyze_dialogue(self, context: Context, image: Any) -> CustomRecognition.AnalyzeResult | RectType | None:
        if self._dark_ratio(image) < self.DIALOG_DARK_RATIO or self._is_map_page(context, image):
            ATTrailAnalyze._dialog_pending = 0
            return None

        # 连续两帧确认，避免地图跳转动画瞬间误判
        ATTrailAnalyze._dialog_pending += 1
        if ATTrailAnalyze._dialog_pending < self.DIALOG_CONFIRM:
            return None

        # 画面长时间不变说明点击无效（对话推不动），放弃命中走超时兜底
        sig = self._screen_signature(image)
        if sig == ATTrailAnalyze._dialog_sig:
            ATTrailAnalyze._dialog_same += 1
        else:
            ATTrailAnalyze._dialog_sig = sig
            ATTrailAnalyze._dialog_same = 0
        if ATTrailAnalyze._dialog_same >= self.DIALOG_STUCK_LIMIT:
            if ATTrailAnalyze._dialog_same == self.DIALOG_STUCK_LIMIT:
                logger.warning("[AutoTrail] 对话画面长时间无变化，停止点击")
            return None

        ATTrailAnalyze._reset_task_counter()
        return CustomRecognition.AnalyzeResult(box=self.DIALOG_CLICK_BOX, detail={})

    def _analyze_task(self, context: Context, image: Any) -> CustomRecognition.AnalyzeResult | RectType | None:
        if not self._is_map_page(context, image):
            return None
        title_box, items = self._scan_list(context, image)

        if not items:
            # 无任务项但标题在：列表可能被手动收起，点标题展开确认
            if title_box is not None and ATTrailAnalyze._title_clicks < self.TITLE_CLICK_LIMIT:
                ATTrailAnalyze._title_clicks += 1
                logger.info(
                    f"[AutoTrail] 列表无任务项但「小径」标题在，点标题展开（第 {ATTrailAnalyze._title_clicks} 次）"
                )
                return CustomRecognition.AnalyzeResult(box=title_box, detail={"expand": True})
            return None
        ATTrailAnalyze._title_clicks = 0
        if ATTrailAnalyze._task_repeat >= self.TASK_REPEAT_LIMIT:
            return None  # 反复点击无响应，交给 done

        text, box = items[0]
        sig = (text, box[1] // 20)
        if sig == ATTrailAnalyze._task_sig:
            ATTrailAnalyze._task_repeat += 1
        else:
            ATTrailAnalyze._task_sig = sig
            ATTrailAnalyze._task_repeat = 1
        ATTrailAnalyze._reset_dialog_counter()
        logger.info(f"[AutoTrail] 小径任务「{text}」（第 {ATTrailAnalyze._task_repeat} 次点击），进入")
        return CustomRecognition.AnalyzeResult(box=box, detail={"task": text})

    def _analyze_done(self, context: Context, image: Any) -> CustomRecognition.AnalyzeResult | RectType | None:
        if not self._is_map_page(context, image):
            return None
        title_box, items = self._scan_list(context, image)
        if not items:
            # 标题在且还没点过展开时，先让 task 试着展开列表
            if title_box is not None and ATTrailAnalyze._title_clicks < self.TITLE_CLICK_LIMIT:
                return None
            logger.info("[AutoTrail] 小径列表已空，全部任务完成")
        elif ATTrailAnalyze._task_repeat >= self.TASK_REPEAT_LIMIT:
            logger.info("[AutoTrail] 剩余列表项反复点击无响应（应为未解锁任务），小径完成")
        else:
            return None
        ATTrailAnalyze.reset_state()
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
