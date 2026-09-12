from agent.custom.action.wilderness import GoodDreamWellFishing

parse_remaining_hours = GoodDreamWellFishing._parse_remaining_hours


def test_parse_remaining_hours_hours_only() -> None:
    assert parse_remaining_hours("7小时") == 7


def test_parse_remaining_hours_hours_and_minutes_floors_to_hours() -> None:
    assert parse_remaining_hours("7小时30分钟") == 7
    assert parse_remaining_hours("7小时30分") == 7


def test_parse_remaining_hours_minutes_only_counts_as_zero() -> None:
    assert parse_remaining_hours("30分钟") == 0
    assert parse_remaining_hours("30分") == 0
    assert parse_remaining_hours("45秒") == 0


def test_parse_remaining_hours_bare_digits_keep_legacy_behaviour() -> None:
    assert parse_remaining_hours("7") == 7


def test_parse_remaining_hours_unparsable_text_counts_as_zero() -> None:
    assert parse_remaining_hours("") == 0
    assert parse_remaining_hours("距好梦井馈赠更新") == 0


def test_parse_remaining_hours_extracts_digits_from_partial_text() -> None:
    assert parse_remaining_hours("距好梦井馈赠更新16小时") == 16
