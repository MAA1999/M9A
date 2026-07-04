from agent.utils import aspect_ratio


def test_accepts_exact_16x9_resolutions_in_both_orientations() -> None:
    assert aspect_ratio.is_aspect_ratio_16x9(1600, 900)
    assert aspect_ratio.is_aspect_ratio_16x9(900, 1600)


def test_rejects_1600x910_in_both_orientations() -> None:
    assert not aspect_ratio.is_aspect_ratio_16x9(1600, 910)
    assert not aspect_ratio.is_aspect_ratio_16x9(910, 1600)


def test_accepts_common_rounded_16x9_resolution() -> None:
    assert aspect_ratio.is_aspect_ratio_16x9(1366, 768)


def test_rejects_invalid_sizes() -> None:
    assert not aspect_ratio.is_aspect_ratio_16x9(0, 720)
    assert not aspect_ratio.is_aspect_ratio_16x9(1280, 0)
    assert not aspect_ratio.is_aspect_ratio_16x9(-1280, 720)


def test_calculate_aspect_ratio_uses_larger_side_first() -> None:
    assert aspect_ratio.calculate_aspect_ratio(
        1600, 900
    ) == aspect_ratio.calculate_aspect_ratio(900, 1600)


def test_calculate_aspect_ratio_distinguishes_1600x910_from_16x9() -> None:
    assert aspect_ratio.calculate_aspect_ratio(1600, 910) != aspect_ratio.TARGET_RATIO
