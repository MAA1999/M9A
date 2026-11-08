"""均衡刷材料：任务入口的「显式重置」与「停用检查」。

## 顺序要求（用户明确指定）

任务入口**先处理 GUI 显式重置，再检查当前逻辑账号是否已停用均衡任务**：

1. 先重置 → 即使当前账号已被标记停用，重置也照样能执行并清除停用标记；
2. 再检查停用 → 已停用就直接跳过本任务，**不再导航、不点选关卡**。

反过来就做不到「已停用时仍能执行重置」。

## 重置清什么

「重置」清**所有逻辑账号**的：

- 关卡不可用记录（`unavailable`）
- 均衡停用标记（`skip_balanced`）

两样一起清 —— 只清一个会让「记录还在但任务不跳」或「任务不跳但记录还在」这种半吊子状态出现。

**当前逻辑账号标识保留**：它不是「记录」，只是「现在该用哪一份状态」的归属。
"""

from __future__ import annotations

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.balanced_state import (
    clear_all,
    current_account,
    is_task_skipped,
    set_task_skipped,
)
from utils.params import parse_params

# pipeline 节点名
ENTRY_NODE = "BF_Entry"
RESET_NODE = "BF_ResetRecords"
SKIPPED_NODE = "BF_Skipped"
PLAN_NODE = "BF_Plan"


def _bool_param(value: object, default: bool = False) -> bool:
    """把 GUI 传下来的开关值解析成布尔（true/false/"true"/"1" 都认）。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@AgentServer.custom_action("BalancedResetRecords")
class BalancedResetRecords(CustomAction):
    """按 GUI「重置全部记录」选项清空所有逻辑账号的关卡不可用记录与均衡停用标记。

    参数格式：
    {
        "reset_stage_records": true   # 为真才清空；缺省不清
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        params = parse_params(argv.custom_action_param)
        if not _bool_param(params.get("reset_stage_records")):
            logger.debug("未勾选「重置全部记录」，保留已有的关卡记录与停用标记")
            context.override_next(RESET_NODE, [ENTRY_NODE])
            return CustomAction.RunResult(success=True)

        if clear_all():
            logger.info("已清空所有逻辑账号的关卡不可用记录与均衡停用标记")
        else:
            logger.error("清空关卡记录失败（文件不可写），记录与停用标记保持原样")
        context.override_next(RESET_NODE, [ENTRY_NODE])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("BalancedTaskEntry")
class BalancedTaskEntry(CustomAction):
    """均衡刷材料入口：检查当前逻辑账号是否已被标记停用。

    - 未停用 → 放行，继续后面的任务流程（选材、选关、作战）；
    - 已停用 → 直接跳过本任务（`BF_Skipped`），**不再导航、不点选关卡**，
      后续任务继续执行。

    停用标记只在「所有有效参与材料的候选关卡都确认不可用」时写入，
    且**一旦写入就一直生效** —— 后续运行、重启、跨天、重新调度都继续跳过，
    直到用户在 GUI 里显式重置。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        parse_params(argv.custom_action_param)
        account_id = current_account()

        if not is_task_skipped(account_id):
            context.override_next(ENTRY_NODE, [PLAN_NODE])
            return CustomAction.RunResult(success=True)

        logger.info(
            f"逻辑账号 {account_id} 已被标记「跳过均衡刷材料任务」（此前所有参与材料的候选关卡都不可用），"
            f"本次直接跳过"
        )
        context.override_next(ENTRY_NODE, [SKIPPED_NODE])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("BalancedTaskUnskip")
class BalancedTaskUnskip(CustomAction):
    """清除「跳过均衡刷材料任务」标记（供将来单独的解除入口用）。

    正常路径不需要它 —— GUI 的「重置全部记录」已经同时清记录与停用标记。
    保留这个动作是为了「只想解除停用、保留关卡记录」这种将来可能的需求。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        parse_params(argv.custom_action_param)
        account_id = current_account()
        if set_task_skipped(account_id, False):
            logger.info(f"已清除逻辑账号 {account_id} 的「跳过均衡刷材料任务」标记")
        else:
            logger.error("清除停用标记失败（文件不可写）")
        context.override_next(ENTRY_NODE, [PLAN_NODE])
        return CustomAction.RunResult(success=True)
