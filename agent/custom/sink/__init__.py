from maa.agent.agent_server import AgentServer

from maa.resource import ResourceEventSink
from maa.controller import ControllerEventSink
from maa.tasker import TaskerEventSink
from maa.context import Context, ContextEventSink

from utils import logger


@AgentServer.tasker_sink()
class MyTaskerSink(TaskerEventSink):
    def on_raw_notification(self, tasker, msg: str, details: dict):
        logger.debug(f"tasker: {tasker}, msg: {msg}, details: {details} ")
        if (
            msg == "Node.PipelineNode.Starting"
            and details.get("entry") == "MaaNS::Tasker::post_stop"
        ):
            logger.debug("任务即将停止，可以在这里执行清理操作")
            # tasker.post_stop()
