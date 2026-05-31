from typing import TypeGuard

from maa.define import (
    BoxAndCountResult,
    BoxAndScoreResult,
    CustomRecognitionResult,
    OCRResult,
    RecognitionDetail,
    RecognitionResult,
    Rect,
)


class HitRecognitionDetail(RecognitionDetail):
    """Recognition detail known to be a hit with a concrete box."""

    box: Rect


def is_hit(detail: RecognitionDetail | None) -> TypeGuard[HitRecognitionDetail]:
    """Check whether a recognition detail has a hit and a box.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        True when the detail exists, is a hit, and contains a non-null box.
    """
    return detail is not None and detail.hit and detail.box is not None


def require_hit(detail: RecognitionDetail | None) -> HitRecognitionDetail:
    """Return a hit recognition detail or fail fast.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        The recognition detail narrowed to a hit detail with a concrete box.

    Raises:
        ValueError: If the detail is absent, missed, or has no box.
    """
    if not is_hit(detail):
        raise ValueError("recognition detail is not hit")
    return detail


def best_result_as[ResultT](
    detail: RecognitionDetail | None,
    result_type: type[ResultT],
) -> ResultT | None:
    """Return the best result when it matches the requested type.

    Args:
        detail: Recognition detail returned by MaaFramework.
        result_type: Expected result class.

    Returns:
        The best result narrowed to ``result_type``, or None when there is no
        hit, no best result, or the best result has a different type.
    """
    if detail is None or not detail.hit or detail.best_result is None:
        return None

    result = detail.best_result
    if isinstance(result, result_type):
        return result
    return None


def results_as[ResultT](
    detail: RecognitionDetail | None,
    result_type: type[ResultT],
) -> list[ResultT]:
    """Return filtered recognition results matching the requested type.

    Args:
        detail: Recognition detail returned by MaaFramework.
        result_type: Expected result class.

    Returns:
        Results from ``filtered_results`` narrowed to ``result_type``. Returns
        an empty list when the detail is absent or missed.
    """
    if detail is None or not detail.hit:
        return []
    return [
        result
        for result in detail.filtered_results
        if isinstance(result, result_type)
    ]


def all_results_as[ResultT](
    detail: RecognitionDetail | None,
    result_type: type[ResultT],
) -> list[ResultT]:
    """Return all recognition results matching the requested type.

    Args:
        detail: Recognition detail returned by MaaFramework.
        result_type: Expected result class.

    Returns:
        Results from ``all_results`` narrowed to ``result_type``. Returns an
        empty list when the detail is absent or missed.
    """
    if detail is None or not detail.hit:
        return []
    return [
        result
        for result in detail.all_results
        if isinstance(result, result_type)
    ]


def ocr_result(detail: RecognitionDetail | None) -> OCRResult | None:
    """Return the best OCR result from a recognition detail.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        The best OCR result, or None when it is unavailable.
    """
    return best_result_as(detail, OCRResult)


def require_ocr_result(detail: RecognitionDetail | None) -> OCRResult:
    """Return the best OCR result or fail fast.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        The best OCR result.

    Raises:
        ValueError: If the detail does not contain an OCR result.
    """
    result = ocr_result(detail)
    if result is None:
        raise ValueError("recognition detail does not contain an OCR result")
    return result


def ocr_text(detail: RecognitionDetail | None, default: str = "") -> str:
    """Return OCR text from the best result.

    Args:
        detail: Recognition detail returned by MaaFramework.
        default: Text returned when no OCR result is available.

    Returns:
        OCR text from the best result, or ``default``.
    """
    result = ocr_result(detail)
    return result.text if result is not None else default


def ocr_results(detail: RecognitionDetail | None) -> list[OCRResult]:
    """Return all OCR results from a recognition detail.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        OCR results from ``all_results``. Returns an empty list when the detail
        is absent or missed.
    """
    return all_results_as(detail, OCRResult)


def recognition_results(detail: RecognitionDetail | None) -> list[RecognitionResult]:
    """Return filtered recognition results for a hit detail.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        ``filtered_results`` when the detail is a hit, otherwise an empty list.
    """
    if detail is None or not detail.hit:
        return []
    return detail.filtered_results


BoxedRecognitionResult = BoxAndScoreResult | BoxAndCountResult | CustomRecognitionResult


def has_box_result(result: RecognitionResult | None) -> TypeGuard[BoxedRecognitionResult]:
    """Check whether a recognition result carries a box.

    Args:
        result: Recognition result returned by MaaFramework.

    Returns:
        True when ``result`` is one of the result types with a concrete box.
    """
    return isinstance(result, BoxAndScoreResult | BoxAndCountResult | CustomRecognitionResult)


def boxed_results(detail: RecognitionDetail | None) -> list[BoxedRecognitionResult]:
    """Return filtered recognition results that carry boxes.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        Box-carrying results from ``filtered_results``. Returns an empty list
        when the detail is absent or missed.
    """
    return [
        result
        for result in recognition_results(detail)
        if has_box_result(result)
    ]


def best_box(detail: RecognitionDetail | None) -> Rect | None:
    """Return the box from the best boxed result.

    Args:
        detail: Recognition detail returned by MaaFramework.

    Returns:
        The best result's box, or None when the detail is absent, missed, or
        the best result does not carry a box.
    """
    if detail is None or not detail.hit:
        return None
    result = detail.best_result
    if not has_box_result(result):
        return None
    return result.box
