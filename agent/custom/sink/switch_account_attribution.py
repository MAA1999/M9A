"""切换账号任务：成功后把「当前逻辑账号」记下来。

## 为什么用 tasker sink 而不是自定义动作

需求：「默认当前账号 = 最近一次**已执行成功**的『切换账号』任务所切到的账号」。

「执行成功」这件事只有框架知道 —— 自定义动作成功不代表整条任务成功（后面的节点
还可能失败）。`TaskerEventSink.on_tasker_task` 正好给出任务级的
`NotificationType.Succeeded` / `Failed`，所以归属只在**任务真正成功**时才写。

## 归属标识从哪来

用**切换任务的目标配置标识**（GUI 的「目标账号(可选)」输入），**不识别真实 UID**：

- GUI 填了账号 → 用它（规范化后）；
- GUI 没填 → 用一个固定默认标识（表示「账号列表里选中的那个」）；
- 任务失败 → **不写**，归属保持不变（未执行或切换失败都不能提前改变归属）。

## 状态文件

`config/balanced_state.json` 的 `current_account` 字段（见 `utils/balanced_state.py`）。
不同切换目标各自保留一套「关卡不可用记录 + 均衡停用标记」，
切回之前的目标继续用它那份记录。
"""

from __future__ import annotations

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink
from utils import logger
from utils.balanced_state import (
    clear_account_unsaved,
    mark_account_unsaved,
    pending_switch_target,
    set_current_account,
)

# 切换账号任务的 entry 名（tasks/SwitchAccount.json 的 entry）
SWITCH_ACCOUNT_ENTRY = "SwitchAccount"


@AgentServer.tasker_sink()
class SwitchAccountAttribution(TaskerEventSink):
    """「切换账号」任务成功后，把当前逻辑账号记到状态文件里。

    任务失败或还没执行时**不写**：归属不能提前改变。
    """

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: NotificationType,
        detail: TaskerEventSink.TaskerTaskDetail,
    ):
        if detail.entry != SWITCH_ACCOUNT_ENTRY:
            return

        if noti_type == NotificationType.Failed:
            logger.info("切换账号任务失败，当前逻辑账号归属保持不变")
            return
        if noti_type != NotificationType.Succeeded:
            return

        target = pending_switch_target()
        if not target:
            logger.info("切换账号任务成功，但未记录目标账号标识，逻辑账号归属保持不变")
            return

        if set_current_account(target):
            logger.info(f"切换账号任务成功，当前逻辑账号记为 {target}")
            clear_account_unsaved()
        else:
            # 切换**已经成功**（游戏里是新账号），但归属没能落盘 —— 文件里还是旧账号。
            # 这种不一致比单纯「保存失败」危险：继续按旧归属读写会把新账号的关卡
            # 失败记录、停用标记写进旧账号的桶。置位后写操作会被拒绝。
            mark_account_unsaved(target)


__all__ = ["SwitchAccountAttribution"]
