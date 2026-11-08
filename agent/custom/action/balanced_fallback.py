"""均衡刷材料：选关超时后的两级顺延（同材料候选 → 第二少/第三少材料）。

## 这个模块负责什么

原「智能均衡刷材料」流程（仓库识别 → 选材 → 进关 → 点击 → 复现 → 收尾）**完全保留**。
本模块只在**选关阶段**加一条分支：当原流程寻找目标关卡**超时**时，

1. 记录该关卡为不可用（连带「编号更大的主线关卡」也算不可用）；
2. 顺延到**同一材料**的下一个候选关卡（数字 `(章节, 关卡)` 降序），重新走原选关流程；
3. 同材料候选全部不可用 → 换**库存数量第二少、第三少……**的材料，每种材料都套同一套规则；
4. 所有有效参与材料的候选都不可用 → 持久标记「跳过均衡刷材料任务」。

**不先跑一遍 Combat 做预探测** —— 超时判定发生在本来就要执行的选关流程里。

## 两级遍历

```text
外层：材料（库存数量从少到多）        ← 原版「均衡取最少」口径
  内层：同材料候选关卡（数字降序）    ← 原登记关卡优先
```

有限遍历：本轮已失败的材料不重复尝试，不会无限回到第一种材料重试。

## 触发点与框架机制

超时分支接在**原版扫描链**上（`resource/base/pipeline/combat.json`），不另写导航。

原版的扫描链是这样绕的：

```text
SwipeLeftAndFindStage（扫描头, max_hit=30）
  → TargetStageName（ColorOCR 找关卡编号）
  → SwipeRightForStageList（滑动尾节点, timeout=2000）
    → StageLookupBudget ← 本模块插入
      → SwipeRightAndFindStage（扫描头, max_hit=30）
        → TargetStageName → SwipeRightForStageList → …
```

- **尾节点的 `timeout: 2000`** —— 滑动后 2 秒没匹配到后继就报错收场，
  原版报的错就是「未在关卡列表中找到目标关卡」。**这本身就是「确实找不到」的精确信号**。
- **本模块给两个尾节点加 `on_error` → `StageLookupTimeout`** —— 把这条原版的失败出口
  导向顺延逻辑；没有均衡顺延在进行时，该动作按原版语义让任务失败（提示文案与原版一致）。
- **尾节点的 `next` 首位插入 `StageLookupBudget`** —— 寻找单个目标关卡的**总预算**检查。
  它是**自定义识别**：未超预算时不匹配（流程照常滑动），超预算时匹配 → 走
  `StageLookupTimeout`。两分钟是**整个寻找过程**的预算，不是给两个尾节点各设两分钟
  —— 尾节点的 `timeout` 仍是原来的 2000ms。

### ⚠️ `max_hit` 用不上（真机实测）

原版给扫描头设了 `max_hit: 30`，看着像「扫 30 次就停」，但**真机跑下来扫描头只命中
28 次**（滑动尾节点 29 次）—— 循环的最后一次里，尾节点命中了而扫描头因为还没到 30
被跳过。所以 `max_hit` 实际是个**永远碰不到的安全上限**，原版判「没找到」靠的是
尾节点的 2 秒 timeout。

结论：**「有没有真的扫过整章」不能看 `max_hit`**，只能自己数滑动次数 ——
`StageLookupBudget` 在扫描链上每滑动一次就被问一次，累加它就是实际滑动次数。

## 只有「寻找超时」才记不可用

`StageLookupTimeout` 里会先确认这次失败**确实是找关卡没找到**：

- 至少滑动过一次（`swipe_count > 0`）→ 确认扫过了，确认未解锁；
- 用户正在停止（`context.tasker.stopping`）→ 不记录；
- 一次都没滑动 → 不记录（不是「找不到」，是压根没找）。

战斗失败、体力不足、补体失败都发生在**找到关卡之后**，根本不会走到这个出口。

## 材料候选从哪来

候选只从原版已有的掉落索引 `data/combat/drop_index.json` 反查（`utils/balanced_state.py`），
不新增任何自造关卡表。原登记关卡优先，其余按数字 `(章节号, 关卡号)` 降序。

## 为什么不在这里做账号识别

账号归属按任务执行上下文确定（最近一次**执行成功**的切换账号任务；没有则固定默认标识），
见 `utils/balanced_state.py` 的模块文档。本模块只读取当前逻辑账号的记录。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.balanced_state import (
    StageCandidate,
    candidates_for_material,
    current_account,
    end_ephemeral_run,
    is_stage_unavailable,
    record_unavailable,
    set_task_skipped,
    unavailable_stages,
)
from utils.material_catalog import MaterialEntry
from utils.params import parse_params

# 寻找单个目标关卡的总预算（毫秒）。用户明确口径：寻找该关卡两分钟超时即判过不去。
# 依据：源码的 2 秒只是「扫描尾节点的单次等待」，不是整个寻找过程的预算。
LOOKUP_BUDGET_MS = 120_000

# pipeline 节点名
COMBAT_ENTRY_NODE = "Combat"
SELECT_STAGE_NODE = "SelectCombatStage"
TIMEOUT_NODE = "StageLookupTimeout"
SKIPPED_NODE = "BF_Skipped"
# 回主界面：原版共享的回家链（ResetReturnMain → ReturnMain）
HOME_ENTRY = "ResetReturnMain"


@dataclass
class MaterialCandidate:
    """一种参与本次均衡刷取的材料及其候选关卡。"""

    entry: MaterialEntry
    """材料目录里的登记信息（关卡、难度、每局掉落等）。"""

    count: int
    """仓库里的数量（决定「从少到多」的顺延顺序）。"""

    candidates: list[StageCandidate] = field(default_factory=list)
    """候选关卡：原登记关卡优先，其余按数字 `(章节, 关卡)` 降序。"""


def build_material_candidates(
    materials: Mapping[str, MaterialEntry],
    counts: Mapping[str, int],
) -> list[MaterialCandidate]:
    """按**库存数量从少到多**排出参与本次刷取的材料，并给每种材料备好候选关卡。

    - 数量相同按材料 id 排序，保证结果稳定（与原版 `BalancedFarmingAnalyze` 的
      `min(sorted(counts), key=...)` 同口径）；
    - 只收录有库存读数的材料（读数缺失的材料不参与，见需求「缺读数不等于关卡不可用」）。
    """
    ordered: list[MaterialCandidate] = []
    for item_id in sorted(counts, key=lambda key: (counts[key], key)):
        entry = materials.get(item_id)
        if entry is None:
            continue
        ordered.append(
            MaterialCandidate(
                entry=entry,
                count=counts[item_id],
                candidates=candidates_for_material(
                    item_id,
                    level=entry.level,
                    registered_stage=entry.stage.code,
                ),
            )
        )
    return ordered


def build_depot_material_candidates(
    catalog: Mapping[str, MaterialEntry],
    inventory: Mapping[str, int],
    targets: Mapping[str, int],
) -> list[MaterialCandidate]:
    """库存保持模式的参与材料：只收**有正缺口**的（不刷已达标材料）。

    顺序：先刷缺口最大的（库存保持的原语义），其余按**库存数量从少到多**排列，
    作为跨材料顺延顺序（「第二少、第三少」按库存数量，不按缺口大小）。
    """
    deficits: dict[str, int] = {}
    for item_id, target in targets.items():
        if target <= 0 or item_id not in catalog:
            continue
        count = inventory.get(item_id)
        if count is None:
            continue  # 没有读数 → 不参与（缺读数不等于关卡不可用）
        if count >= target:
            continue  # 已达标 → 不硬刷
        deficits[item_id] = target - count

    if not deficits:
        return []

    first = max(sorted(deficits), key=lambda key: deficits[key])
    rest = sorted((key for key in deficits if key != first), key=lambda key: (inventory[key], key))
    order = [first, *rest]

    return [
        MaterialCandidate(
            entry=catalog[item_id],
            count=inventory[item_id],
            candidates=candidates_for_material(
                item_id,
                level=catalog[item_id].level,
                registered_stage=catalog[item_id].stage.code,
            ),
        )
        for item_id in order
    ]


class BalancedFallback:
    """本轮均衡刷取的状态机：记录不可用关卡、两级顺延、判断是否要停用任务。

    状态放在实例上（一个任务一份），跨 pipeline 节点用模块级单例传递 ——
    与仓库其它自定义动作的写法一致（`depot_maintain._state`）。
    """

    def __init__(self) -> None:
        self.account_id: str = current_account()
        """当前逻辑账号（按任务执行上下文确定，不做真实账号识别）。"""

        self.active: bool = False
        """本轮是否处于「均衡顺延」状态。非均衡刷材料的流程不受影响。"""

        self.materials: list[MaterialCandidate] = []
        """参与本轮的材料：第 0 个是本次先刷的，其余按库存数量从少到多。"""

        self.current_index: int = 0
        """外层遍历位置。"""

        self.candidate_index: int = 0
        """内层遍历位置。"""

        self.failed_materials: set[str] = set()
        """本轮已确认「全部候选不可用」的材料，不重复尝试。"""

        self.current_stage: str = ""
        """当前正在寻找的关卡（超时时记录它）。"""

        self.lookup_started_at: float = 0.0
        """本次选关寻找的开始时刻（用于总预算）。"""

        self.swipe_count: int = 0
        """本次寻找已经滑动过多少次。

        由 `StageLookupBudget`（自定义识别）每次被询问时累加 —— 它在扫描链上
        每滑动一次就被问一次，所以这个计数就是**实际滑动次数**。

        为什么要自己数：MaaFW 的 `max_hit` 记在**扫描头**（`SwipeLeftAndFindStage`
        / `SwipeRightAndFindStage`）上，但实测扫描头只命中 28 次就停（滑动尾节点
        29 次），**永远达不到 max_hit=30** —— 原版判「没找到」靠的是尾节点的
        `timeout: 2000`（2 秒没命中后继），不是 max_hit。所以「扫描是否真的跑过
        一遍」只能靠自己数滑动次数。
        """

    # ---------------------------------------------------------------- 生命周期
    def reset(self) -> None:
        """任务入口重置（每个任务各自一份）。"""
        self.account_id = current_account()
        self.active = False
        self.materials = []
        self.current_index = 0
        self.candidate_index = 0
        self.failed_materials = set()
        self.current_stage = ""
        self.lookup_started_at = 0.0
        self.swipe_count = 0

    def begin(
        self,
        materials: Sequence[MaterialCandidate],
        *,
        account_id: str | None = None,
    ) -> None:
        """开始本轮遍历。

        `materials[0]` 是本次先刷的材料（默认均衡 = 库存最少；库存保持 = 缺口最大），
        其余按库存数量从少到多排列，作为跨材料顺延顺序。
        """
        if account_id is not None:
            self.account_id = account_id
        self.materials = list(materials)
        self.current_index = 0
        self.candidate_index = 0
        self.failed_materials = set()
        self.active = True
        self.current_stage = ""
        self.lookup_started_at = 0.0
        self.swipe_count = 0

    def begin_stage_lookup(self, stage: str) -> None:
        """开始寻找某个关卡（记下起点与滑动计数，用于总预算与「是否真的扫过」判定）。"""
        self.current_stage = stage
        self.lookup_started_at = time.monotonic()
        self.swipe_count = 0

    def note_swipe(self) -> None:
        """记录又滑动了一次（由 `StageLookupBudget` 每次被询问时调用）。"""
        self.swipe_count += 1

    def budget_exceeded(self) -> bool:
        """寻找单个目标关卡是否超过总预算。"""
        if self.lookup_started_at <= 0:
            return False
        return (time.monotonic() - self.lookup_started_at) * 1000 >= self.lookup_budget_ms

    @property
    def lookup_budget_ms(self) -> int:
        """本次寻找的总预算（毫秒）。"""
        return LOOKUP_BUDGET_MS

    # ---------------------------------------------------------------- 遍历
    def current_material(self) -> MaterialCandidate | None:
        """当前正在尝试的材料。"""
        if self.current_index >= len(self.materials):
            return None
        return self.materials[self.current_index]

    def next_candidate(self) -> StageCandidate | None:
        """当前材料的下一个**尚可尝试**的候选关卡。

        跳过两类候选：
        - 已被记录为不可用的（连同编号更大的主线关卡）；
        - 本轮已经试过并失败的（同一候选不重复试）。

        返回 None 表示当前材料的候选已经用尽。
        """
        material = self.current_material()
        if material is None:
            return None
        known = unavailable_stages(self.account_id)
        while self.candidate_index < len(material.candidates):
            candidate = material.candidates[self.candidate_index]
            self.candidate_index += 1
            if is_stage_unavailable(known, candidate.stage):
                logger.info(f"{material.entry.name}：关卡 {candidate.stage} 已在不可用清单里，顺延到下一个候选")
                continue
            return candidate
        return None

    def next_available_candidate(self) -> StageCandidate | None:
        """取下一个可用候选关卡，**自动跨材料顺延**（外层遍历）。

        与 `next_candidate()` 的区别：后者只看**当前材料**，用尽就返回 `None`；
        这里在当前材料用尽时自动 `finish_material()` 换下一种材料继续找。

        返回 `None` 才表示**所有参与材料**的候选都确认不可用 —— 只有这种兜底情况
        才允许停用整个任务（需求 §5：「单个材料刷不了，不能停用整个均衡任务」）。

        外层顺序由 `begin()` 传入的 `materials` 决定（库存数量从少到多）。
        本轮已失败的材料不会重复尝试：`current_index` 只增不减。
        """
        while True:
            candidate = self.next_candidate()
            if candidate is not None:
                return candidate
            if self.all_materials_unavailable():
                return None
            # 当前材料用尽 → 记为本轮失败，换下一种材料继续
            material = self.current_material()
            if material is not None:
                logger.info(f"{material.entry.name} 的候选关卡全部不可用，顺延到下一种材料")
            self.finish_material()

    def mark_unavailable(self, stage: str) -> bool:
        """记录「这个关卡找不到（寻找超时）」，连带更大的主线关卡视为不可用。

        返回是否真的落盘成功。**保存失败时调用方必须如实提示，不得宣称已持久化。**
        """
        saved = record_unavailable(self.account_id, stage)
        if not saved:
            logger.error(f"关卡不可用记录保存失败：{stage}（本次运行内仍然生效，但下次运行不会记得）")
        return saved

    def finish_material(self) -> None:
        """当前材料的候选已全部不可用 → 标记本轮失败，移到下一种材料。"""
        material = self.current_material()
        if material is not None:
            self.failed_materials.add(material.entry.item_id)
        self.current_index += 1
        self.candidate_index = 0
        self.current_stage = ""

    def all_materials_unavailable(self) -> bool:
        """所有有效参与材料的候选都确认不可用了吗？

        「有效参与材料」= 本轮材料列表里的那些材料。**缺读数的材料根本不在列表里**，
        不参与这个判断；「全部达标」是原流程的收尾分支，也不会走到这里。
        """
        return self.current_index >= len(self.materials)

    def failed_names(self) -> str:
        """收尾时用的失败材料摘要。"""
        names = [
            material.entry.name
            for material in self.materials
            if material.entry.item_id in self.failed_materials
        ]
        return "、".join(names)

    def persist_skip_flag(self) -> bool:
        """持久标记「跳过均衡刷材料任务」。返回是否真的落盘成功。"""
        saved = set_task_skipped(self.account_id, True)
        if not saved:
            logger.error("「跳过均衡刷材料任务」标记保存失败，下次运行不会自动跳过")
        return saved


# 模块级单例：一个任务一份，跨 pipeline 节点共享
_planner = BalancedFallback()


def planner() -> BalancedFallback:
    """取本轮的顺延状态机。"""
    return _planner


def reset_planner() -> None:
    """任务入口重置顺延状态。"""
    _planner.reset()


def finish_planner() -> None:
    """任务收尾清理顺延状态。

    ⚠️ 必须调用：`_planner` 是模块级单例，跨任务存活。若均衡任务异常结束
    （用户停止、其它节点失败）而没有清理，`active` 会一直为 True，
    之后同 agent 进程里其它任务（如常规作战）的 `StageLookupBudget` 识别
    仍会介入 —即使它们自己完全用不到顺延。
    """
    _planner.active = False
    _planner.current_stage = ""
    _planner.lookup_started_at = 0.0
    _planner.swipe_count = 0


@AgentServer.custom_action("StageLookupTimeout")
class StageLookupTimeout(CustomAction):
    """寻找目标关卡超时 → 记录不可用 → 顺延到下一个候选（无候选则收尾）。

    ## 两条触发路径

    1. **扫描尾节点的 `on_error`** —— 原版判定的「未在关卡列表中找到目标关卡」。
       原版就是靠这个出口报错的（尾节点 2 秒没匹配到后继 → 报错收场），
       所以这条路径**本身就是「确实找不到」的精确信号**，直接顺延。
    2. **`StageLookupBudget` 命中**（`next` 指向本节点）—— 两分钟总预算到。
       这条是本改造新加的出口，需要额外确认扫描确实在进行中。

    ## 为什么第 2 条要额外确认

    预算到期只说明「花了两分钟」，不说明「扫过整章都没找到」——
    也可能是滑动动作本身失败、页面卡住等别的原因。
    所以要求**至少滑动过一次**（`swipe_count > 0`），否则不记录关卡不可用。

    ## 其它

    - 没有均衡顺延在进行（其它任务）：按原版语义让任务失败，提示文案与原版一致；
    - 候选取尽（所有参与材料都不可用）：持久标记「跳过均衡刷材料任务」并结束本任务。
    """
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        parse_params(argv.custom_action_param)
        state = planner()

        if not state.active:
            # 原版行为：任务失败，提示与原版 focus 文案一致
            logger.error("未在关卡列表中找到目标关卡，请检查关卡配置")
            return CustomAction.RunResult(success=False)

        if context.tasker.stopping:
            logger.warning("任务正在停止，不记录关卡不可用")
            return CustomAction.RunResult(success=False)

        if state.swipe_count <= 0:
            # 一次都没滑动过 → 不是「扫过整章都没找到」，不能当成关卡未解锁
            logger.warning("关卡列表扫描未开始（不是「找不到目标关卡」），不记录关卡不可用")
            return CustomAction.RunResult(success=False)

        stage = state.current_stage
        if stage:
            logger.warning(f"关卡 {stage} 找不到（已滑动 {state.swipe_count} 次），标记为不可用并顺延")
            state.mark_unavailable(stage)

        # 取下一个可用候选，**自动跨材料连续顺延**：当前材料用尽就换下一种，
        # 一直找到可用的或所有参与材料都耗尽。
        # ⚠️ 不能写成「next_candidate() + finish_material() + next_candidate()」——
        # 那样只换一次材料，第二种材料的候选若也被记录过就直接走停用分支，
        # 违背「继续顺延第二少、第三少……」的要求。
        candidate = state.next_available_candidate()

        if candidate is None:
            # 所有有效参与材料的候选都确认不可用 → 停用本任务
            names = state.failed_names()
            if state.persist_skip_flag():
                logger.warning(
                    f"所有参与材料的候选关卡都不可用（{names}），"
                    f"已标记「跳过均衡刷材料任务」，下次运行直接跳过"
                )
            else:
                logger.error(
                    f"所有参与材料的候选关卡都不可用（{names}），"
                    f"但停用标记保存失败，下次运行不会自动跳过"
                )
            # 回主界面：此刻游戏停在**关卡列表页**（本动作正是从扫描链的失败出口进来的），
            # 而 BF_Skipped 按约定不导航。不先回家的话任务结束时游戏留在关卡页，
            # 后续任务会从错误界面开始。与下方顺延分支、balanced_farming.py 的
            # 跳过分支保持同一做法。
            detail = context.run_task(HOME_ENTRY)
            if detail is None or detail.status.failed:
                logger.warning("跳过均衡任务前未能回到主界面，请检查游戏当前界面")
            context.override_next(TIMEOUT_NODE, [SKIPPED_NODE])
            return CustomAction.RunResult(success=True)

        material = state.current_material()
        label = material.entry.name if material else candidate.stage
        logger.info(f"{label} 顺延到关卡 {candidate.stage} {candidate.level}")

        # 库存保持模式下，跨材料顺延必须同步 depot 的「本轮目标材料」。
        # 不然 `_state.item_id` 还是旧材料：`DepotMaintainAccumulate` 会按旧 id
        # 找掉落，新关卡的掉落统计不到、快照也不更新，等于白刷。
        # 延迟导入避免与 depot_maintain 的循环依赖（它已经 import 了本模块）。
        if material is not None:
            from .depot_maintain import retarget_material

            synced = retarget_material(context, material.entry.item_id, candidate.stage, candidate.level)
            if synced is False:
                # 库存保持模式下同步失败：`_state` 仍是旧材料，继续刷会把掉落记到
                # 旧材料头上。宁可结束本任务也不要刷错。
                logger.error(
                    "库存保持目标切换失败，无法把掉落记到材料 "
                    f"{material.entry.name}，结束本次均衡刷材料"
                )
                detail = context.run_task(HOME_ENTRY)
                if detail is None or detail.status.failed:
                    logger.warning("结束前未能回到主界面，请检查游戏当前界面")
                context.override_next(TIMEOUT_NODE, [])
                return CustomAction.RunResult(success=False)

        # 回主界面：原导航依赖主界面的「进入」按钮，停在关卡页时它认不出来
        detail = context.run_task(HOME_ENTRY)
        if detail is None or detail.status.failed:
            logger.warning("顺延到下一候选前未能回到主界面")

        # 只改 stage / level 两个字段。
        # ⚠️ MaaFW 的覆盖对 `attach` 是**叠加合并**、对**末端键**整体替换
        # （见 docs/zh_cn/develop/depot-catalog.md）：这里的 attach 只有一个末端键
        # `level`，所以它整体替换；`depot_accumulate` 挂在同一个 attach 的**另一个**
        # 键上，合并后仍然保留（库存保持的掉落累计不会因为顺延而失效）。
        context.override_pipeline(
            {
                SELECT_STAGE_NODE: {
                    "action": {"param": {"custom_action_param": {"stage": candidate.stage}}},
                    "attach": {"level": candidate.level},
                }
            }
        )
        state.begin_stage_lookup(candidate.stage)
        # 回到原选关流程：原版的 Combat → SelectCombatStage → 进卷 → 扫关卡列表
        context.override_next(TIMEOUT_NODE, [COMBAT_ENTRY_NODE])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("BalancedTaskSkip")
class BalancedTaskSkip(CustomAction):
    """均衡刷材料任务被跳过时的收尾：说明原因。

    任务在入口就被判定为「已停用」时走这里 —— 此时游戏还没被导航过，
    **不导航、不点选关卡**，直接结束本任务让后续任务继续。
    """
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        parse_params(argv.custom_action_param)
        # 收尾清理：本任务结束时关掉顺延状态，避免影响同一 agent 进程里的后续任务
        finish_planner()
        end_ephemeral_run()
        logger.info("均衡刷材料任务已按标记跳过（所有参与材料的候选关卡此前都不可用）")
        return CustomAction.RunResult(success=True)
