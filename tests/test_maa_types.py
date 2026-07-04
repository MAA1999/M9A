import numpy as np
import pytest
from maa.define import (
    BoxAndCountResult,
    BoxAndScoreResult,
    CustomRecognitionResult,
    OCRResult,
    RecognitionDetail,
    RecognitionResult,
    Rect,
)

from agent.utils.maa_types import (
    all_results_as,
    best_box,
    best_result_as,
    boxed_results,
    has_box_result,
    is_hit,
    ocr_result,
    ocr_results,
    ocr_text,
    recognition_results,
    require_hit,
    require_ocr_result,
    results_as,
)


def _detail(
    *,
    hit: bool,
    box: Rect | None,
    all_results: list[RecognitionResult] | None = None,
    filtered_results: list[RecognitionResult] | None = None,
    best_result: RecognitionResult | None = None,
) -> RecognitionDetail:
    return RecognitionDetail(
        reco_id=1,
        name="TestRecognition",
        algorithm="Test",
        hit=hit,
        box=box,
        all_results=all_results or [],
        filtered_results=filtered_results or [],
        best_result=best_result,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


def test_is_hit_requires_detail_hit_and_box() -> None:
    rect = Rect(1, 2, 3, 4)
    hit_detail = _detail(hit=True, box=rect)

    assert not is_hit(None)
    assert not is_hit(_detail(hit=False, box=rect))
    assert not is_hit(_detail(hit=True, box=None))
    assert is_hit(hit_detail)
    assert require_hit(hit_detail) is hit_detail

    with pytest.raises(ValueError, match="recognition detail is not hit"):
        require_hit(None)


def test_typed_result_helpers_filter_best_filtered_and_all_results() -> None:
    rect = Rect(10, 20, 30, 40)
    ocr = OCRResult(rect, 0.9, "text")
    score = BoxAndScoreResult(rect, 0.8)
    count = BoxAndCountResult(rect, 3)
    miss = _detail(
        hit=False,
        box=rect,
        all_results=[ocr, score, count],
        filtered_results=[ocr, score],
        best_result=ocr,
    )
    detail = _detail(
        hit=True,
        box=rect,
        all_results=[ocr, score, count],
        filtered_results=[ocr, score],
        best_result=ocr,
    )

    assert best_result_as(None, OCRResult) is None
    assert best_result_as(miss, OCRResult) is None
    assert best_result_as(detail, OCRResult) is ocr
    assert best_result_as(detail, BoxAndScoreResult) is ocr
    assert results_as(detail, OCRResult) == [ocr]
    assert results_as(detail, BoxAndScoreResult) == [ocr, score]
    assert results_as(miss, OCRResult) == []
    assert all_results_as(detail, BoxAndCountResult) == [count]
    assert all_results_as(None, OCRResult) == []


def test_ocr_helpers_return_text_and_results() -> None:
    rect = Rect(1, 1, 2, 2)
    first = OCRResult(rect, 0.9, "alpha")
    second = OCRResult(rect, 0.8, "")
    detail = _detail(
        hit=True,
        box=rect,
        all_results=[first, second],
        filtered_results=[first],
        best_result=first,
    )

    assert ocr_result(detail) is first
    assert require_ocr_result(detail) is first
    assert ocr_text(detail) == "alpha"
    assert ocr_text(None, default="fallback") == "fallback"
    assert ocr_results(detail) == [first, second]

    no_ocr = _detail(hit=True, box=rect, best_result=BoxAndScoreResult(rect, 0.7))
    assert ocr_result(no_ocr) is None
    assert ocr_text(no_ocr) == ""
    with pytest.raises(ValueError, match="does not contain an OCR result"):
        require_ocr_result(no_ocr)


def test_recognition_and_boxed_helpers_filter_non_hits_and_boxed_result_types() -> None:
    rect = Rect(4, 5, 6, 7)
    ocr = OCRResult(rect, 0.9, "text")
    score = BoxAndScoreResult(rect, 0.8)
    count = BoxAndCountResult(rect, 2)
    custom = CustomRecognitionResult(rect, {"kind": "custom"})
    detail = _detail(
        hit=True,
        box=rect,
        all_results=[ocr, score, count, custom],
        filtered_results=[ocr, score, count, custom],
        best_result=score,
    )
    miss = _detail(
        hit=False,
        box=rect,
        filtered_results=[score],
        best_result=score,
    )

    assert recognition_results(None) == []
    assert recognition_results(miss) == []
    assert recognition_results(detail) == [ocr, score, count, custom]
    assert not has_box_result(None)
    assert has_box_result(ocr)
    assert has_box_result(score)
    assert has_box_result(count)
    assert has_box_result(custom)
    assert boxed_results(detail) == [ocr, score, count, custom]
    assert boxed_results(miss) == []
    assert best_box(detail) == rect
    assert best_box(miss) is None
    assert best_box(_detail(hit=True, box=rect, best_result=ocr)) == rect
