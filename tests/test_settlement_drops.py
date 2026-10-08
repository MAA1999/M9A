import types

import numpy as np
import pytest
from maa.define import BoxAndScoreResult, OCRResult, RecognitionDetail, Rect

from agent.utils import settlement_drops
from agent.utils.settlement_drops import (
    MAX_SWIPES,
    count_roi,
    filter_digit_colors,
    read_battle_drops,
    read_frame_count,
)

_ICON_BOX = (1131, 555, 83, 56)
_EMPTY_IMG = np.zeros((720, 1280, 3), dtype=np.uint8)


def _icon_detail(box: tuple[int, int, int, int] | None) -> RecognitionDetail:
    rect = Rect(*box) if box is not None else None
    return RecognitionDetail(
        reco_id=1,
        name="DropRegionRec",
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


def _text_detail(text: str, roi: list[int]) -> RecognitionDetail:
    rect = Rect(*roi)
    return RecognitionDetail(
        reco_id=2,
        name="DropCountRec",
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


class _FakeController:
    """最小 controller 桩：记录滑动与截图次数。"""

    def __init__(self) -> None:
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self.screencaps = 0

    def post_screencap(self) -> "_FakeController":
        self.screencaps += 1
        return self

    def wait(self) -> "_FakeController":
        return self

    def get(self) -> np.ndarray:
        return _EMPTY_IMG

    def post_swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> "_FakeController":
        self.swipes.append((x1, y1, x2, y2, duration))
        return self


class _FakeContext:
    """按「每屏一帧」的脚本返回图标匹配与数量 OCR；记录数量 ROI。"""

    def __init__(self, frames: list[tuple[tuple[int, int, int, int] | None, str]]) -> None:
        self.controller = _FakeController()
        self.tasker = types.SimpleNamespace(controller=self.controller)
        self._frames = frames
        self.count_rois: list[list[int]] = []

    def _current_frame(self) -> tuple[tuple[int, int, int, int] | None, str]:
        index = min(max(self.controller.screencaps - 1, 0), len(self._frames) - 1)
        return self._frames[index]

    def run_recognition(self, name: str, image: object, override: dict) -> RecognitionDetail | None:
        icon_box, text = self._current_frame()
        if name == settlement_drops.DROP_REGION_NODE:
            return _icon_detail(icon_box)
        roi = override[name]["recognition"]["param"]["roi"]
        self.count_rois.append(roi)
        return _text_detail(text, roi)


@pytest.fixture(autouse=True)
def _no_settle_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settlement_drops, "SWIPE_SETTLE_SECONDS", 0)


def test_filter_digit_colors_keeps_gray_digits_only() -> None:
    """只留近灰白（数字）像素：彩色、过暗、过亮一律抹白。"""
    img = np.array([[[200, 200, 200], [200, 100, 50], [20, 20, 20], [250, 250, 250]]], dtype=np.uint8)
    result = filter_digit_colors(img)
    assert result[0, 0, 0] == 0  # 中灰 → 保留为黑
    assert result[0, 1, 0] == 255  # 彩色 → 抹白
    assert result[0, 2, 0] == 255  # 过暗 → 抹白
    assert result[0, 3, 0] == 255  # 过亮 → 抹白


def test_count_roi_matches_drop_core_constants() -> None:
    """数量区域与 drop_core 相同：box.x+22, y=613, box.w-44, 高 17。"""
    assert count_roi(list(_ICON_BOX)) == [1153, 613, 39, 17]


def test_count_roi_clamps_when_icon_is_too_narrow() -> None:
    """图标比数字区偏移还窄时宽度夹到 0，不把负宽度 roi 交给 OCR。"""
    assert count_roi([100, 555, 40, 56]) == [122, 613, 0, 17]
    assert count_roi([100, 555, 44, 56]) == [122, 613, 0, 17]
    assert count_roi([100, 555, 45, 56]) == [122, 613, 1, 17]


def test_read_frame_count_parses_digits() -> None:
    context = _FakeContext([(_ICON_BOX, "x300")])
    assert read_frame_count(context, _EMPTY_IMG, "203") == 300  # pyright: ignore[reportArgumentType]
    assert context.count_rois == [[1153, 613, 39, 17]]


def test_read_frame_count_none_without_icon() -> None:
    """图标未命中时不读数量，按未掉落处理。"""
    context = _FakeContext([(None, "300")])
    assert read_frame_count(context, _EMPTY_IMG, "203") is None  # pyright: ignore[reportArgumentType]
    assert context.count_rois == []


def test_read_frame_count_none_when_ocr_has_no_digits() -> None:
    context = _FakeContext([(_ICON_BOX, "")])
    assert read_frame_count(context, _EMPTY_IMG, "203") is None  # pyright: ignore[reportArgumentType]


def test_read_battle_drops_swipes_until_match() -> None:
    """首屏未命中时横向滑动重试，命中即返回。"""
    context = _FakeContext([(None, ""), (_ICON_BOX, "2")])
    assert read_battle_drops(context, "203") == 2  # pyright: ignore[reportArgumentType]
    assert len(context.controller.swipes) == 1
    assert context.controller.swipes[0][0] == settlement_drops.SWIPE_FROM[0]


def test_read_battle_drops_none_after_max_swipes() -> None:
    """滑满次数仍未命中返回 None。"""
    context = _FakeContext([(None, "")])
    assert read_battle_drops(context, "203") is None  # pyright: ignore[reportArgumentType]
    assert len(context.controller.swipes) == MAX_SWIPES
