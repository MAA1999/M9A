"""切换账号任务：成功后把「当前逻辑账号」记下来。

## 为什么用 tasker sink 而不是自定义动作

需求：「默认当前账号 = 最近一次**已执行成功**的『切换账号』任务所切到的账号」。

「执行成功」这件事只有框架知道 —— 自定义动作成功不代表整条任务成功（后面的节点
还可能失败）。`TaskerEventSink.on_tasker_task` 正好给出任务级的
`NotificationType.Succeeded` / `Failed`，所以归属只在**任务真正成功**时才写。

## 归属标识从哪来（2026-11-08 改造）

**优先用游戏内真实 UID**，而不是 GUI 里手填的掩码账号文本。

原因：掩码文本只有前 3 位 + 后 4 位，游戏从不校验它，手工在游戏里换号后
仍会沿用旧账号的记录 —— 多账号场景下会串号。

UID 的来源是 `RecordID` 动作（`agent/custom/action/record_id.py`）：它在
`RecordId` 节点上用 OCR 读主页右上角的用户名与 ID，缓存在类变量里。
而 `SwitchAccount` 任务结尾会 `StartGame` → 走回家链（`HomeFlagCloseReturnMain`）
→ 到主界面时 `RecordId` 节点命中 → UID 被刷成**新账号**的值。

所以任务成功时读 `current_account()`（内部优先取 `RecordID.current_account_id()`）
拿到的就是刚切过去的那个账号。

兜底顺序：真实 UID → 状态文件里的旧值 → 固定默认标识。

## 状态文件

`config/balanced_state.json` 的 `current_account` 字段（见 `utils/balanced_state.py`）。
不同账号各自保留一套「关卡不可用记录 + 均衡停用标记」，切回之前继续用它那份记录。
"""

from __future__ import annotations

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink
from utils import logger
from utils.account_store import DEFAULT_ACCOUNT_KEY
from utils.balanced_state import (
    clear_account_unsaved,
    current_account,
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

        # 首选游戏内真实 UID：`SwitchAccount` 结尾的 StartGame → 回家链会让
        # `RecordId` 命中并把 UID 刷成新账号。
        uid = current_account()
        configured = pending_switch_target()

        if uid and uid != DEFAULT_ACCOUNT_KEY:
            target = uid
            logger.info(f"切换账号任务成功，读到游戏内 UID: {uid}（GUI 配置标识: {configured or '未填'}）")
        elif configured:
            # 读不到 UID 时退回 GUI 配置的标识 —— 比丢归属强，但会记一条警告，
            # 因为这种模式下手工换号可能串号。
            target = configured
            logger.warning(
                f"切换账号任务成功，但未能读到游戏内 UID，退回使用 GUI 配置标识 {configured}。"
                f"多账号场景下这个标识不会随手工换号变化，可能串号"
            )
        else:
            logger.info("切换账号任务成功，但未读到 UID 且未记录目标标识，逻辑账号归属保持不变")
            return

        if set_current_account(target):
            logger.info(f"当前逻辑账号记为 {target}")
            clear_account_unsaved()
        else:
            # 切换**已经成功**（游戏里是新账号），但归属没能落盘 —— 文件里还是旧账号。
            # 这种不一致比单纯「保存失败」危险：继续按旧归属读写会把新账号的关卡
            # 失败记录、停用标记写进旧账号的桶。置位后写操作会被拒绝。
            mark_account_unsaved(target)


__all__ = ["SwitchAccountAttribution"]

