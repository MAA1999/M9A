"""检查均衡任务新增节点、原版扫描链的接入顺序和入口分支。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "resource" / "base" / "pipeline"
COMBAT = PIPELINE_DIR / "combat.json"
BALANCED = PIPELINE_DIR / "balanced_farming.json"
FALLBACK = PIPELINE_DIR / "balanced_fallback.json"


def _load(path: Path) -> dict[str, Any]:
    """读 pipeline JSON（允许 `//` 注释）。"""
    text = path.read_text(encoding="utf-8")
    stripped = _strip_comments(text)
    return json.loads(stripped)


def _strip_comments(text: str) -> str:
    """去掉 JSONC 的 `//` 行注释（正确跳过字符串字面量里的 `//`）。"""
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


@pytest.fixture(scope="module")
def combat() -> dict[str, Any]:
    return _load(COMBAT)


@pytest.fixture(scope="module")
def balanced() -> dict[str, Any]:
    return _load(BALANCED)


@pytest.fixture(scope="module")
def fallback() -> dict[str, Any]:
    return _load(FALLBACK)


# --------------------------------------------------------------- 原版保留
def test_no_new_fixed_coordinate_click_in_new_nodes(fallback: dict[str, Any]) -> None:
    """新增节点不得引入固定坐标点击（要复用原版点击配置）。"""
    for name, body in fallback.items():
        action = body.get("action")
        if not isinstance(action, dict):
            continue
        assert action.get("type") == "Custom", f"{name} 应是自定义动作，不该是固定坐标点击"
        param = action.get("param", {})
        assert "custom_action" in param, f"{name} 缺少 custom_action"


# --------------------------------------------------------------- 超时分支接入
def test_scan_list_has_no_global_on_error(combat: dict[str, Any]) -> None:
    """两个扫描尾节点**不能**在 `combat.json` 里写死 `on_error`。

    它们是原版共享节点，非均衡任务也用。写死 `on_error: [StageLookupTimeout]`
    会让那些任务找关卡失败时跳过本节点的 `focus` 文案、改在
    `StageLookupTimeout` 上失败 —— 用户看到的原因就变了。

    真实挂载在 `BalancedTaskEntry` 的入口 override 里，由入口行为测试覆盖。
    """
    for name in ("SwipeLeftForStageList", "SwipeRightForStageList"):
        assert "on_error" not in combat[name], f"{name} 是原版共享节点，on_error 只能在均衡任务里 override"
        # 原版的 focus 文案必须还在（失败原因照常显示）
        assert "Node.PipelineNode.Failed" in (combat[name].get("focus") or {})


def test_stage_lookup_timeout_keeps_failure_focus(fallback: dict[str, Any]) -> None:
    """`StageLookupTimeout` 补了与扫描尾节点一致的失败文案。

    均衡任务把扫描尾的失败出口改成指向它；没有 `focus` 的话，用户在 GUI 里
    看不到「未找到目标关卡」这个原因。
    """
    focus = fallback["StageLookupTimeout"].get("focus") or {}
    assert "Node.PipelineNode.Failed" in focus
    assert focus["Node.PipelineNode.Failed"] == "$Focus.Combat.StageNotFound"


def test_scan_list_next_keeps_original_order(combat: dict[str, Any]) -> None:
    """`next` 里原版的扫描头必须还在（预算检查只加在前面）。"""
    assert combat["SwipeLeftForStageList"]["next"] == ["StageLookupBudget", "SwipeLeftAndFindStage"]
    assert combat["SwipeRightForStageList"]["next"] == ["StageLookupBudget", "SwipeRightAndFindStage"]


def test_budget_node_is_recognition_not_action(fallback: dict[str, Any]) -> None:
    """预算检查是**自定义识别**（没 recognition 的动作节点会无条件命中、打断原版调度）。"""
    node = fallback["StageLookupBudget"]
    assert node["recognition"]["type"] == "Custom"
    assert node["recognition"]["param"]["custom_recognition"] == "StageLookupBudget"
    assert "action" not in node, "预算检查不应带动作"
    # 匹配后要能走到超时处理节点
    assert node["next"] == ["StageLookupTimeout"], "预算超限后必须导向顺延处理"


def test_timeout_node_is_action(fallback: dict[str, Any]) -> None:
    """超时处理是自定义动作。"""
    node = fallback["StageLookupTimeout"]
    assert node["action"]["type"] == "Custom"
    assert node["action"]["param"]["custom_action"] == "StageLookupTimeout"


# --------------------------------------------------------------- 入口顺序
def test_entry_order_reset_before_skip(balanced: dict[str, Any]) -> None:
    """入口顺序：先重置 → 再检查停用（保证已停用时仍能执行重置）。"""
    assert balanced["BalancedFarming"]["next"][0] == "BF_ResetRecords"
    assert balanced["BF_ResetRecords"]["next"] == ["BF_Entry"]
    assert balanced["BF_Entry"]["action"]["param"]["custom_action"] == "BalancedTaskEntry"
    assert balanced["BF_ResetRecords"]["action"]["param"]["custom_action"] == "BalancedResetRecords"


def test_skip_node_does_not_navigate(balanced: dict[str, Any]) -> None:
    """被跳过时的收尾节点不导航（不点选关卡）。"""
    node = balanced["BF_Skipped"]
    assert node["action"]["type"] == "Custom"
    assert node["action"]["param"]["custom_action"] == "BalancedTaskSkip"
    assert node.get("next") == [], "跳过后不应再往下走"


# --------------------------------------------------------------- i18n / GUI
def test_reset_option_label_exists() -> None:
    """GUI 上有「重置全部记录」这个选项（中英双语都要有）。"""
    for locale in ("zh_cn.json", "en_us.json"):
        text = (ROOT / "locales" / locale).read_text(encoding="utf-8")
        assert "Option.BalancedFarming.ResetStageRecords" in text, f"{locale} 缺少重置选项的文案"


def test_far_left_node_wired_before_original(combat: dict[str, Any]) -> None:
    """StageLookupFarLeft 接在左向扫描头里，且排在原版判定**之前**。

    排在前面是为了先置位 `reached_far_left` 再让原版节点接管 —— 原版节点命中后
    会回 `SwipeRightForStageList`，两者行为一致，只是多记一个标记。
    """
    nxt = combat["SwipeLeftAndFindStage"]["next"]
    assert "StageLookupFarLeft" in nxt
    assert "TheFarLeftOfStageList" in nxt
    assert nxt.index("StageLookupFarLeft") < nxt.index("TheFarLeftOfStageList")


def test_far_left_node_disabled_by_default(fallback: dict[str, Any]) -> None:
    """两个自定义识别默认 disabled，避免拖累所有作战任务。

    它们都是 Custom 识别，MaaFW 会为它们强制截图并回调 agent；而
    `StageLookupBudget` 被插在两个扫描尾节点的 next 首位、`StageLookupFarLeft`
    插在左向扫描头里，默认启用会让**所有作战任务**每轮都多付这份开销。
    """
    assert fallback["StageLookupBudget"]["enabled"] is False
    assert fallback["StageLookupFarLeft"]["enabled"] is False
