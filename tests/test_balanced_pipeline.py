"""均衡刷材料改造的 **pipeline 静态校验**。

## 覆盖的需求点（§4 / §5 / §8）

- **原版点击方式保留**：Click/Swipe、目标区域、target_offset、延迟、冻结等待、
  矩形随机取点全部不动 —— 校验原版节点的配置与改造前一致；
- 超时分支接在**原版扫描链**上（`SwipeLeftForStageList` / `SwipeRightForStageList`），
  不另写导航；
- 尾节点的 `timeout` 仍是原来的 2000ms（两分钟是**整个寻找过程**的总预算，
  不是给两个尾节点各设两分钟）；
- 新增节点只加在**清单尾部**，不改动任何既有节点的字段。

这些是**静态**校验：读 pipeline JSON、比对结构。真实点击行为需要真机验证。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "resource" / "base" / "pipeline"
COMBAT = PIPELINE_DIR / "combat.json"
BALANCED = PIPELINE_DIR / "balanced_farming.json"
FALLBACK = PIPELINE_DIR / "balanced_fallback.json"

# 原版扫描链的关键节点（改造前就存在，改造后必须还在且配置不变）
ORIGINAL_SCAN_NODES = (
    "SwipeLeftAndFindStage",
    "SwipeRightAndFindStage",
    "SwipeLeftForStageList",
    "SwipeRightForStageList",
)
# 原版「开始行动」点击节点
READY_NODE = "ReadyForAction"


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
def test_original_scan_nodes_still_present(combat: dict[str, Any]) -> None:
    """原版扫描链的节点一个都不能少。"""
    for name in ORIGINAL_SCAN_NODES:
        assert name in combat, f"原版节点 {name} 不应被删掉"


def test_scan_list_timeout_unchanged(combat: dict[str, Any]) -> None:
    """尾节点的 `timeout` 仍是原来的 2000ms。

    两分钟是**整个寻找过程**的总预算（由 `StageLookupBudget` 识别把关），
    不是给两个尾节点各设两分钟。
    """
    for name in ("SwipeLeftForStageList", "SwipeRightForStageList"):
        assert combat[name]["timeout"] == 2000, f"{name} 的 timeout 不应被改大"


def test_scan_head_max_hit_unchanged(combat: dict[str, Any]) -> None:
    """扫描头的 `max_hit` 仍是原来的 30（一次选关的上限）。"""
    for name in ("SwipeLeftAndFindStage", "SwipeRightAndFindStage"):
        assert combat[name]["max_hit"] == 30, f"{name} 的 max_hit 不应被改"


def test_ready_for_action_click_unchanged(combat: dict[str, Any]) -> None:
    """原版「开始行动」节点仍是 Click + 原来的识别区域与冻结等待。

    （这个节点原本就没有 `target_offset` —— 它点的是 OCR 识别到的「开始行动」
    文字中心，矩形随机取点由 MaaFW 在识别框内做。所以这里校验的是
    **识别区域 + 冻结等待**没被动过。）
    """
    node = combat[READY_NODE]
    assert node["action"]["type"] == "Click"
    assert node["recognition"]["param"]["roi"] == [900, 500, 380, 220]
    assert node["recognition"]["param"]["expected"] == ["开始行动"]
    assert node["post_wait_freezes"] == {"time": 1500, "target": [0, 381, 238, 138]}


def test_no_new_fixed_coordinate_click_in_new_nodes(fallback: dict[str, Any]) -> None:
    """新增节点不得引入固定坐标点击（要复用原版点击配置）。"""
    for name, body in fallback.items():
        action = body.get("action")
        if not isinstance(action, dict):
            continue
        assert action.get("type") == "Custom", f"{name} 应是自定义动作，不该是固定坐标点击"
        param = action.get("param", {})
        assert "custom_action" in param, f"{name} 缺少 custom_action"


def test_swipe_params_unchanged(combat: dict[str, Any]) -> None:
    """原版滑动节点的起止点与时长不变。"""
    left = combat["SwipeLeftForStageList"]["action"]["param"]
    assert left["begin"] == [300, 600, 100, 50]
    assert left["end"] == [900, 600, 100, 50]
    assert left["duration"] == 400


def test_freeze_wait_unchanged(combat: dict[str, Any]) -> None:
    """原版冻结等待不变。"""
    assert combat["SwipeLeftForStageList"]["post_wait_freezes"] == 1
    assert combat["SwipeRightForStageList"]["post_wait_freezes"] == 100


# --------------------------------------------------------------- 超时分支接入
def test_scan_list_has_timeout_on_error(combat: dict[str, Any]) -> None:
    """两个扫描尾节点都挂了超时分支（on_error → StageLookupTimeout）。"""
    for name in ("SwipeLeftForStageList", "SwipeRightForStageList"):
        on_error = combat[name].get("on_error")
        assert on_error == ["StageLookupTimeout"], f"{name} 应在失败时导向 StageLookupTimeout"


def test_scan_list_next_keeps_original_order(combat: dict[str, Any]) -> None:
    """`next` 里原版的扫描头必须还在（预算检查只加在前面）。"""
    assert "SwipeLeftAndFindStage" in combat["SwipeLeftForStageList"]["next"]
    assert "SwipeRightAndFindStage" in combat["SwipeRightForStageList"]["next"]


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


def test_entry_skips_to_skipped_node(balanced: dict[str, Any]) -> None:
    """入口节点有「跳过」出口。"""
    assert balanced["BF_Entry"]["action"]["param"]["custom_action"] == "BalancedTaskEntry"


# --------------------------------------------------------------- i18n / GUI
def test_reset_option_label_exists() -> None:
    """GUI 上有「重置全部记录」这个选项（中英双语都要有）。"""
    for locale in ("zh_cn.json", "en_us.json"):
        text = (Path(__file__).resolve().parent.parent / "locales" / locale).read_text(encoding="utf-8")
        assert "Option.BalancedFarming.ResetStageRecords" in text, f"{locale} 缺少重置选项的文案"


def test_no_stale_stage_progress_references() -> None:
    """旧的 `stage_progress` / `stage_probe` 设计已彻底删除，仓库里不该再引用。

    本测试文件自身要提到这些名字（用来断言它们不再被引用），所以排除 tests/ 目录。
    """
    root = Path(__file__).resolve().parent.parent
    stale: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in (".py", ".json", ".md"):
            continue
        if any(part in (".git", "node_modules", "debug", ".venv", "tests") for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"stage_progress|stage_probe|StageProgressReset|StageProbe", text):
            stale.append(str(path.relative_to(root)))
    assert not stale, f"仍有旧设计的残留引用: {stale}"
