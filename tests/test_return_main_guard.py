from unittest.mock import Mock

import pytest
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType
from maa.pipeline import JActionType, JStopTask

from agent.custom.sink.return_main_guard import ReturnMainGuard


def _node(name: str, task_id: int, parent: int | None = None) -> ContextEventSink.NodePipelineNodeDetail:
    return ContextEventSink.NodePipelineNodeDetail(task_id, 1, name, None, parent_task_id=parent)


@pytest.mark.parametrize("parent", [None, 30])
def test_return_main_failure_skips_later_roots_until_a_new_agent(parent: int | None) -> None:
    guard = ReturnMainGuard()
    context = Mock(spec=Context)
    context.get_task_job.return_value.job_id = 10
    failed = _node("ReturnMain", 31 if parent else 10, parent)
    guard.on_node_pipeline_node(context, NotificationType.Failed, failed)

    for node in [_node("BF_Plan", 10), _node("ResetReturnMain", 32, 10)]:
        guard.on_node_pipeline_node(context, NotificationType.Starting, node)
    context.run_action_direct.assert_not_called()

    for task_id in [11, 12]:
        guard.on_node_pipeline_node(context, NotificationType.Starting, _node("Awards", task_id))
    assert context.run_action_direct.call_count == 2
    context.run_action_direct.assert_called_with(JActionType.StopTask, JStopTask())

    context.reset_mock()
    ReturnMainGuard().on_node_pipeline_node(context, NotificationType.Starting, _node("Awards", 13))
    context.run_action_direct.assert_not_called()


def test_ordinary_failure_and_cancelled_return_main_do_not_block_tasks() -> None:
    guard = ReturnMainGuard()
    context = Mock(spec=Context)
    guard.on_node_pipeline_node(context, NotificationType.Failed, _node("Awards", 1))
    guard.on_node_pipeline_node(context, NotificationType.Cancelled, _node("ReturnMain", 1))
    guard.on_node_pipeline_node(context, NotificationType.Starting, _node("Awards", 2))
    context.run_action_direct.assert_not_called()
