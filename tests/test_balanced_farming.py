from types import SimpleNamespace

import numpy as np
from maa.define import BoxAndScoreResult, OCRResult, RecognitionDetail, Rect

from agent.custom.action.balanced_farming import BalancedFarmingAnalyze, warehouse_materials
from agent.utils.material_catalog import build_catalog, load_catalog


def _icon_detail(box: tuple[int, int, int, int] | None) -> RecognitionDetail:
    """图标匹配结果：box 为 None 时表示未命中。"""
    rect = Rect(*box) if box is not None else None
    return RecognitionDetail(
        reco_id=1,
        name="BF_ItemIcon",
        algorithm="TemplateMatch",
        hit=rect is not None,
        box=rect,
        all_results=[],
        filtered_results=[],
        best_result=BoxAndScoreResult(rect, 0.99) if rect is not None else None,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


def _count_detail(text: str, roi: list[int]) -> RecognitionDetail:
    """数量 OCR 结果：text 为空表示低于阈值被 MaaFW 过滤（best_result 为空）。"""
    rect = Rect(*roi)
    return RecognitionDetail(
        reco_id=2,
        name="BF_ItemCount",
        algorithm="OCR",
        hit=bool(text),
        box=rect,
        all_results=[],
        filtered_results=[OCRResult(rect, 0.9, text)] if text else [],
        best_result=OCRResult(rect, 0.9, text) if text else None,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


class _FakeContext:
    """最小 context 桩：按脚本返回图标/数量识别结果，并记录数量的 ROI。"""

    def __init__(self, icon_box: tuple[int, int, int, int] | None, text: str) -> None:
        self._icon_box = icon_box
        self._text = text
        self.count_rois: list[list[int]] = []

    def run_recognition(self, name: str, image: object, override: dict) -> RecognitionDetail:
        if name == "BF_ItemIcon":
            return _icon_detail(self._icon_box)
        roi = override[name]["recognition"]["param"]["roi"]
        self.count_rois.append(roi)
        return _count_detail(self._text, roi)


def _analyze() -> BalancedFarmingAnalyze:
    return BalancedFarmingAnalyze.__new__(BalancedFarmingAnalyze)


def test_warehouse_materials_skips_character_source() -> None:
    """货币类材料（source=character）不在仓库页，旧流程不能把它们算进「取最少」。"""
    raw = {
        "110103": {"name": "啮咬盒", "stage": "7-26", "level": "Hard"},
        "205": {"name": "微尘", "stage": "LP-06", "level": "None", "source": "character"},
        "203": {"name": "利齿子儿", "stage": "MA-06", "level": "None", "source": "character"},
    }
    catalog = build_catalog(raw, source="unit-test")
    assert set(warehouse_materials(catalog)) == {"110103"}

    assert warehouse_materials({}) == {}


def test_warehouse_materials_resolves_name_from_items_json() -> None:
    """目录不写 name 时名称回退到 items.json —— 旧流程靠这一条拿到显示名。"""
    raw = {"110103": {"stage": "7-26", "level": "Hard"}}
    catalog = build_catalog(raw, source="unit-test", names={"110103": "啮咬盒"})

    entry = warehouse_materials(catalog)["110103"]
    assert (entry.name, entry.stage.code, entry.level) == ("啮咬盒", "7-26", "Hard")


def test_shipped_catalog_has_resolvable_names() -> None:
    """回归：随仓库发布的目录里，仓库材料的名称/关卡必须都解析得出来。

    目录里的 24 条仓库材料已经不写 `name`（单一来源是 items.json）。旧「均衡取最少」流程
    若绕过 `load_catalog()` 直接读原始 JSON，就会在第一次取 `name` 时 KeyError ——
    而它是「库存保持」总开关关闭时的默认路径，没开新功能的用户全都会中招。
    """
    materials = warehouse_materials(load_catalog())

    assert materials, "随仓库发布的目录里不应没有仓库材料"
    for item_id, entry in materials.items():
        assert entry.name, f"{item_id} 没有可解析的显示名"
        assert entry.stage.code and entry.level, f"{item_id} 缺关卡信息"
    # 货币（source=character）走角色升级页，不在仓库页，旧流程必须排除掉
    assert "203" not in materials
    assert "205" not in materials


def test_count_roi_is_middle_half_anchored_to_icon_bottom() -> None:
    """回归：数量 ROI 取图标中部一半、贴图标底边 30px 高。

    整宽 ROI（87x79 图标 → 71x36）会把单字符「1」稀释成小目标，OCR 置信度掉到 MaaFW
    默认阈值 0.3 以下被过滤，数量读到空串（110403 祝圣秘银，实测 0.228）。
    """
    context = _FakeContext((1101, 213, 87, 79), "1")

    found, count = _analyze()._recognize_item(context, None, "110403")

    assert (found, count) == (True, 1)
    assert context.count_rois == [[1122, 292, 44, 30]]


def test_recognize_item_keeps_icon_found_when_count_unreadable() -> None:
    """图标找到但数量 OCR 被阈值过滤：返回 (True, None)，不能按 0 计入候选。"""
    context = _FakeContext((613, 378, 59, 83), "")

    assert _analyze()._recognize_item(context, None, "110103") == (True, None)


def test_recognize_item_parses_longest_digit_group() -> None:
    """数量文本取最长数字组，忽略千分位与噪声字符。"""
    context = _FakeContext((613, 378, 59, 83), "1,234 噪声 5")

    assert _analyze()._recognize_item(context, None, "110103") == (True, 1234)


def test_recognize_item_skips_count_clipped_by_screen_bottom() -> None:
    """数量条超出屏幕底部时不读（不调用 OCR），等滚动后再读，避免半截数字。"""
    context = _FakeContext((1101, 660, 87, 79), "1")

    assert _analyze()._recognize_item(context, None, "110403") == (False, None)
    assert context.count_rois == []


def test_recognize_item_returns_not_found_when_icon_missing() -> None:
    """图标未匹配到：返回 (False, None) 且不做数量识别。"""
    context = _FakeContext(None, "1")

    assert _analyze()._recognize_item(context, None, "110403") == (False, None)
    assert context.count_rois == []


class _FakeController:
    """`post_screencap` / `post_swipe` 都返回自身，`wait().get()` 给个占位图。"""

    def post_screencap(self) -> "_FakeController":
        return self

    def post_swipe(self, *_args: object) -> "_FakeController":
        return self

    def wait(self) -> "_FakeController":
        return self

    def get(self) -> object:
        return object()


class _AnalyzeContext:
    """驱动 `BalancedFarmingAnalyze.run` 的最小桩：图标全命中、数量都读成 5。"""

    def __init__(self) -> None:
        self.tasker = SimpleNamespace(controller=_FakeController())
        self.pipeline_overrides: list[dict] = []

    def run_recognition(self, name: str, image: object, override: dict) -> RecognitionDetail:
        if name == "BF_ItemIcon":
            return _icon_detail((100, 200, 87, 79))
        roi = override[name]["recognition"]["param"]["roi"]
        return _count_detail("5", roi)

    def override_pipeline(self, pipeline: dict) -> None:
        self.pipeline_overrides.append(pipeline)


def test_analyze_reads_shipped_catalog_without_name_field() -> None:
    """回归：旧「均衡取最少」流程直接吃随仓库发布的目录。

    目录里的仓库材料已经不再写 `name`（单一来源是 items.json）。旧实现用 `json.load` 读原始
    JSON 后直接取 `materials[item_id]["name"]`，会在这里 KeyError —— 而它是「库存保持」总开关
    关闭时的默认路径，未开启新功能的用户全都会中招。
    """
    context = _AnalyzeContext()

    result = _analyze().run(context, None)  # pyright: ignore[reportArgumentType]

    assert result.success
    override = context.pipeline_overrides[-1]["SelectCombatStage"]
    # 所有材料读数相同 → 取 id 最小的一种（110103 啮咬盒，7-26 Hard）
    assert override["action"]["param"]["custom_action_param"]["stage"] == "7-26"
    assert override["attach"]["level"] == "Hard"
