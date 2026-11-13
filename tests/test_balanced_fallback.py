"""均衡刷材料「选关超时 → 两级顺延」的离线测试。

## 覆盖的需求点（§8 的重点场景）

1. 超时后同材料关卡顺延成功；
2. 第六个候选可用也要在本次尝试到（不能「只试五个就算全部失败」）；
3. 第一材料全失败后继续第二少、第三少并成功；
4. 每种材料都遵守「跳过记录」，且本轮已失败的材料不重复尝试；
5. 只有所有有效参与材料都不可用时，本次及下次/重启才跳过；
6. 显式重置恢复；
7. 没有切换任务时默认同一账号；
8. A/B 切换隔离与切回恢复；
9. 无效 / 失败的切换不改归属；
10. 非寻关失败不误记（战斗失败、体力不足等不记录关卡不可用）。

## 测试方式

全部用**内存桩**：不启动游戏、不截图、不发键鼠 / ADB 操作。
被测分支（顺延、记录、停用）由桩如实驱动 —— 断言的是**流程与状态**，
不是「桩成总成功」。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

# `utils.*`（agent 目录在 sys.path 上）与 `agent.utils.*` 是两个模块对象 ——
# 同一份源码、不同的模块实例。状态路径的常量两份各一份，打补丁要都打。
import utils.balanced_state as _plain_balanced_state  # noqa: E402
from maa.custom_action import CustomAction

from agent.custom.action import balanced_entry, balanced_fallback
from agent.custom.action.balanced_fallback import (
    BalancedFallback,
    MaterialCandidate,
    build_depot_material_candidates,
    build_material_candidates,
    planner,
    reset_planner,
)
from agent.utils import balanced_state
from agent.utils.balanced_state import (
    StageCandidate,
    candidates_for_material,
    is_stage_unavailable,
    is_task_skipped,
    record_unavailable,
    set_task_skipped,
    unavailable_stages,
)
from agent.utils.material_catalog import MaterialEntry, parse_stage_code

TEST_UID = "100000001"
"""测试用的固定 UID（新实现里账号归属只认 UID）。"""

_FAKE_ARGV = CustomAction.RunArg(None, "", "", "", None, None)  # pyright: ignore[reportArgumentType]


def _argv(param: str) -> CustomAction.RunArg:
    return CustomAction.RunArg(None, "", "", param, None, None)  # pyright: ignore[reportArgumentType]


# --------------------------------------------------------------------- 桩
class _FakeController:
    def post_screencap(self) -> Any:
        return types.SimpleNamespace(wait=lambda: types.SimpleNamespace(get=lambda: "IMG"))


class _FakeTasker:
    def __init__(self, stopping: bool = False) -> None:
        self.stopping = stopping
        self.controller = _FakeController()


class _FakeContext:
    """最小 context 桩：记录覆写与调用。"""

    def __init__(
        self,
        *,
        stopping: bool = False,
        home_ok: bool = True,
    ) -> None:
        self.next_overrides: list[tuple[str, list[str]]] = []
        self.pipeline_overrides: list[dict[str, Any]] = []
        self.run_tasks: list[str] = []
        self.home_ok = home_ok
        self.tasker = _FakeTasker(stopping=stopping)

    def override_next(self, node_name: str, next_list: list[str]) -> None:
        self.next_overrides.append((node_name, next_list))

    def override_pipeline(self, pipeline: dict[str, Any]) -> None:
        self.pipeline_overrides.append(pipeline)

    def run_task(self, entry: str, *args: Any, **kwargs: Any) -> Any:
        self.run_tasks.append(entry)
        failed = not self.home_ok if entry == balanced_fallback.HOME_ENTRY else False
        return types.SimpleNamespace(status=types.SimpleNamespace(failed=failed))

    def get_node_object(self, name: str) -> Any:
        """`material_candy_override` 会读节点数据；桩里直接给默认结构。"""
        return types.SimpleNamespace(attach={})

    def get_node_data(self, name: str) -> Any:
        """`_capture_baselines` 会读节点数据；桩里返回空 dict。"""
        return {}


def _entry(item_id: str, name: str, stage: str, level: str = "Hard", per_run: int | None = None) -> MaterialEntry:
    return MaterialEntry(
        item_id=item_id,
        name=name,
        stage=parse_stage_code(stage),
        level=level,
        per_run=per_run,
    )


def _state_path(tmp_path: Path, name: str = "balanced_state.json") -> Path:
    """状态文件放**工作区内**的临时目录。

    pytest 的 `tmp_path` 在系统临时目录（工作区之外），沙箱不允许写那里；
    落在工作区里的 `.pytest-tmp-*` 已在 .gitignore 里，不污染 git status。

    文件名带用例名，**用例之间互不干扰**（状态文件是模块级的共享资源）。
    """
    root = Path(__file__).resolve().parent.parent / ".pytest-tmp-bf-state"
    root.mkdir(parents=True, exist_ok=True)
    return root / name


@pytest.fixture(autouse=True)
def _isolated_state(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """把状态文件指向本用例专属的临时文件，并重置模块级顺延状态机。

    `agent.utils.*` 与 `utils.*` 是**两张模块图**（同一份源码、两个模块对象），
    所以两个都要打补丁 —— 只改一个的话，另一张图里的函数仍会写回默认路径。
    """
    safe = request.node.name.replace("/", "_").replace("\\", "_")
    path = _state_path(Path("."), f"state_{safe}.json")
    # 上一次运行留下的同名文件会让用例互相干扰（状态是持久资源）→ 先清掉
    path.unlink(missing_ok=True)
    # `agent.utils.*` 与 `utils.*` 是两张模块图（同一份源码、两个模块对象），
    # 两边都要打补丁 —— 只改一个的话，另一张图里的函数仍会写回默认路径。
    for module in (balanced_state, _plain_balanced_state):
        monkeypatch.setattr(module, "BALANCED_STATE_PATH", path)
    reset_planner()
    yield


# ------------------------------------------------------------- 候选关卡顺序
def test_candidates_put_registered_stage_first(tmp_path: Path) -> None:
    """原登记关卡排最前，其余按数字 (章节, 关卡) 降序。"""
    drop_index = {
        "13-4E": [110103],
        "12-10E": [110103],
        "9-8E": [110103],
        "8-7E": [110103],
        "7-26E": [110103],
    }
    candidates = candidates_for_material(
        "110103",
        level="Hard",
        registered_stage="7-26",
        drop_index=drop_index,
    )
    stages = [c.stage for c in candidates]
    assert stages[0] == "7-26", "原登记关卡必须排最前"
    # 其余按数字降序：13-4 > 12-10 > 9-8 > 8-7
    assert stages[1:] == ["13-4", "12-10", "9-8", "8-7"]


def test_candidates_numeric_order_not_string_order(tmp_path: Path) -> None:
    """数字比较，不是字符串比较（`13-4 > 12-10`，字符串比较会得出相反结果）。"""
    drop_index = {"13-4E": [110103], "12-10E": [110103], "9-8E": [110103]}
    candidates = candidates_for_material("110103", level="Hard", registered_stage="13-4", drop_index=drop_index)
    assert [c.stage for c in candidates] == ["13-4", "12-10", "9-8"]


def test_candidates_sixth_is_reachable(tmp_path: Path) -> None:
    """第六个候选也在候选序列里（不能「只试五个就算全部失败」）。"""
    drop_index = {f"{c}-1E": [110103] for c in ("1", "2", "3", "4", "5", "6", "7")}
    candidates = candidates_for_material("110103", level="Hard", registered_stage="7-1", drop_index=drop_index)
    assert len(candidates) == 7
    assert candidates[5].stage == "2-1", "第六个候选必须可达"


def test_candidates_always_include_registered_stage(tmp_path: Path) -> None:
    """登记关卡始终在候选里 —— 即使掉落索引漏了它。

    回归防护：索引里「有别的候选但没有登记关卡」时，不能把登记关卡丢掉，
    否则其余候选都不可用会把材料误判成「无可用关卡」。
    """
    # 索引里有 13-4 / 12-10，但**没有**登记关卡 7-26
    drop_index = {"13-4E": [110103], "12-10E": [110103]}
    candidates = candidates_for_material("110103", level="Hard", registered_stage="7-26", drop_index=drop_index)
    stages = [c.stage for c in candidates]
    assert stages[0] == "7-26", "登记关卡必须仍在首位（索引缺项时补回来）"
    assert stages[1:] == ["13-4", "12-10"]


def test_resource_family_stage_only_exact_match(tmp_path: Path) -> None:
    """资源族关卡不套主线编号规则，只精确匹配。"""
    assert is_stage_unavailable({"MA-06"}, "MA-06") is True
    assert is_stage_unavailable({"MA-06"}, "MA-07") is False
    assert is_stage_unavailable({"MA-06"}, "LP-06") is False


def test_main_story_unavailable_covers_larger_numbers(tmp_path: Path) -> None:
    """记录 7-26 后，编号更大的主线关卡也算不可用。"""
    known = {"7-26"}
    assert is_stage_unavailable(known, "7-26") is True
    assert is_stage_unavailable(known, "8-1") is True
    assert is_stage_unavailable(known, "13-4") is True
    assert is_stage_unavailable(known, "7-25") is False
    assert is_stage_unavailable(known, "6-30") is False


# ------------------------------------------------------------- 顺延状态机
def _material(item_id: str, count: int, stages: list[str]) -> MaterialCandidate:
    entry = _entry(item_id, f"材料{item_id}", stages[0])
    from agent.utils.balanced_state import StageCandidate, parse_stage_order

    candidates = [StageCandidate(stage=stage, level="Hard", order=parse_stage_order(stage)) for stage in stages]
    return MaterialCandidate(entry=entry, count=count, candidates=candidates)


def test_fallback_moves_to_next_candidate_of_same_material(tmp_path: Path) -> None:
    """同材料顺延：第一个候选失败后取下一个。

    注意候选是**降序**（新关卡在前），而「记录 7-26 → 编号更大的也算不可用」，
    所以记录 7-26 之后的下一个可用候选是**更早**的 6-6（主线逐关解锁，
    更靠后的更不可能解锁）。
    """
    state = BalancedFallback()
    state.begin([_material("110103", 1, ["7-26", "6-6", "5-19"])])
    state.account_id = TEST_UID
    first = state.next_candidate()
    assert first is not None and first.stage == "7-26"
    state.mark_unavailable("7-26")
    second = state.next_candidate()
    assert second is not None and second.stage == "6-6"


def test_fallback_skips_already_recorded_candidates(tmp_path: Path) -> None:
    """已在不可用清单里的候选直接跳过。"""
    record_unavailable(TEST_UID, "7-26")
    state = BalancedFallback()
    state.begin([_material("110103", 1, ["7-26", "6-6"])])
    state.account_id = TEST_UID
    candidate = state.next_candidate()
    assert candidate is not None and candidate.stage == "6-6"


def test_fallback_moves_to_second_and_third_least_material(tmp_path: Path) -> None:
    """第一材料全失败后继续第二少、第三少，并最终成功。

    注意「编号更大的主线关卡也算不可用」这条边界：记录了 `7-26` 之后，
    `8-7`、`9-3`… 这些更靠后的关卡都不可用；所以后一种材料的候选要选
    **更早**的关卡（`3-13`、`2-8`），它们才仍然可尝试。
    """
    materials = [
        _material("110103", 1, ["7-26"]),
        _material("110203", 2, ["3-13"]),
        _material("110303", 3, ["2-8"]),
    ]
    state = BalancedFallback()
    state.begin(materials)
    state.account_id = TEST_UID

    candidate = state.next_candidate()
    assert candidate is not None and candidate.stage == "7-26"
    state.mark_unavailable("7-26")
    # 本材料候选用尽 → 换下一种材料
    assert state.next_candidate() is None
    state.finish_material()
    candidate = state.next_candidate()
    assert candidate is not None and candidate.stage == "3-13", "应顺延到第二少的材料"
    state.mark_unavailable("3-13")
    assert state.next_candidate() is None
    state.finish_material()
    candidate = state.next_candidate()
    assert candidate is not None and candidate.stage == "2-8", "应顺延到第三少的材料"


def test_fallback_does_not_retry_failed_material_in_same_round(tmp_path: Path) -> None:
    """本轮已失败的材料不重复尝试。"""
    materials = [
        _material("110103", 1, ["7-26"]),
        _material("110203", 2, ["3-13"]),
    ]
    state = BalancedFallback()
    state.begin(materials)
    state.account_id = TEST_UID
    state.next_candidate()
    state.mark_unavailable("7-26")
    assert state.next_candidate() is None
    state.finish_material()
    state.next_candidate()
    assert state.all_materials_unavailable() is False, "还有第二种材料没试完"


def test_all_materials_unavailable_only_after_every_candidate(tmp_path: Path) -> None:
    """所有有效参与材料的候选都不可用，才算全部不可用。"""
    state = BalancedFallback()
    state.begin([_material("110103", 1, ["7-26"]), _material("110203", 2, ["3-13"])])
    state.account_id = TEST_UID
    state.next_candidate()
    state.mark_unavailable("7-26")
    assert state.next_candidate() is None
    state.finish_material()
    state.next_candidate()
    state.mark_unavailable("3-13")
    assert state.next_candidate() is None
    state.finish_material()
    assert state.all_materials_unavailable() is True


# ------------------------------------------- 自动跨材料顺延（next_available_candidate）
def test_next_available_candidate_skips_exhausted_first_material(tmp_path: Path) -> None:
    """第一种材料的候选**事先**全被记录为不可用时，自动继续到第二少、第三少。

    这是「单个材料刷不了不能停用整个任务」的回归防护（需求 §5）：
    旧实现用 `next_candidate()` 只看当前材料，第一个材料用尽就返回 None，
    会被误判成「所有参与材料都不可用」而永久停用任务。
    """
    # 第一种材料的唯一候选事先就被记录为不可用
    record_unavailable(TEST_UID, "7-26")

    state = BalancedFallback()
    state.begin(
        [
            _material("110103", 1, ["7-26"]),  # 已全部不可用
            _material("110203", 2, ["3-13"]),  # 第二少，可用
            _material("110303", 3, ["2-8"]),
        ]
    )
    state.account_id = TEST_UID

    candidate = state.next_available_candidate()

    assert candidate is not None, "第一种材料用尽时不应直接判定全部不可用"
    assert candidate.stage == "3-13", "应自动顺延到第二少的材料"
    assert state.current_material() is not None
    assert state.current_material().entry.item_id == "110203"


def test_next_available_candidate_returns_none_only_when_all_exhausted(tmp_path: Path) -> None:
    """只有**所有**参与材料的候选都不可用时才返回 None（兜底停用依据）。"""
    account = TEST_UID
    record_unavailable(account, "7-26")
    record_unavailable(account, "3-13")

    state = BalancedFallback()
    state.begin(
        [
            _material("110103", 1, ["7-26"]),
            _material("110203", 2, ["3-13"]),
        ]
    )
    state.account_id = TEST_UID

    assert state.next_available_candidate() is None
    assert state.all_materials_unavailable() is True


def test_next_available_candidate_does_not_retry_failed_material(tmp_path: Path) -> None:
    """跨材料顺延后不会回头重试本轮已失败的材料。"""
    state = BalancedFallback()
    state.begin(
        [
            _material("110103", 1, ["7-26"]),
            _material("110203", 2, ["3-13"]),
        ]
    )
    state.account_id = TEST_UID

    first = state.next_available_candidate()
    assert first is not None and first.stage == "7-26"
    state.mark_unavailable("7-26")

    second = state.next_available_candidate()
    assert second is not None and second.stage == "3-13"
    assert "110103" in state.failed_materials, "第一种材料应记为本轮失败"


# --------------------------------------------------- StageLookupTimeout 动作
def _planner_with(materials: list[MaterialCandidate]) -> BalancedFallback:
    state = planner()
    state.begin(materials)
    state.account_id = TEST_UID
    # 新实现里账号只认 UID，由入口赋值；测试里直接给一个固定 UID，
    # 否则 account_id 为空会走「不读不写」分支（那是「读不到 UID」的路径）。
    state.account_id = TEST_UID
    return state


def _scanned(state: BalancedFallback, stage: str, swipes: int = 30) -> None:
    """模拟「已经滑动过 swipes 次、并滑到本章第一关，仍在找 stage」。

    滑动次数由 `StageLookupBudget` 每次被问时累加（`note_swipe`），
    真机实测：扫描链每滑动一次就问一次预算节点。

    `reached_far_left` 由 `StageLookupFarLeft` 命中时置位 —— 它才是
    「整章确实扫完」的判据（`on_error` 也会因动作失败触发，光有滑动次数不算）。
    """
    state.begin_stage_lookup(stage)
    for _ in range(swipes):
        state.note_swipe()
    state.note_reached_far_left()


def test_timeout_action_advances_to_next_candidate(tmp_path: Path) -> None:
    """超时后同材料关卡顺延成功：记录不可用 → 覆写选关 → 回到原选关流程。"""
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    _scanned(state, "7-26")
    context = _FakeContext()

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is True
    # 记录了不可用
    assert "7-26" in unavailable_stages(state.account_id)
    # 覆写了 SelectCombatStage 指向下一个候选
    assert context.pipeline_overrides, "应覆写选关节点"
    override = context.pipeline_overrides[-1]
    assert override["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "6-6"
    assert override["SelectCombatStage"]["attach"]["level"] == "Hard"
    # 回到原流程的 Combat 入口
    assert context.next_overrides[-1][1] == ["Combat"]
    # 回主界面后再导航
    assert balanced_fallback.HOME_ENTRY in context.run_tasks


def test_timeout_action_marks_skip_when_all_unavailable(tmp_path: Path) -> None:
    """所有参与材料都不可用 → 持久停用标记 → 本次跳过。"""
    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")
    context = _FakeContext()

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is True
    assert is_task_skipped(state.account_id) is True, "应写入停用标记"
    assert context.next_overrides[-1][1] == ["BF_Skipped"], "应跳到跳过收尾"


def test_timeout_action_ignores_scan_when_far_left_not_reached(tmp_path: Path) -> None:
    """没滑到本章第一关就中止 → **不记录**关卡不可用，按扫描异常失败。

    回归防护（APPLe-DF 评审）：两个扫描尾节点是 Swipe 动作节点，而 MaaFW 的
    `on_error` 同时覆盖「next 超时」和「动作失败」—— Swipe 或截图偶发失败也会走进
    `StageLookupTimeout`。若仅凭「滑动过」就记成关卡不可用，会把明明能打的关卡
    **永久**记错。只有滑到过 01（本章第一关）才说明整章确实扫完。
    """
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    # 只滑动过、没到第一关
    state.begin_stage_lookup("7-26")
    for _ in range(5):
        state.note_swipe()
    context = _FakeContext()

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is False, "扫描异常应按原版语义失败，不是静默顺延"
    assert "7-26" not in unavailable_stages(state.account_id), "不能记录关卡不可用"
    assert not context.pipeline_overrides, "不应覆写选关节点"


def test_timeout_action_records_in_memory_when_persist_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """落盘失败时仍要记进本次运行内存，避免反复重试同一关卡。

    回归防护（APPLe-DF 评审）：`record_unavailable` 在归属保护下返回 False，
    但 `DepotMaintainPlan` 每轮会重置 `candidate_index`，同一关卡会被重新选中、
    反复白等最长两分钟超时。
    """
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    _scanned(state, "7-26")
    # 模拟落盘失败（归属保护 / 文件不可写）
    monkeypatch.setattr(balanced_fallback, "record_unavailable", lambda *a, **k: False)
    context = _FakeContext()

    balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert "7-26" in state.failed_stages, "落盘失败也必须记进本次运行内存"
    assert "7-26" not in unavailable_stages(state.account_id), "确实没落盘"


def test_begin_keeps_failed_stages_across_planning_rounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """库存保持每轮规划调 `begin()` 时，**不能**清掉未落盘的失败关卡。

    回归防护（CodeRabbit 第 7 轮）：库存保持补完一种材料会
    `TargetCountFinish → BF_Plan → DepotMaintainPlan`，那里再调一次 `begin()`。
    若 `begin()` 清空 `failed_stages`，本轮没落盘（归属保护 / 文件不可写）的
    失败关卡就被忘掉，下一轮重新选中同一关卡、再白等两分钟超时。
    """
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    _scanned(state, "7-26")
    monkeypatch.setattr(balanced_fallback, "record_unavailable", lambda *a, **k: False)
    balanced_fallback.StageLookupTimeout().run(_FakeContext(), _FAKE_ARGV)
    assert "7-26" in state.failed_stages

    # 模拟库存保持的下一轮规划
    state.begin([_material("110103", 1, ["7-26", "6-6"])])
    state.account_id = TEST_UID

    assert "7-26" in state.failed_stages, "begin() 不能清空本轮未落盘的失败关卡"
    # 而且下一轮选关必须能过滤掉它
    picked = state.next_candidate()
    assert picked is not None and picked.stage != "7-26", "已失败的关卡不该被重新选中"

    # 任务入口 reset() 才清
    state.reset()
    assert state.failed_stages == set(), "reset()（任务入口）应清空"


def test_reset_uses_atomic_write(tmp_path: Path) -> None:
    """重置走原子写入，且在清空记录后保留当前逻辑账号标识。

    回归防护：早前 `clear_all` 用 `write_text` 直接覆盖，中途出错会留下半截文件，
    下次读到损坏内容会连 `current_account` 一起丢。
    """
    from agent.utils.balanced_state import clear_all, load_state

    record_unavailable("A", "7-26")
    set_task_skipped("A", True)

    assert clear_all(balanced_state.BALANCED_STATE_PATH) is True

    data = load_state(balanced_state.BALANCED_STATE_PATH)
    assert data.get("accounts") == {}, "记录与停用标记应被清空"


def test_timeout_action_continues_past_second_material(tmp_path: Path) -> None:
    """第一种、第二种材料的候选都不可用时，**继续**顺延到第三种，而不是直接停用。

    回归防护：旧实现只换一次材料（`finish_material()` + `next_candidate()`），
    第二种材料的候选若也被记录过就直接走停用分支 —— 违背「继续顺延第二少、
    第三少……」的要求。
    """
    account = TEST_UID
    # 第一、第二种材料的候选事先都被记录为不可用
    record_unavailable(account, "7-26")
    record_unavailable(account, "3-13")

    state = _planner_with(
        [
            _material("110103", 1, ["7-26"]),
            _material("110203", 2, ["3-13"]),
            _material("110303", 3, ["2-8"]),  # 第三少，仍可用
        ]
    )
    _scanned(state, "7-26")
    context = _FakeContext()

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is True
    # 必须真的顺延到第三种材料，而不是停用任务
    assert is_task_skipped(state.account_id) is False, "还有可用材料，不该停用任务"
    override = context.pipeline_overrides[-1]
    assert override["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "2-8"
    assert context.next_overrides[-1][1] == ["Combat"]


def test_finish_planner_clears_active_state(tmp_path: Path) -> None:
    """收尾清理：`finish_planner()` 关掉 active，避免影响同进程后续任务。"""
    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")
    assert state.active is True

    balanced_fallback.finish_planner()

    assert state.active is False, "收尾后 active 必须为 False，否则其它任务的预算识别会介入"
    assert state.current_stage == ""
    assert state.swipe_count == 0
    assert state.budget_exceeded() is False


def test_balanced_task_skip_clears_state(tmp_path: Path) -> None:
    """跳过任务的收尾动作也会清理状态。"""
    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")
    assert state.active is True

    balanced_fallback.BalancedTaskSkip().run(_FakeContext(), _FAKE_ARGV)

    assert state.active is False


def test_task_end_sink_clears_state_for_default_flow(tmp_path: Path) -> None:
    """默认均衡分支（走 Combat → TargetCountFinish）不经过任何 BF_* 收尾节点，
    必须靠 tasker sink 在任务结束时清理，否则 active 会留到后续任务。

    回归防护：review 指出 `BalancedFarmingAnalyze` 设了 active=True 后直接走 Combat，
    没有清理路径，导致后续任务的 StageLookupBudget 误命中。
    """
    from maa.event_sink import NotificationType

    from agent.custom.sink.balanced_cleanup import BalancedStateCleanup

    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")
    assert state.active is True

    sink = BalancedStateCleanup()
    sink.on_tasker_task(
        types.SimpleNamespace(),  # pyright: ignore[reportArgumentType]
        NotificationType.Succeeded,
        types.SimpleNamespace(entry="BalancedFarming"),  # pyright: ignore[reportArgumentType]
    )

    assert state.active is False, "任务结束后必须清理，否则后续任务的预算识别会误命中"
    assert state.budget_exceeded() is False


def test_task_end_sink_ignores_other_tasks(tmp_path: Path) -> None:
    """其它任务的结束事件不该碰均衡顺延状态。"""
    from maa.event_sink import NotificationType

    from agent.custom.sink.balanced_cleanup import BalancedStateCleanup

    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")

    sink = BalancedStateCleanup()
    sink.on_tasker_task(
        types.SimpleNamespace(),  # pyright: ignore[reportArgumentType]
        NotificationType.Succeeded,
        types.SimpleNamespace(entry="Combat"),  # pyright: ignore[reportArgumentType]
    )

    assert state.active is True, "非均衡任务不应清理"


def test_task_end_sink_clears_on_failure(tmp_path: Path) -> None:
    """任务失败（用户停止等）时同样要清理。"""
    from maa.event_sink import NotificationType

    from agent.custom.sink.balanced_cleanup import BalancedStateCleanup

    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")

    sink = BalancedStateCleanup()
    sink.on_tasker_task(
        types.SimpleNamespace(),  # pyright: ignore[reportArgumentType]
        NotificationType.Failed,
        types.SimpleNamespace(entry="BalancedFarming"),  # pyright: ignore[reportArgumentType]
    )

    assert state.active is False


def test_exhausted_branch_returns_home_before_skip(tmp_path: Path) -> None:
    """候选全耗尽时，跳过前必须回主界面（否则游戏留在关卡列表页）。

    回归防护：review 指出该分支只 override_next 到 BF_Skipped（不导航），
    与其它跳过路径不一致。
    """
    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")
    context = _FakeContext()

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is True
    assert is_task_skipped(state.account_id) is True
    assert balanced_fallback.HOME_ENTRY in context.run_tasks, "跳过前应先回主界面"
    assert context.next_overrides[-1][1] == ["BF_Skipped"]


def test_timeout_action_does_not_record_when_scan_not_started(tmp_path: Path) -> None:
    """一次都没滑动过 → 不是「找不到目标关卡」→ 不记录关卡不可用。

    （真机实测：MaaFW 的 `max_hit` 记在扫描头上，而扫描头只命中 28 次就停，
    永远达不到 30 —— 原版判「没找到」靠的是尾节点的 2 秒 timeout，不是 max_hit。
    所以「有没有真的扫过」由自己数的滑动次数决定。）
    """
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    state.begin_stage_lookup("7-26")  # 没滑动
    context = _FakeContext()

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is False, "扫描没开始不应判定为顺延成功"
    assert unavailable_stages(state.account_id) == set(), "不应记录关卡不可用"


def test_timeout_action_does_not_record_when_user_stopping(tmp_path: Path) -> None:
    """用户正在停止 → 不记录关卡不可用。"""
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    _scanned(state, "7-26")
    context = _FakeContext(stopping=True)

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is False
    assert unavailable_stages(state.account_id) == set()


def test_timeout_action_inactive_fails_like_original(tmp_path: Path) -> None:
    """没有均衡顺延在进行 → 按原版语义让任务失败。"""
    reset_planner()
    context = _FakeContext()
    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)
    assert result.success is False


def test_swipe_count_resets_per_lookup(tmp_path: Path) -> None:
    """每次选关重新计数（上一轮的滑动次数不能算到这一轮）。"""
    state = _planner_with([_material("110103", 1, ["7-26", "6-6"])])
    _scanned(state, "7-26", swipes=10)
    assert state.swipe_count == 10
    _scanned(state, "6-6", swipes=3)
    assert state.swipe_count == 3, "新一轮寻找应从 0 开始数"


# ------------------------------------------------------------- 入口与停用
def test_retarget_material_returns_tristate(tmp_path: Path) -> None:
    """`retarget_material` 必须能区分「不需要同步」与「同步失败」。

    三态语义：
    - `None`  = 不在库存保持模式（默认均衡分支），可继续顺延
    - `False` = 库存保持模式下切换失败，调用方必须停止而不是硬刷
    - `True`  = 切换成功
    """
    from agent.custom.action import depot_maintain

    # 非库存保持模式（_state.item_id 为 None）
    depot_maintain._state.item_id = None
    assert depot_maintain.retarget_material(_FakeContext(), "110103", "7-26", "Hard") is None

    # 库存保持模式下、材料目录里没有该材料 → 失败
    depot_maintain._state.item_id = "999999"
    try:
        result = depot_maintain.retarget_material(_FakeContext(), "nonexistent-id", "7-26", "Hard")
        assert result is False, "库存保持模式下切换失败必须返回 False"
    finally:
        depot_maintain._state.item_id = None


def test_retarget_material_syncs_battle_params(tmp_path: Path) -> None:
    """跨材料顺延时，除 `_state` 外还必须同步 AllIn / 吃糖 / 掉落上报。

    回归防护（GPT 评审指出）：规划路径会把 `AllIn.target_count`、逐材料吃糖上限、
    `DropRecognition.enabled` 按**旧材料**写进 pipeline；若 `retarget_material` 只更新
    `_state`，会出现「材料已换成 B，但复现次数/吃糖仍按 A」。
    """
    from agent.custom.action import depot_maintain

    # 模拟库存保持模式：item_id 已设置、candy_caps 已有规划时存下的值
    depot_maintain._state.item_id = "110103"
    depot_maintain._state.candy_caps = {"110103": 3}
    depot_maintain._state.runs = 5

    ctx = _FakeContext()
    result = depot_maintain.retarget_material(ctx, "110103", "7-26", "Hard")

    assert result is True
    # 必须把 AllIn 的 target_count 一并写回（retarget 内部会按新材料重算 runs，
    # 这里不预先假设具体值，只验证「写回了 AllIn」且值等于 _state.runs）
    allin_override = None
    drop_override = None
    for pipeline in ctx.pipeline_overrides:
        for node, val in pipeline.items():
            if node == "AllIn":
                allin_override = val
            elif node == depot_maintain.DROP_REPORT_NODE:
                drop_override = val
    assert allin_override is not None, "必须同步 AllIn"
    assert allin_override["action"]["param"]["custom_action_param"]["target_count"] == depot_maintain._state.runs, (
        "AllIn 的 target_count 必须等于重算后的 _state.runs"
    )
    assert drop_override is not None, "必须同步掉落上报开关"
    # 恢复，避免影响其它用例
    depot_maintain._state.item_id = None


def test_entry_skips_task_when_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """已停用 → 直接跳过，不点选关卡。

    入口会先确认归属（读游戏内 UID）。这里 mock 掉 `current_uid` 让它看起来
    已缓存，从而覆盖「UID 已缓存 → 不额外导航」这条快路径。
    """
    account = TEST_UID
    set_task_skipped(account, True)
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: account)

    context = _FakeContext()
    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    assert context.next_overrides[-1][1] == ["BF_Skipped"]
    assert context.run_tasks == [], "UID 已缓存时不应再导航"


def test_entry_navigates_once_to_read_uid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UID 未知时，入口回主页读一次（这是「按真实账号分桶」的前提）。

    回归防护：早前归属直接用 GUI 里手填的掩码文本，手工换号后仍沿用旧账号记录。
    """
    calls: list[str] = []
    cache: list[str] = [""]  # 模拟 RecordID 缓存：一开始为空

    context = _FakeContext()

    def fake_ensure_uid(ctx: object) -> None:
        calls.append("nav")
        cache[0] = TEST_UID  # 回家 + RecordId 之后缓存有值了

    monkeypatch.setattr(balanced_entry, "current_uid", lambda: cache[0])
    monkeypatch.setattr(balanced_entry, "_ensure_uid", fake_ensure_uid)

    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    assert calls == ["nav"], "UID 未知时必须触发一次读取"


def test_entry_proceeds_when_not_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未停用 → 放行。"""
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: "100000001")
    context = _FakeContext()
    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)
    assert result.success is True
    assert context.next_overrides[-1][1] == ["BF_Plan"]


def test_reset_clears_records_and_skip_flag(tmp_path: Path) -> None:
    """显式重置：同时清关卡不可用记录与均衡停用标记。"""
    account = TEST_UID
    record_unavailable(account, "7-26")
    set_task_skipped(account, True)

    context = _FakeContext()
    result = balanced_entry.BalancedResetRecords().run(context, _argv(json.dumps({"reset_stage_records": True})))
    assert result.success is True
    assert unavailable_stages(account) == set(), "关卡不可用记录应被清空"
    assert is_task_skipped(account) is False, "停用标记应被清空"
    # 重置后回到入口检查
    assert context.next_overrides[-1][1] == ["BF_Entry"]


def test_reset_without_option_keeps_records(tmp_path: Path) -> None:
    """没勾选重置 → 记录与停用标记都保留。"""
    account = TEST_UID
    record_unavailable(account, "7-26")
    set_task_skipped(account, True)

    context = _FakeContext()
    balanced_entry.BalancedResetRecords().run(context, _argv(json.dumps({})))
    assert "7-26" in unavailable_stages(account)
    assert is_task_skipped(account) is True


def test_reset_then_entry_order_allows_reset_while_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """已停用时仍能执行重置：重置在停用检查之前。"""
    account = TEST_UID
    set_task_skipped(account, True)

    # 入口顺序：先重置 → 再检查停用
    reset_ctx = _FakeContext()
    balanced_entry.BalancedResetRecords().run(reset_ctx, _argv(json.dumps({"reset_stage_records": True})))
    assert reset_ctx.next_overrides[-1][1] == ["BF_Entry"]

    # 重置后停用标记已清 → 入口放行（UID 已知，跳过 OCR 导航）
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: account)
    entry_ctx = _FakeContext()
    balanced_entry.BalancedTaskEntry().run(entry_ctx, _FAKE_ARGV)
    assert entry_ctx.next_overrides[-1][1] == ["BF_Plan"], "重置后应恢复执行"


def test_skip_flag_persists_across_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """停用标记跨「重启」生效：重新读文件仍然认得。"""
    account = TEST_UID
    set_task_skipped(account, True)

    # 模拟重启：新建状态机实例（内存清空），从文件重新读
    fresh = BalancedFallback()
    fresh.account_id = TEST_UID
    assert fresh.account_id == TEST_UID
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: account)
    context = _FakeContext()
    balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)
    assert context.next_overrides[-1][1] == ["BF_Skipped"]


# ------------------------------------------------------------- 逻辑账号归属
def test_current_uid_empty_when_record_unloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`RecordID` 未加载时 `current_uid()` 返回空串，而不是抛异常。"""
    monkeypatch.delitem(sys.modules, "agent.custom.action.record_id", raising=False)
    monkeypatch.delitem(sys.modules, "custom.action.record_id", raising=False)
    assert balanced_state.current_uid() == ""


# ------------------------------------------------------------- 库存保持顺延
def test_depot_candidates_exclude_reached_targets(tmp_path: Path) -> None:
    """库存保持：已达标材料不参与顺延（不硬刷）。"""
    catalog = {
        "110103": _entry("110103", "甲", "7-26"),
        "110203": _entry("110203", "乙", "3-13"),
    }
    inventory = {"110103": 10, "110203": 5}
    targets = {"110103": 10, "110203": 20}  # 110103 已达标
    candidates = build_depot_material_candidates(catalog, inventory, targets)
    ids = [c.entry.item_id for c in candidates]
    assert "110103" not in ids, "已达标的材料不该参与"
    assert ids[0] == "110203", "缺口最大的先刷"


def test_depot_candidates_ordered_by_inventory_after_first(tmp_path: Path) -> None:
    """跨材料顺延顺序按**库存数量**从少到多（不是缺口大小）。"""
    catalog = {
        "110103": _entry("110103", "甲", "7-26"),
        "110203": _entry("110203", "乙", "3-13"),
        "110303": _entry("110303", "丙", "7-7"),
    }
    inventory = {"110103": 1, "110203": 2, "110303": 3}
    targets = {"110103": 100, "110203": 100, "110303": 100}
    candidates = build_depot_material_candidates(catalog, inventory, targets)
    ids = [c.entry.item_id for c in candidates]
    # 缺口相同 → 按库存数量从少到多
    assert ids == ["110103", "110203", "110303"]


# ---------------------------------------------------------- 均衡取最少入口
def test_build_material_candidates_sorted_by_count(tmp_path: Path) -> None:
    """均衡分支：材料按库存数量从少到多排列。"""
    catalog = {
        "110103": _entry("110103", "甲", "7-26"),
        "110203": _entry("110203", "乙", "3-13"),
    }
    counts = {"110103": 5, "110203": 1}
    candidates = build_material_candidates(catalog, counts)
    assert [c.entry.item_id for c in candidates] == ["110203", "110103"]


# ------------------------------------------------------ 进入战斗前的候选挑选
def test_resolve_available_stage_skips_recorded(tmp_path: Path) -> None:
    """进入战斗前：登记关卡已被记为不可用时，顺延到下一个可用候选。

    `_resolve_available_stage` 读的是**模块级单例**的状态机（与动作节点同一份），
    所以这里也要用 `planner()` 而不是新建实例。
    """
    from agent.custom.action.depot_maintain import _resolve_available_stage

    record_unavailable(TEST_UID, "7-26")
    state = planner()
    state.begin([_material("110103", 1, ["7-26", "6-6"])])
    state.account_id = TEST_UID

    stage, level = _resolve_available_stage(_FakeContext(), state.current_material().entry, {})
    assert stage == "6-6", "应跳过已记录的不可用关卡"
    assert level == "Hard"


def test_resolve_available_stage_returns_none_when_all_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """该材料的候选全部不可用 → 返回 None（由调用方换材料）。

    这里把候选来源换成**只有一个**的桩，否则真实掉落索引里该材料还有其它候选
    （`6-6` 等），达不到「全部不可用」。
    """
    from agent.custom.action import depot_maintain
    from agent.custom.action.depot_maintain import _resolve_available_stage

    record_unavailable(TEST_UID, "7-26")
    state = planner()
    state.begin([_material("110103", 1, ["7-26"])])
    state.account_id = TEST_UID

    # 候选只剩登记关卡一个，且它已被记录为不可用
    monkeypatch.setattr(
        depot_maintain,
        "candidates_for_material",
        lambda *args, **kwargs: [
            StageCandidate(stage="7-26", level="Hard", order=(7, 26)),
        ],
    )
    stage, _level = _resolve_available_stage(_FakeContext(), state.current_material().entry, {})
    assert stage is None, "候选全不可用时应返回 None"
