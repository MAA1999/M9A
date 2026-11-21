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
import os
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

# 只在这里导入一次：每个测试里再 `from custom.reco import ...` 会触发第二张模块图，
# 导致 `Custom name is already registered`（跨文件跑 pytest 时尤其明显）。
from agent.custom.reco import balanced_fallback as reco_balanced_fallback
from agent.custom.reco import general as reco_general
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
    cached_image = "IMG"

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

    def run_recognition_direct(self, *args: Any, **kwargs: Any) -> Any:
        return types.SimpleNamespace(hit=False, all_results=[], best_result=None)

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
    # 文件名带上进程号：并行跑多份 pytest 时，同一条用例的两次执行不能共用一个
    # 状态文件（否则一边 unlink、另一边刚写完，断言会读到缺失或别人的记录）。
    safe = request.node.name.replace("/", "_").replace("\\", "_")
    path = _state_path(Path("."), f"state_{safe}_{os.getpid()}.json")
    # 上一次运行留下的同名文件会让用例互相干扰（状态是持久资源）→ 先清掉
    path.unlink(missing_ok=True)
    # `agent.utils.*` 与 `utils.*` 是两张模块图（同一份源码、两个模块对象），
    # 两边都要打补丁 —— 只改一个的话，另一张图里的函数仍会写回默认路径。
    for module in (balanced_state, _plain_balanced_state):
        monkeypatch.setattr(module, "BALANCED_STATE_PATH", path)
    reset_planner()
    yield
    # ⚠️ `RecordID.global_id` 是**类变量**，`_remember_uid()` 会把它设成本用例的
    # UID。不清掉的话，后续文件（如 test_warehouse_inventory）会用它当快照桶键，
    # 拿不到 `__default__` 桶 → KeyError。这里必须复位。
    _reset_record_id()
    # ⚠️ 顺延状态机是**模块级单例**，用例跑完后必须清掉：`BalancedTaskEntry` /
    # `StageLookupTimeout` 都会把它 `begin()` 成 active，残留的候选顺序会被
    # 后续文件（如 test_balanced_farming）读到，导致选关结果对不上预期。
    reset_planner()


def _reset_record_id() -> None:
    """把 `RecordID` 的缓存清空（它是类变量，跨用例共享）。"""
    for name in ("agent.custom.action.record_id", "custom.action.record_id"):
        module = sys.modules.get(name)
        if module is None:
            continue
        record_id = getattr(module, "RecordID", None)
        if record_id is None:
            continue
        record_id.global_id = ""
        record_id.global_user_name = ""


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


def test_no_difficulty_excludes_story_and_hard() -> None:
    index = {"7-26E": [110103], "7-26G": [110103], "7-12": [110103]}
    candidates = candidates_for_material("110103", level="None", registered_stage="ME-02", drop_index=index)
    assert [c.stage for c in candidates] == ["ME-02", "7-12"]


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


def test_retarget_material_syncs_battle_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """跨材料顺延时，除 `_state` 外还必须同步 AllIn / 吃糖 / 掉落上报。

    回归防护（GPT 评审指出）：规划路径会把 `AllIn.target_count`、逐材料吃糖上限、
    `DropRecognition.enabled` 按**旧材料**写进 pipeline；若 `retarget_material` 只更新
    `_state`，会出现「材料已换成 B，但复现次数/吃糖仍按 A」。

    ⚠️ 这里刻意用**两种不同材料**（旧 A=110103、新 B=110203），并给它们不同的
    缺口与吃糖上限：如果哪一项没被刷新，断言就会读到 A 的旧值而失败。
    """
    from utils.balanced_state import candidates_for_material

    from agent.custom.action import depot_maintain

    old_id, new_id = "110103", "110203"

    # 模拟库存保持模式：旧的 A 在位，且 A 的吃糖上限是 3
    depot_maintain._state.item_id = old_id
    depot_maintain._state.candy_caps = {old_id: 3, new_id: 7}
    depot_maintain._state.runs = 5
    # 目标：A 缺 90、B 缺 20 —— 换过去后 runs 必须按 B 的缺口重算
    depot_maintain._state.targets = {old_id: 100, new_id: 20}
    monkeypatch.setattr(
        depot_maintain,
        "read_snapshot",
        lambda path=None: {"counts": {old_id: 10, new_id: 0}},
    )
    # 换材料要能反查候选（用真实掉落索引）
    assert candidates_for_material(old_id, level="Hard", registered_stage="7-26")
    monkeypatch.setattr(depot_maintain, "_confirmed_account_id", lambda: "")

    ctx = _FakeContext()
    result = depot_maintain.retarget_material(ctx, new_id, "3-13", "Hard")

    assert result is True
    assert depot_maintain._state.item_id == new_id, "目标材料必须真的换成新材料"

    merged: dict[str, Any] = {}
    for pipeline in ctx.pipeline_overrides:
        for node, val in pipeline.items():
            merged[node] = val

    # 1. AllIn 的复现次数按**新材料 B** 的缺口算，而不是旧材料 A 的 5
    allin = merged.get("AllIn") or {}
    target_count = allin["action"]["param"]["custom_action_param"]["target_count"]
    assert target_count == depot_maintain._state.runs
    assert target_count != 5, "不能沿用旧材料 A 的 runs"

    # 2. 吃糖上限换成 B 的 7（A 是 3）
    candy_start = merged.get("EatCandyStart") or {}
    assert candy_start.get("max_hit") == 7, f"吃糖上限应换成新材料 B 的 7，实际 {candy_start}"

    # 3. 掉落上报开关有明确值（不是「只存在」）
    drop = merged.get(depot_maintain.DROP_REPORT_NODE) or {}
    assert "enabled" in drop, "必须写入掉落上报开关的具体值"

    # 恢复，避免影响其它用例
    depot_maintain._state.item_id = None
    depot_maintain._state.targets = {}


def test_entry_skips_task_when_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """已停用 → 直接跳过，不点选关卡。

    入口会先确认归属（读游戏内 UID）。这里 mock 掉 `current_uid` 让它看起来
    已缓存，从而覆盖「UID 已缓存 → 不额外导航」这条快路径。
    """
    account = TEST_UID
    set_task_skipped(account, True)
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: account)
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: account)

    context = _FakeContext()
    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    assert context.next_overrides[-1][1] == ["BF_Skipped"]
    # 采样前**无条件**回主页（CodeRabbit：不能假定任务开始时停在主页，
    # 否则采样可能读到空画面、uid 为空 → 绕过停用判断）。
    assert "ResetReturnMain" in context.run_tasks, "采样前必须先回主页"


def test_entry_skips_only_after_uid_is_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """停用标记只用**采样确认后**的 UID 判断，不用缓存里的单次 OCR 值。

    回归防护（CodeRabbit）：`RecordID` 只做一次 OCR，认错一个数字就会把记录写进
    错误的桶、或用错误账号的停用标记跳过。所以入口必须走 `sample_uid()`，
    缓存里的值只决定「要不要先导航」。

    这里让缓存里是一个**已被停用**的旧值，而采样得到的是另一个**未停用**的账号：
    正确的实现会按采样结果照常刷取（BF_Plan），而不是被旧值误导跳过。
    """
    stale = "STALE-CACHED-UID"
    set_task_skipped(stale, True)

    context = _FakeContext()
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: stale)
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: TEST_UID)

    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    assert context.next_overrides[-1][1] == ["BF_Plan"], (
        "必须按采样确认的 UID 判断停用标记，不能采信缓存里的单次 OCR 值"
    )


def test_entry_skips_when_sampled_uid_is_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """采样确认的 UID 确实被停用 → 跳过，且**不截图**。

    回归防护：停用是稳态路径（标记持久化，每次调度都走到），截图会无限堆积。
    """
    set_task_skipped(TEST_UID, True)

    context = _FakeContext()
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: TEST_UID)
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: TEST_UID)
    shots: list[str] = []
    monkeypatch.setattr(balanced_entry, "save_debug_screenshot", lambda ctx, tag: shots.append(tag))

    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    assert context.next_overrides[-1][1] == ["BF_Skipped"]
    assert shots == [], "停用跳过是稳态路径，不该每次都存截图"


def test_entry_navigates_once_to_read_uid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UID 未知时，入口回主页读一次（这是「按真实账号分桶」的前提）。

    回归防护：早前归属直接用 GUI 里手填的掩码文本，手工换号后仍沿用旧账号记录。
    """
    # 采样本身另有单测（tests/test_uid_sampler.py），这里只测入口分支
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: TEST_UID)
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
    # 采样本身另有单测（tests/test_uid_sampler.py），这里只测入口分支
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: TEST_UID)
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
    # 采样本身另有单测（tests/test_uid_sampler.py），这里只测入口分支
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: TEST_UID)
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
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: account)
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
    targets = {"110103": 5, "110203": 100, "110303": 200}
    candidates = build_depot_material_candidates(catalog, inventory, targets)
    ids = [c.entry.item_id for c in candidates]
    # 丙的缺口最大（197），先选丙；剩余两种按库存排序，甲（1）先于乙（2）。
    assert ids == ["110303", "110103", "110203"]


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


def test_entry_disables_depot_maintain_when_uid_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """采样失败时关掉库存保持，避免下游重读账号。

    回归防护（CodeRabbit, major）：清空 `RecordID` 缓存只保证入口不用未确认账号，
    但 `DepotMaintainPlan.run` 会调 `_ensure_account_id()`，缓存为空时它**再跑一次**
    `RecordId`，拿新读到的值当本轮账号，之后快照读写全按那个桶走。
    采样连读 6 次都不一致说明画面不可靠，这时再让下游单读一次决定快照桶风险更大。

    关掉库存保持后走 `LEGACY_ENTRY_NODE`，**顺延仍然保留**
    （`StageLookupTimeout` + `next_candidate()` 与库存保持无关）。
    """
    context = _FakeContext()
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: "")
    monkeypatch.setattr(balanced_entry, "_ensure_uid", lambda ctx: None)
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: "")  # 采样失败
    monkeypatch.setattr(balanced_entry, "save_debug_screenshot", lambda ctx, tag: None)

    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    assert context.next_overrides[-1][1] == ["BF_Plan"], "仍要进规划（顺延照常）"

    # 必须把 depot_disabled 写进 override，让库存保持退回原有流程
    merged = {}
    for payload in context.pipeline_overrides:
        for node, patch in payload.items():
            merged.setdefault(node, {}).update(patch)
    plan = merged.get("BF_Plan") or {}
    params = ((plan.get("action") or {}).get("param") or {}).get("custom_action_param") or {}
    assert params.get("depot_disabled") is True, "采样失败时必须关掉库存保持"


def test_entry_keeps_depot_maintain_when_uid_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UID 确认时不碰 `depot_disabled`（用户可能开了库存保持）。"""
    context = _FakeContext()
    monkeypatch.setattr(balanced_entry, "current_uid", lambda: TEST_UID)
    monkeypatch.setattr(balanced_entry, "_ensure_uid", lambda ctx: None)
    monkeypatch.setattr(balanced_entry, "sample_uid", lambda ctx: TEST_UID)

    result = balanced_entry.BalancedTaskEntry().run(context, _FAKE_ARGV)

    assert result.success is True
    merged = {}
    for payload in context.pipeline_overrides:
        for node, patch in payload.items():
            merged.setdefault(node, {}).update(patch)
    plan = merged.get("BF_Plan") or {}
    params = ((plan.get("action") or {}).get("param") or {}).get("custom_action_param") or {}
    assert "depot_disabled" not in params, "UID 正常时不该动库存保持开关"


def test_timeout_clears_planner_when_home_fails(tmp_path: Path) -> None:
    """回主页失败按失败结束前，必须清掉模块级 planner 状态。

    回归防护（CodeRabbit）：`_planner` 是跨任务存活的单例，
    异常退出若不清，残留的 `active=True` 会让之后其它任务（如常规作战）
    的 `StageLookupBudget` 识别也介入 —— 那些任务完全用不到顺延。
    """
    state = _planner_with([_material("110103", 1, ["7-26"])])
    _scanned(state, "7-26")
    assert state.active is True

    # home_ok=False → 回家任务返回失败
    context = _FakeContext(home_ok=False)

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is False, "回不了主页就该按失败结束"
    assert planner().active is False, "异常退出前必须清掉 planner 状态"


# ------------------------------------------------- StageLookupBudget 真实实例
class _BudgetArg:
    """`CustomRecognition.AnalyzeArg` 的最小桩（预算检查只用 image）。"""

    def __init__(self, image: Any = None) -> None:
        self.image = image
        self.custom_recognition_param = None


class _BudgetReco:
    """记录 `run_recognition_direct` 调用的最小 context。"""

    def __init__(self, results: list[str]) -> None:
        self.results = results
        self.calls: list[Any] = []

    def run_recognition_direct(self, reco_type: Any, param: Any, image: Any = None) -> Any:
        self.calls.append((reco_type, param, image))

        class _Detail:
            pass

        detail = _Detail()
        detail.all_results = [_TextResult(t) for t in self.results]
        return detail


class _TextResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.box = [10, 300, 40, 20]


def test_budget_returns_none_when_planner_inactive() -> None:
    """非均衡任务：预算检查必须无条件不匹配（原版行为不受影响）。"""
    mod = reco_balanced_fallback

    reset_planner()  # 定义在 action.balanced_fallback，模块级单例是同一个
    assert mod.StageLookupBudget().analyze(_FakeContext(), _BudgetArg()) is None


def test_budget_returns_none_before_deadline() -> None:
    """预算未到：返回 None，流程继续滑动。"""
    mod = reco_balanced_fallback

    state = planner()
    state.begin([_material("110103", 1, ["7-26"])])
    state.begin_stage_lookup("7-26")

    result = mod.StageLookupBudget().analyze(_FakeContext(), _BudgetArg())

    assert result is None
    assert state.swipe_count == 1, "每次被问都要记一次滑动"


def test_budget_hits_after_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """预算到点：返回匹配结果，并带上当前关卡与滑动次数。"""
    mod = reco_balanced_fallback

    state = planner()
    state.begin([_material("110103", 1, ["7-26"])])
    state.begin_stage_lookup("7-26")
    # 用假时钟推进到超过预算（不依赖机器 uptime）
    _force_budget(state, monkeypatch)

    result = mod.StageLookupBudget().analyze(_FakeContext(), _BudgetArg())

    assert result is not None, "预算超了必须命中，否则永远不会顺延"
    assert result.detail["node"] == "StageLookupBudget"
    assert result.detail["stage"] == "7-26"


class _FakeClock:
    """可控时钟：把 `monotonic()` 换成一个我们能随意推进的数。

    `time.monotonic()` 的**原点是任意的**（Linux 上是开机时长），任何
    「减一个大常数」的写法在 uptime 不足那个数时都会得到负数，而
    `budget_exceeded()` 把非正起点当成「还没开始」→ 测试在刚启动的机器上假失败。
    这里改成显式控制：起点一律是正数，需要超时时再推进。
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _force_budget(state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """把预算起点设成 1000，并推进到超过预算之后。

    同时 patch `balanced_fallback.time.monotonic`，让 `begin_stage_lookup()`
    记下的起点与 `budget_exceeded()` 读到的「现在」都来自同一个假时钟。
    """
    # 用文件顶部已导入的 alanced_fallback，不再局部 import（会触发第二张模块图）
    clock = _FakeClock()
    monkeypatch.setattr(balanced_fallback.time, "monotonic", clock.monotonic)
    state.begin_stage_lookup(state.current_stage or "7-26")
    budget_s = getattr(state, "lookup_budget_ms", 120_000) / 1000.0
    clock.advance(budget_s + 1.0)


# ----------------------------------------- StageLookupFarLeft 真实实例
def _patch_far_left_context(monkeypatch: pytest.MonkeyPatch, texts: list[str]) -> _BudgetReco:
    """让 `filter_by_color` 恒等返回，并注入识别结果。"""
    general = reco_general

    monkeypatch.setattr(general, "filter_by_color", lambda img, *a, **k: img)
    return _BudgetReco(texts)


def test_far_left_sets_flag_and_returns_box(monkeypatch: pytest.MonkeyPatch) -> None:
    """看到 `01` → 必须调用 `note_reached_far_left()` 并返回识别框。

    维护者指出：现有测试直接调 `state.note_reached_far_left()`，所以就算把
    `analyze()` 里那行删掉也不会失败。这里走真实路径。
    """
    mod = reco_balanced_fallback

    state = planner()
    state.begin([_material("110103", 1, ["7-26"])])
    state.begin_stage_lookup("7-26")
    assert state.reached_far_left is False

    context = _patch_far_left_context(monkeypatch, ["010203"])
    result = mod.StageLookupFarLeft().analyze(context, _BudgetArg(image="img"))

    assert result is not None, "看到 01 必须命中"
    assert state.reached_far_left is True, "analyze() 必须自己置位，不能靠测试代劳"
    assert result.detail["node"] == "StageLookupFarLeft"


def test_far_left_ignores_non_01_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 `01` → 不命中、也不置位。"""
    mod = reco_balanced_fallback

    state = planner()
    state.begin([_material("110103", 1, ["7-26"])])
    state.begin_stage_lookup("7-26")

    context = _patch_far_left_context(monkeypatch, ["201", "13-10"])
    result = mod.StageLookupFarLeft().analyze(context, _BudgetArg(image="img"))

    assert result is None
    assert state.reached_far_left is False


def test_far_left_returns_none_when_planner_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """非均衡任务：不匹配，原版 TheFarLeftOfStageList 照常接管。"""
    mod = reco_balanced_fallback

    reset_planner()  # 定义在 action.balanced_fallback，模块级单例是同一个
    context = _patch_far_left_context(monkeypatch, ["01"])
    result = mod.StageLookupFarLeft().analyze(context, _BudgetArg(image="img"))

    assert result is None
    assert context.calls == [], "未激活时不该跑识别"


def test_far_left_reraises_interface_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口类错误必须抛出，不能静默变成「永远没到第一关」。"""
    mod = reco_balanced_fallback

    state = planner()
    state.begin([_material("110103", 1, ["7-26"])])
    state.begin_stage_lookup("7-26")

    class _BrokenContext:
        def run_recognition_direct(self, *a: Any, **k: Any) -> Any:
            raise TypeError("signature mismatch")

    general = reco_general

    monkeypatch.setattr(general, "filter_by_color", lambda img, *a, **k: img)

    with pytest.raises(TypeError):
        mod.StageLookupFarLeft().analyze(_BrokenContext(), _BudgetArg(image="img"))


# ------------------------------------ 记录不可用前复核目标（CodeRabbit major）
class _RecheckContext(_FakeContext):
    """可注入「目标是否在屏幕上」的上下文桩。

    `StageLookupTimeout` 在 `mark_unavailable()` 之前会跑一次独立复核，
    这里用假的 `cached_image` + `run_recognition_direct` 控制复核结论。
    """

    def __init__(self, *, target_visible: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.target_visible = target_visible
        self.recheck_calls = 0
        self.tasker = types.SimpleNamespace(
            stopping=False,
            controller=types.SimpleNamespace(cached_image=object()),
        )

    def run_recognition_direct(self, reco_type: Any, param: Any, image: Any = None) -> Any:
        self.recheck_calls += 1

        class _Detail:
            pass

        detail = _Detail()
        if self.target_visible:
            box = [10, 400, 60, 20]
            detail.all_results = [
                types.SimpleNamespace(text=f"{self.recheck_stage} Hard", box=box),
            ]
            detail.best_result = types.SimpleNamespace(text=f"{self.recheck_stage} Hard", box=box, score=0.9)
        else:
            detail.all_results = []
            detail.best_result = None
        return detail


def _scanned_and_at_far_left(state: Any, stage: str = "13-10") -> None:
    """把状态机布置成「滑到过第一关、目标没找到、最多还试一次」。"""
    state.begin([_material("110103", 1, [stage])])
    state.begin_stage_lookup(stage)
    state.note_swipe()
    state.note_reached_far_left()


def test_timeout_does_not_record_when_target_still_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """目标就在屏幕上时**不能**记成不可用。

    回归防护（CodeRabbit major）：`StageLookupFarLeft` 命中只说明这一帧有 01；
    `TargetStageName` 那一帧如果颜色识别没成，一个明明存在的目标会被当成
    「已滑到最左、目标确实不存在」，永久记进不可用清单。
    """
    state = _planner_with([_material("110103", 1, ["13-10"])])
    _scanned_and_at_far_left(state)

    context = _RecheckContext(target_visible=True)
    context.recheck_stage = "13-10"  # type: ignore[attr-defined]
    monkeypatch.setattr(balanced_fallback, "_target_visible_on_screen", lambda c, s: True)

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert result.success is False, "复核发现目标就在屏幕上 → 本次不记录、按失败结束"
    assert "13-10" not in state.failed_stages, "不能把这个关卡记成不可用"
    assert not state.failed_stages


def test_timeout_records_when_target_really_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """复核也确认看不见时才记不可用并顺延（原有行为不变）。"""
    state = _planner_with([_material("110103", 1, ["13-10"])])
    _scanned_and_at_far_left(state)

    context = _RecheckContext(target_visible=False)
    monkeypatch.setattr(balanced_fallback, "_target_visible_on_screen", lambda c, s: False)

    result = balanced_fallback.StageLookupTimeout().run(context, _FAKE_ARGV)

    assert "13-10" in state.failed_stages, "确认看不见才记录不可用"
    # 只有一个候选且回家成功 → 记录后应当收尾（转 BF_Skipped），而不是报失败
    assert result.success is True, "记录并顺延成功后应返回成功"
    # _FakeContext.override_next 记的是 (节点名, next列表) 元组
    last = context.next_overrides[-1] if context.next_overrides else (None, [])
    assert "BF_Skipped" in last[1], f"候选耗尽应转 BF_Skipped，实际 {last}"


def test_target_recheck_error_does_not_blacklist_stage() -> None:

    class _BrokenContext(_FakeContext):
        def run_recognition_direct(self, *a: Any, **k: Any) -> Any:
            raise TypeError("signature mismatch")

    state = _planner_with([_material("110103", 1, ["13-10"])])
    _scanned_and_at_far_left(state)
    assert not balanced_fallback.StageLookupTimeout().run(_BrokenContext(), _FAKE_ARGV).success
    assert not state.failed_stages
    assert not unavailable_stages(TEST_UID)


@pytest.mark.parametrize(
    ("texts", "stage", "expected"),
    [
        (["13-10 Hard"], "13-10", True),
        (["13-10 Hard"], "13-13", False),
        (["010203"], "13-02", True),
        (["010203"], "13-20", False),
        (["192021"], "13-20", True),
        (["201"], "13-20", None),
        (["190221"], "13-02", None),
        (["201", "20"], "13-20", True),
    ],
)
def test_target_recheck_matches_stage_in_ocr_text(texts: list[str], stage: str, expected: bool | None) -> None:

    class _Ctx:
        tasker = types.SimpleNamespace(controller=types.SimpleNamespace(cached_image=object()))

        def run_recognition_direct(self, *a: Any, **k: Any) -> Any:
            box = [1, 2, 3, 4]
            return types.SimpleNamespace(
                hit=True,
                box=box,
                all_results=[types.SimpleNamespace(text=text, box=box) for text in texts],
                best_result=types.SimpleNamespace(text=texts[0], box=box, score=0.9),
            )

    assert balanced_fallback._target_visible_on_screen(_Ctx(), stage) is expected
