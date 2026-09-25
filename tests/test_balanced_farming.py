import numpy as np
from maa.define import BoxAndScoreResult, OCRResult, RecognitionDetail, Rect

from agent.custom.action.balanced_farming import BalancedFarmingAnalyze


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
