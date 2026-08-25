import pytest

from agent.utils.params import parse_params


def test_parse_params_none_and_empty_return_empty_dict() -> None:
    assert parse_params(None) == {}
    assert parse_params("") == {}


def test_parse_params_json_null_returns_empty_dict() -> None:
    """MaaFW 在节点未写 custom_*_param 时传字面量 "null"，必须视同缺省而非报错。"""
    assert parse_params("null") == {}


def test_parse_params_object() -> None:
    assert parse_params('{"threshold": 0.8}') == {"threshold": 0.8}


def test_parse_params_non_object_raises() -> None:
    with pytest.raises(ValueError, match="参数必须是对象"):
        parse_params("[1, 2]")


def test_parse_params_required_keys() -> None:
    assert parse_params('{"a": 1}', "a") == {"a": 1}
    with pytest.raises(ValueError, match="缺少必填字段"):
        parse_params('{"b": 1}', "a")
    with pytest.raises(ValueError, match="参数为空"):
        parse_params(None, "a")
    with pytest.raises(ValueError, match="参数为空"):
        parse_params("null", "a")


def test_parse_params_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="JSON解析失败"):
        parse_params("{bad")
