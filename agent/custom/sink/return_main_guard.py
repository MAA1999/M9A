"""回主界面失败后，本次 Agent 会话的后续任务在入口结束。"""

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType
from maa.pipeline import JActionType, JStopTask
from utils.logger import logger


@AgentServer.context_sink()
class ReturnMainGuard(ContextEventSink):
    def __init__(self) -> None:
        self.failed_task_id: int | None = None

    def on_node_pipeline_node(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodePipelineNodeDetail,
    ) -> None:
        if self.failed_task_id is None:
            if noti_type == NotificationType.Failed and detail.name == "ReturnMain":
                # run_task 的子流程有独立的事件 ID，Context 保留最外层任务号。
                self.failed_task_id = context.get_task_job().job_id
                logger.warning("回主界面失败，本次连接的后续任务将跳过")
            return

        if (
            noti_type == NotificationType.Starting
            and not detail.parent_task_id
            and detail.task_id != self.failed_task_id
        ):
            logger.info(f"跳过任务 {detail.name} (task_id={detail.task_id})")
            result = context.run_action_direct(JActionType.StopTask, JStopTask())
            if result is None or not result.success:
                logger.error(f"任务入口停止失败 (task_id={detail.task_id})")
