"""均衡刷材料：任务结束时清理模块级顺延状态。

## 为什么需要它

`balanced_fallback._planner` 是**模块级单例**，跨任务存活。它的 `active` 一旦为
`True`、`lookup_started_at` 一旦是旧的，同一 agent 进程里**后续任务**的
`StageLookupBudget` 识别就会误命中：把本来能进的关卡判成超时，进而写进
「关卡不可用」记录、把选关改道。

之前的做法只在两处清理：

- `DepotMaintainDone`（库存保持收尾）
- `BalancedTaskSkip`（跳过任务收尾）

但**默认均衡分支**（`BF_Analyze` → `Combat` → `AllIn` → `TargetCountFinish`）
根本不经过这两个节点 —— 那条路径在作战结束后直接以 `TargetCountFinish` 收尾，
planner 就一直是 `active=True` 留在内存里。

## 为什么用 sink 而不是改 combat.py

`TargetCountFinish` / `TargetCountAbort` 在 `combat.py`，是**所有作战任务共用**的
原版节点。为了均衡刷材料的状态清理去改它，会把改动扩散到无关任务。
`TaskerEventSink.on_tasker_task` 能直接拿到**任务级**的
`Succeeded` / `Failed`，在这里按任务名判断即可，零侵入。
"""

from __future__ import annotations

import sys
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink
from utils import logger

# 均衡刷材料任务的 entry 名（tasks/BalancedFarming.json）
BALANCED_FARMING_ENTRY = "BalancedFarming"


def _planner() -> Any:
    """取顺延状态机。

    `agent.custom.*` 与 `custom.*` 是两张模块图（同一份源码、两个模块对象）。
    直接 `from custom.action.balanced_fallback import planner` 会**再导入一次**
    那个模块，触发 `@AgentServer.custom_action` 的重复注册并抛
    `Custom name is already registered`。

    所以优先从 `sys.modules` 拿已加载的那份；确实还没加载时才延迟导入。
    """
    for name in ("custom.action.balanced_fallback", "agent.custom.action.balanced_fallback"):
        module = sys.modules.get(name)
        if module is not None:
            return module.planner()
    from custom.action.balanced_fallback import planner as _p

    return _p()


def _end_ephemeral() -> None:
    """关掉「本轮不落盘」模式。

    同样要避开两张模块图：状态存在 `builtins` 上的进程级容器里，两边共享同一份，
    所以这里直接调任一侧已加载的模块即可。
    """
    for name in ("custom.utils.balanced_state", "agent.utils.balanced_state", "utils.balanced_state"):
        module = sys.modules.get(name)
        if module is None:
            continue
        end = getattr(module, "end_ephemeral_run", None)
        if callable(end):
            end()
            return


@AgentServer.tasker_sink()
class BalancedStateCleanup(TaskerEventSink):
    """均衡刷材料任务结束（成功或失败）时，清掉模块级顺延状态。"""

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: NotificationType,
        detail: TaskerEventSink.TaskerTaskDetail,
    ):
        if detail.entry != BALANCED_FARMING_ENTRY:
            return
        if noti_type not in (NotificationType.Succeeded, NotificationType.Failed):
            return

        # 无论本轮是否进入过顺延，都要关掉「不落盘」模式 ——
        # 否则同进程里后续的均衡任务会一直被当成 ephemeral，记录永远存不下来。
        _end_ephemeral()

        state = _planner()
        if not state.active:
            return

        # 不清 materials / 记录，只关掉「本轮正在顺延」这个运行期标志 ——
        # 持久记录（不可用关卡、跳过标记）已经落盘，不该被清理。
        state.active = False
        state.current_stage = ""
        state.lookup_started_at = 0.0
        state.swipe_count = 0
        logger.debug(f"均衡刷材料任务结束（{noti_type.name}），已清理顺延状态")


__all__ = ["BalancedStateCleanup"]
