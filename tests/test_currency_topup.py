"""微尘 / 利齿子儿补足任务的离线测试（独立资源任务）。

## 覆盖的需求点（§3 / §8）

- 两个货币各自的开关与 GUI 阈值继续有效，**默认关闭**；
- 关闭不刷；**等于或高于**阈值不刷；**低于**阈值才触发；
- 只用**本轮有效读数**，不拿缺失项的旧快照决定刷取；
- 触发后选原资源关卡、沿原常规作战刷完体力后正常结束
  （**不回头重查阈值、不重复进零体力作战**）；
- 两个币都缺时用一个**简单确定的规则**选本次刷哪种；
- 均衡任务停用**只影响均衡任务**，不影响本任务。

不启动游戏、不截图、不发键鼠 / ADB 操作 —— 全部用内存桩。
"""

from __future__ import annotations

import json
import types
from typing import Any

import pytest
from maa.custom_action import CustomAction

from agent.custom.action import currency_topup
from agent.custom.action.currency_topup import (
    COIN_ITEM_ID,
    COIN_STAGE,
    DUST_ITEM_ID,
    DUST_STAGE,
    CurrencyTopUpDone,
    CurrencyTopUpInit,
    CurrencyTopUpPlan,
    _int_param,
    should_farm_currency,
)

_FAKE_ARGV = CustomAction.RunArg(None, "", "", "", None, None)  # pyright: ignore[reportArgumentType]


def _argv(param: str) -> CustomAction.RunArg:
    return CustomAction.RunArg(None, "", "", param, None, None)  # pyright: ignore[reportArgumentType]


class _FakeController:
    def post_screencap(self) -> Any:
        return types.SimpleNamespace(wait=lambda: types.SimpleNamespace(get=lambda: "IMG"))


class _FakeContext:
    """最小 context 桩：记录 attach、override_next / override_pipeline 与 run_task。"""

    def __init__(self, attach: dict[str, Any] | None = None) -> None:
        self.attach = attach or {}
        self.next_overrides: list[tuple[str, list[str]]] = []
        self.pipeline_overrides: list[dict[str, Any]] = []
        self.run_tasks: list[str] = []
        self.tasker = types.SimpleNamespace(controller=_FakeController())

    def get_node_object(self, name: str) -> Any:
        return types.SimpleNamespace(attach=self.attach)

    def override_next(self, node_name: str, next_list: list[str]) -> None:
        self.next_overrides.append((node_name, next_list))

    def override_pipeline(self, pipeline: dict[str, Any]) -> None:
        self.pipeline_overrides.append(pipeline)

    def run_task(self, entry: str, *args: Any, **kwargs: Any) -> Any:
        self.run_tasks.append(entry)
        return types.SimpleNamespace(status=types.SimpleNamespace(failed=False))


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    currency_topup.reset_currency_state()
    # 规划节点读不到快照（默认）→ 「本轮没读到」
    monkeypatch.setattr(currency_topup, "_read_currency_counts", lambda: {})
    # 这两个函数由规划节点在函数内 import，patch 到定义它们的模块上
    from agent.custom.action import depot_maintain

    monkeypatch.setattr(depot_maintain, "set_required_currency", lambda _ids: None)
    monkeypatch.setattr(depot_maintain, "ensure_account_id", lambda _ctx: True)


# ------------------------------------------------------------------ 阈值规则
def test_should_farm_only_below_threshold() -> None:
    """低于阈值才刷；相等或高于都不刷。"""
    assert should_farm_currency(DUST_ITEM_ID, 100, 200, True) is True
    assert should_farm_currency(DUST_ITEM_ID, 200, 200, True) is False, "等于阈值不刷"
    assert should_farm_currency(DUST_ITEM_ID, 300, 200, True) is False, "高于阈值不刷"


def test_should_farm_respects_switch() -> None:
    """开关关掉 → 不刷。"""
    assert should_farm_currency(DUST_ITEM_ID, 10, 200, False) is False


def test_should_farm_needs_reading() -> None:
    """没读到数量 → 不刷（缺读数不等于该刷）。"""
    assert should_farm_currency(DUST_ITEM_ID, None, 200, True) is False


def test_int_param_supports_k_and_m() -> None:
    """阈值输入支持 K / M 缩写；空输入用默认值，非法输入返回 None。"""
    assert _int_param("500K", 0) == 500_000
    assert _int_param("1.5M", 0) == 1_500_000
    assert _int_param("1352100", 0) == 1_352_100
    assert _int_param("", 42) == 42, "空输入 = 用户没填 → 用默认值"


def test_int_param_rejects_unparsable_instead_of_defaulting() -> None:
    """非法阈值返回 `None`，**不回落到默认值**。

    回归防护：默认阈值是 135 万，若输入 `K` 之类解析失败后静默用默认值，
    任务会把当天体力一次刷光。
    """
    assert _int_param("abc", 42) is None, "非法输入必须拒绝，不能回落默认值"
    assert _int_param("K", 42) is None, "只有单位没有数字也要拒绝"
    assert _int_param("0", 42) is None, "0 不是有效阈值"


def test_int_param_accepts_numeric_types() -> None:
    """数值类型阈值直接接受，不经过字符串（避免科学计数法）。

    回归防护：手写 pipeline 覆写可能传 `1e16`，先 `str()` 会变成 `1e+16`，
    解析器反而拒绝该货币。数值应直接按整数接受。
    """
    assert _int_param(1_000_000, 42) == 1_000_000, "int 直接接受"
    assert _int_param(1.5e6, 42) == 1_500_000, "float 转 int 后接受"
    assert _int_param(0.5, 42) is None, "小于 1 的数值转 int 后为 0，必须拒绝"
    assert _int_param(-5, 42) is None, "负数必须拒绝"


def test_int_param_rejects_bool() -> None:
    """布尔阈值按无效处理，不回落到默认值。

    回归防护：`True` / `False` 只可能来自 GUI 之外的 pipeline 覆写（把开关值错填到
    阈值字段）。若回落到默认阈值 135 万，任务会按一个用户从未输入过的数字刷光体力。
    """
    assert _int_param(True, 42) is None, "布尔 True 必须拒绝"
    assert _int_param(False, 42) is None, "布尔 False 必须拒绝"
    assert _int_param(None, 42) == 42, "None = 没传 → 用默认值（与布尔区分开）"


# ------------------------------------------------------------------ 入口动作
def test_init_does_not_clobber_gui_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    """入口**不覆写** CT_Plan 的 attach —— GUI 的开关与阈值不能被盖掉。

    入口唯一允许写的 pipeline 是 `ReturnMain.max_hit`（抬命中上限，见下一个用例），
    除此之外不能碰任何节点。
    """
    context = _FakeContext(attach={"dust_enabled": True, "dust_threshold": "500K"})
    result = CurrencyTopUpInit().run(context, _argv(json.dumps({"dust_threshold": 999})))
    assert result.success is True
    written_nodes = {node for pipeline in context.pipeline_overrides for node in pipeline}
    assert written_nodes == {"ReturnMain"}, f"入口只应抬 ReturnMain，实际写了 {written_nodes}"
    # attach 原样保留
    assert context.attach["dust_enabled"] is True
    assert context.attach["dust_threshold"] == "500K"


def test_init_raises_return_main_max_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """入口把 ReturnMain 的 max_hit 抬到 RETURN_MAIN_MAX_HIT。

    回归防护：`startup.json` 里 max_hit 只有 2，而本任务正常流程要回家两次
    （读角色页收尾 + CT_Done 收尾），正好用满没有余量 —— 多一次回家需求就会
    让收尾的 ReturnMain 被静默过滤、任务以失败收场。
    """
    from agent.custom.action.depot_maintain import RETURN_MAIN_MAX_HIT

    context = _FakeContext()
    CurrencyTopUpInit().run(context, _FAKE_ARGV)

    hit = None
    for pipeline in context.pipeline_overrides:
        if "ReturnMain" in pipeline:
            hit = pipeline["ReturnMain"].get("max_hit")
    assert hit == RETURN_MAIN_MAX_HIT, "入口必须抬高 ReturnMain 的命中上限"


def test_plan_reads_thresholds_from_gui_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    """阈值从 GUI 的 attach 读（支持 K/M）。"""
    monkeypatch.setattr(
        currency_topup,
        "_read_currency_counts",
        lambda: {DUST_ITEM_ID: 100, COIN_ITEM_ID: 100},
    )
    context = _FakeContext(
        attach={
            "dust_enabled": True,
            "coin_enabled": True,
            "dust_threshold": "500K",
            "coin_threshold": "1M",
        }
    )
    CurrencyTopUpPlan().run(context, _FAKE_ARGV)
    assert currency_topup.dust_threshold == 500_000
    assert currency_topup.coin_threshold == 1_000_000


# ------------------------------------------------------------------ 触发规则
def _plan(monkeypatch: pytest.MonkeyPatch, counts: dict[str, int], attach: dict[str, Any]) -> _FakeContext:
    monkeypatch.setattr(currency_topup, "_read_currency_counts", lambda: counts)
    context = _FakeContext(attach=attach)
    CurrencyTopUpPlan().run(context, _FAKE_ARGV)
    return context


def test_not_triggered_when_at_or_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """等于阈值 → 不触发，直接收尾。"""
    context = _plan(
        monkeypatch,
        {DUST_ITEM_ID: 1000, COIN_ITEM_ID: 1000},
        {"dust_enabled": True, "coin_enabled": True, "dust_threshold": "1000", "coin_threshold": "1000"},
    )
    assert context.next_overrides[-1][1] == ["CT_Done"]
    assert context.pipeline_overrides == [], "不应覆写选关"


def test_triggered_below_threshold_picks_resource_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """低于阈值 → 选原资源关卡并走原常规作战。"""
    context = _plan(
        monkeypatch,
        {DUST_ITEM_ID: 100, COIN_ITEM_ID: 100},
        {"dust_enabled": True, "coin_enabled": False, "dust_threshold": "1000"},
    )
    assert context.next_overrides[-1][1] == ["Combat"]
    override = context.pipeline_overrides[-1]
    assert override["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == DUST_STAGE
    assert override["SelectCombatStage"]["attach"]["level"] == "None"


def test_switch_off_means_no_farming(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关掉 → 不刷。"""
    context = _plan(
        monkeypatch,
        {DUST_ITEM_ID: 1, COIN_ITEM_ID: 1},
        {"dust_enabled": False, "coin_enabled": False},
    )
    assert context.next_overrides[-1][1] == ["CT_Done"]
    assert context.pipeline_overrides == []


def test_missing_reading_does_not_use_stale_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """只用本轮有效读数：缺读数的货币不参与判断（不拿旧值决定刷取）。

    桩里 `_read_currency_counts` 只返回**本轮真的读到**的那些（生产代码按
    `read_currency_ids` 过滤），所以这里模拟「微尘读到、利齿子儿没读到」。
    """
    context = _plan(
        monkeypatch,
        {DUST_ITEM_ID: 100},
        {"dust_enabled": True, "coin_enabled": True, "dust_threshold": "1000", "coin_threshold": "10"},
    )
    # 利齿子儿没读到 → 不因它触发；微尘低于阈值 → 刷微尘
    assert context.next_overrides[-1][1] == ["Combat"]
    override = context.pipeline_overrides[-1]
    assert override["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == DUST_STAGE


def test_both_missing_means_no_farming(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个都没读到 → 不刷（缺读数 ≠ 关卡不可用，也不触发刷取）。"""
    context = _plan(
        monkeypatch,
        {},
        {"dust_enabled": True, "coin_enabled": True, "dust_threshold": "1000"},
    )
    assert context.next_overrides[-1][1] == ["CT_Done"]
    assert context.pipeline_overrides == []


def test_both_below_threshold_picks_dust_deterministically(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个都缺 → 用一个简单确定的规则（先刷微尘）。"""
    context = _plan(
        monkeypatch,
        {DUST_ITEM_ID: 100, COIN_ITEM_ID: 100},
        {"dust_enabled": True, "coin_enabled": True, "dust_threshold": "1000", "coin_threshold": "1000"},
    )
    assert context.next_overrides[-1][1] == ["Combat"]
    override = context.pipeline_overrides[-1]
    assert override["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == DUST_STAGE


def test_coin_only_below_threshold_picks_coin_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """只有利齿子儿低于阈值 → 刷铸币美学。"""
    context = _plan(
        monkeypatch,
        {DUST_ITEM_ID: 5000, COIN_ITEM_ID: 100},
        {"dust_enabled": True, "coin_enabled": True, "dust_threshold": "1000", "coin_threshold": "1000"},
    )
    assert context.next_overrides[-1][1] == ["Combat"]
    override = context.pipeline_overrides[-1]
    assert override["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == COIN_STAGE


# ------------------------------------------------------------------ 收尾
def test_target_count_finish_goes_to_done_not_back_to_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """刷完体力后**正常结束**：不回到 CT_Plan 重查阈值（否则反复进零体力作战）。"""
    _plan(
        monkeypatch,
        {DUST_ITEM_ID: 100},
        {"dust_enabled": True, "coin_enabled": False, "dust_threshold": "1000"},
    )
    override = context_override_target_count_finish()
    assert override == ["CT_Done"], "刷完体力应直接收尾，不重查阈值"


def context_override_target_count_finish() -> list[str]:
    """从 currency_topup 的模块状态里取上一次覆写的 TargetCountFinish.next。

    `_plan` 内部建的 context 不外露，所以这里改用模块级记录：
    `CurrencyTopUpPlan` 覆写时把 next 存进 `_state`（见实现）。
    """
    return list(currency_topup._state.target_count_finish_next)  # type: ignore[attr-defined]


def test_done_returns_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """收尾回到主界面。"""
    context = _FakeContext()
    result = CurrencyTopUpDone().run(context, _FAKE_ARGV)
    assert result.success is True
    assert "ResetReturnMain" in context.run_tasks
