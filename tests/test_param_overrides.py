import pytest

from agent.utils.params import ParamOverrideMixin, coerce_like


class _Demo(ParamOverrideMixin):
    OVERRIDABLE = frozenset({"SAT_MIN", "READ_RATIO", "SIG_ROI", "CLICK_BOX", "NAME"})

    SAT_MIN = 100
    READ_RATIO = 0.5
    SIG_ROI = (200, 150, 880, 330)
    CLICK_BOX = [760, 318, 114, 49]
    NAME = "default"
    NOT_LISTED = 7


class TestCoerceLike:
    def test_int(self):
        assert coerce_like(90, 100, "k") == 90
        assert isinstance(coerce_like(90.0, 100, "k"), int)

    def test_float(self):
        assert coerce_like(0.7, 0.5, "k") == pytest.approx(0.7)
        assert isinstance(coerce_like(1, 0.5, "k"), float)

    def test_bool_rejects_int(self):
        with pytest.raises(ValueError):
            coerce_like(1, True, "k")
        assert coerce_like(False, True, "k") is False

    def test_int_rejects_bool(self):
        with pytest.raises(ValueError):
            coerce_like(True, 100, "k")

    def test_str(self):
        assert coerce_like("x", "default", "k") == "x"
        with pytest.raises(ValueError):
            coerce_like(1, "default", "k")

    def test_tuple_from_list(self):
        result = coerce_like([1, 2, 3, 4], (0, 0, 0, 0), "k")
        assert result == (1, 2, 3, 4)
        assert isinstance(result, tuple)

    def test_list_default_returns_list(self):
        result = coerce_like([1, 2, 3, 4], [0, 0, 0, 0], "k")
        assert result == [1, 2, 3, 4]
        assert isinstance(result, list)

    def test_roi_length_mismatch(self):
        with pytest.raises(ValueError):
            coerce_like([1, 2, 3], (0, 0, 0, 0), "k")

    def test_array_element_type(self):
        with pytest.raises(ValueError):
            coerce_like([1, 2, "a", 4], (0, 0, 0, 0), "k")

    def test_array_rejects_scalar(self):
        with pytest.raises(ValueError):
            coerce_like(5, (0, 0, 0, 0), "k")


class TestParamOverrideMixin:
    def test_empty_params_keeps_defaults(self):
        d = _Demo()
        d.apply_param_overrides({})
        assert d.SAT_MIN == 100
        assert d.READ_RATIO == 0.5
        assert d.SIG_ROI == (200, 150, 880, 330)

    def test_override_applies(self):
        d = _Demo()
        d.apply_param_overrides(
            {"sat_min": 80, "read_ratio": 0.7, "sig_roi": [0, 0, 10, 10]}
        )
        assert d.SAT_MIN == 80
        assert d.READ_RATIO == pytest.approx(0.7)
        assert d.SIG_ROI == (0, 0, 10, 10)
        # 类默认值不受影响
        assert _Demo.SAT_MIN == 100

    def test_previous_override_cleared(self):
        d = _Demo()
        d.apply_param_overrides({"sat_min": 80})
        assert d.SAT_MIN == 80
        d.apply_param_overrides({})
        assert d.SAT_MIN == 100

    def test_unknown_key_ignored(self):
        d = _Demo()
        d.apply_param_overrides({"not_listed": 99, "nonexistent": 1})
        assert d.NOT_LISTED == 7

    def test_query_key_skipped(self):
        d = _Demo()
        d.apply_param_overrides({"query": "stage"})
        assert not hasattr(type(d), "QUERY")

    def test_invalid_value_falls_back(self):
        d = _Demo()
        d.apply_param_overrides({"sat_min": "not-a-number"})
        assert d.SAT_MIN == 100

    def test_list_default_override(self):
        d = _Demo()
        d.apply_param_overrides({"click_box": [1, 2, 3, 4]})
        assert d.CLICK_BOX == [1, 2, 3, 4]
        assert isinstance(d.CLICK_BOX, list)

    def test_str_override(self):
        d = _Demo()
        d.apply_param_overrides({"name": "other"})
        assert d.NAME == "other"
