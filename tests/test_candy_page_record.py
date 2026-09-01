from types import SimpleNamespace

import numpy as np
import pytest
from maa.define import OCRResult, RecognitionDetail, RecognitionResult, Rect

from agent.custom.reco.combat import AP_OVERFLOW_LIMIT, CandyPageRecord

_MAX_AP = 240
_BIG_CANDY_INDEX = 3


def _recognition_detail(text: str | None = None) -> RecognitionDetail:
    rect = Rect(1, 1, 2, 2)
    best_result: RecognitionResult | None = OCRResult(rect, 0.9, text) if text is not None else None
    return RecognitionDetail(
        reco_id=1,
        name="TestRecognition",
        algorithm="Test",
        hit=True,
        box=rect,
        all_results=[best_result] if best_result is not None else [],
        filtered_results=[best_result] if best_result is not None else [],
        best_result=best_result,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


class _CandyPageContext:
    """Minimal Context stub exposing only what CandyPageRecord.analyze consumes."""

    def __init__(
        self,
        remaining_ap: int,
        counts: list[int],
        periods: list[str],
        attach: dict[str, object],
        max_ap: int = _MAX_AP,
    ) -> None:
        self.remaining_ap = remaining_ap
        self.max_ap = max_ap
        self.counts = counts
        self.periods = periods
        self.attach = attach

    def run_recognition(
        self,
        name: str,
        _image: object,
        pipeline_override: dict[str, dict[str, list[int]]] | None = None,
    ) -> RecognitionDetail | None:
        if name == "EatCandyPage":
            return _recognition_detail()
        if name == "CandyRecognizeRemainingAp":
            return _recognition_detail(str(self.remaining_ap))
        if name == "CandyRecognizeMaxAp":
            return _recognition_detail(str(self.max_ap))
        if name == "EatCandyPageCountRecord" and pipeline_override is not None:
            roi = pipeline_override["EatCandyPageCountRecord"]["roi"]
            return _recognition_detail(str(self.counts[CandyPageRecord.count_rois.index(roi)]))
        if name == "EatCandyPageValidPeriodRecord" and pipeline_override is not None:
            roi = pipeline_override["EatCandyPageValidPeriodRecord"]["roi"]
            return _recognition_detail(self.periods[CandyPageRecord.valid_period_rois.index(roi)])
        return None

    def get_node_object(self, _name: str) -> SimpleNamespace:
        return SimpleNamespace(attach=self.attach)


def _big_candy_only_context(remaining_ap: int, attach: dict[str, object]) -> _CandyPageContext:
    return _CandyPageContext(
        remaining_ap=remaining_ap,
        counts=[0, 0, 0, 13],
        periods=["", "", "", "12天"],
        attach=attach,
    )


def _analyze(context: _CandyPageContext) -> object | None:
    argv = SimpleNamespace(image=np.zeros((1, 1, 3), dtype=np.uint8))
    return CandyPageRecord().analyze(context, argv)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_candy_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CandyPageRecord, "_has_eaten_once", False)
    monkeypatch.setattr(CandyPageRecord, "_last_candy_counts", {})
    monkeypatch.setattr(CandyPageRecord, "_last_remaining_ap", -1)


def test_candy_page_record_eats_candy_that_fits_the_remaining_headroom() -> None:
    context = _big_candy_only_context(1, {"valid_period": "14d", "fast": 1})

    result = _analyze(context)

    assert result is not None
    assert result.box == CandyPageRecord.click_rois[_BIG_CANDY_INDEX]


def test_candy_page_record_skips_overflowing_candy_by_default() -> None:
    # 121/240：大糖恢复 120 > 剩余空间 119，默认不允许溢出时跳过
    context = _big_candy_only_context(121, {"valid_period": "14d", "fast": 1})

    assert _analyze(context) is None


def test_candy_page_record_eats_overflowing_candy_when_overflow_allowed() -> None:
    context = _big_candy_only_context(121, {"valid_period": "14d", "fast": 1, "allow_overflow": 1})

    result = _analyze(context)

    assert result is not None
    assert result.box == CandyPageRecord.click_rois[_BIG_CANDY_INDEX]
    assert result.detail["allow_overflow"] == 1


def test_candy_page_record_keeps_eating_above_the_displayed_cap_when_overflow_allowed() -> None:
    # 361/240：已超过显示上限但远未到隐性上限，允许溢出时应继续吃
    context = _big_candy_only_context(361, {"valid_period": "14d", "fast": 1, "allow_overflow": 1})

    result = _analyze(context)

    assert result is not None
    assert result.box == CandyPageRecord.click_rois[_BIG_CANDY_INDEX]


def test_candy_page_record_stops_at_the_hidden_ap_ceiling() -> None:
    attach: dict[str, object] = {"valid_period": "14d", "fast": 1, "allow_overflow": 1}

    assert _analyze(_big_candy_only_context(AP_OVERFLOW_LIMIT, attach)) is not None
    assert _analyze(_big_candy_only_context(AP_OVERFLOW_LIMIT + 1, attach)) is None


def test_candy_page_record_stops_at_full_stamina_without_overflow_permission() -> None:
    context = _big_candy_only_context(_MAX_AP, {"valid_period": "14d", "fast": 1})

    assert _analyze(context) is None


def test_candy_page_record_stops_overflowing_when_stamina_does_not_grow() -> None:
    # 连续两次识别到同样的体力，说明上一次吃糖没有生效，不应继续空转
    attach: dict[str, object] = {"valid_period": "14d", "fast": 1, "allow_overflow": 1}

    assert _analyze(_big_candy_only_context(121, attach)) is not None
    assert _analyze(_big_candy_only_context(121, attach)) is None


def test_candy_page_record_keeps_overflowing_while_stamina_grows() -> None:
    attach: dict[str, object] = {"valid_period": "14d", "fast": 1, "allow_overflow": 1}

    assert _analyze(_big_candy_only_context(1, attach)) is not None
    assert _analyze(_big_candy_only_context(121, attach)) is not None
    assert CandyPageRecord._last_remaining_ap == 121

    CandyPageRecord.reset_eaten_flag()
    assert CandyPageRecord._last_remaining_ap == -1
