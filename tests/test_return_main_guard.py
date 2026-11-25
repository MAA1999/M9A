from types import SimpleNamespace
from unittest.mock import Mock

import numpy
import pytest
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType
from maa.pipeline import JActionType, JStopTask

from agent.custom.sink import return_main_guard
from agent.custom.sink.return_main_guard import ReturnMainGuard


def _node(name: str, task_id: int, parent: int | None = None) -> ContextEventSink.NodePipelineNodeDetail:
    return ContextEventSink.NodePipelineNodeDetail(task_id, 1, name, None, parent_task_id=parent)


@pytest.fixture
def guard_context() -> Context:
    context = Mock(spec=Context)
    context.get_task_job.return_value.job_id = 10
    return context


def _arm(guard: ReturnMainGuard, context: Context) -> None:
    guard.on_node_pipeline_node(context, NotificationType.Failed, _node("ReturnMain", 10))


def test_still_broken_skips_each_later_root_until_disarmed(
    monkeypatch: pytest.MonkeyPatch, guard_context: Context
) -> None:
    monkeypatch.setattr(return_main_guard, "_screen_recovered", lambda ctx: False)
    guard = ReturnMainGuard()
    _arm(guard, guard_context)

    # 武装任务自身与子流程不受影响，也不会触发探测
    guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("BF_Plan", 10))
    guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("ResetReturnMain", 32, 10))
    guard_context.run_action_direct.assert_not_called()

    for task_id in [11, 12]:
        guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("Awards", task_id))
    assert guard_context.run_action_direct.call_count == 2
    guard_context.run_action_direct.assert_called_with(JActionType.StopTask, JStopTask())


def test_recovered_lets_task_run_and_disarms(monkeypatch: pytest.MonkeyPatch, guard_context: Context) -> None:
    monkeypatch.setattr(return_main_guard, "_screen_recovered", lambda ctx: True)
    guard = ReturnMainGuard()
    _arm(guard, guard_context)

    guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("Awards", 11))
    guard_context.run_action_direct.assert_not_called()

    # 解除后后续任务不再探测、也不跳过
    guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("Awards", 12))
    guard_context.run_action_direct.assert_not_called()
    assert guard.failed_task_id is None


def test_probe_failure_is_conservative(monkeypatch: pytest.MonkeyPatch, guard_context: Context) -> None:
    # _screen_recovered 内部已把任何异常收敛成 False，这里直接验证它就返回 False
    context = Mock()
    context.get_node_data.return_value = {"next": [{"name": "HomeFlagCloseReturnMain"}]}
    context.tasker.controller.post_screencap.return_value.wait.return_value.get.side_effect = RuntimeError("boom")

    assert return_main_guard._screen_recovered(context) is False
    context.run_recognition.assert_not_called()


def test_probe_without_candidates_is_not_recovered() -> None:
    context = Mock()
    context.get_node_data.return_value = {"next": []}

    assert return_main_guard._screen_recovered(context) is False


def test_probe_hit_resolves_named_candidates() -> None:
    context = Mock()
    context.get_node_data.return_value = {
        "next": [{"name": "Confirm", "jump_back": True}, {"name": "HomeFlagCloseReturnMain"}]
    }
    image = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    context.tasker.controller.post_screencap.return_value.wait.return_value.get.return_value = image
    context.run_recognition.return_value = SimpleNamespace(hit=True)

    assert return_main_guard._screen_recovered(context) is True

    entry, called_image, override = context.run_recognition.call_args[0]
    assert entry == return_main_guard.PROBE_NODE
    assert called_image is image
    assert override[return_main_guard.PROBE_NODE]["recognition"] == {
        "type": "Or",
        "param": {"any_of": ["Confirm", "HomeFlagCloseReturnMain"]},
    }


def test_probe_miss_returns_not_recovered() -> None:
    context = Mock()
    context.get_node_data.return_value = {"next": [{"name": "Confirm"}]}
    image = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    context.tasker.controller.post_screencap.return_value.wait.return_value.get.return_value = image
    context.run_recognition.return_value = SimpleNamespace(hit=False)

    assert return_main_guard._screen_recovered(context) is False


def test_ordinary_failure_and_cancelled_return_main_do_not_block_tasks() -> None:
    guard = ReturnMainGuard()
    context = Mock(spec=Context)
    guard.on_node_pipeline_node(context, NotificationType.Failed, _node("Awards", 1))
    guard.on_node_pipeline_node(context, NotificationType.Cancelled, _node("ReturnMain", 1))
    guard.on_node_pipeline_node(context, NotificationType.Starting, _node("Awards", 2))
    context.run_action_direct.assert_not_called()
