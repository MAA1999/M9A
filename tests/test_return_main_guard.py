from types import SimpleNamespace
from typing import Any
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


def _context(node_map: dict[str, Any], failed_job_id: int = 10) -> Context:
    """按节点名返回 node_data 的假 Context；未登记的节点返回 None。"""
    context = Mock(spec=Context)
    context.get_task_job.return_value.job_id = failed_job_id
    context.get_node_data.side_effect = lambda name: node_map.get(name)
    return context


def _tm() -> dict[str, Any]:
    return {"recognition": {"type": "TemplateMatch"}}


@pytest.fixture
def guard_context() -> Context:
    return _context({"ReturnMain": {"next": [{"name": "HomeFlagCloseReturnMain"}]}, "HomeFlagCloseReturnMain": _tm()})


def _arm(guard: ReturnMainGuard, context: Context) -> None:
    guard.on_node_pipeline_node(context, NotificationType.Failed, _node("ReturnMain", 10))


def test_still_broken_skips_each_later_root_until_disarmed(
    monkeypatch: pytest.MonkeyPatch, guard_context: Context
) -> None:
    monkeypatch.setattr(return_main_guard, "_screen_recovered", lambda ctx: False)
    guard = ReturnMainGuard()
    _arm(guard, guard_context)

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

    guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("Awards", 12))
    guard_context.run_action_direct.assert_not_called()
    assert guard.failed_task_id is None


def test_probe_failure_is_conservative() -> None:
    context = _context({"ReturnMain": {"next": [{"name": "Confirm"}]}, "Confirm": _tm()})
    context.tasker.controller.post_screencap.return_value.wait.return_value.get.side_effect = RuntimeError("boom")

    assert return_main_guard._screen_recovered(context) is False
    context.run_recognition.assert_not_called()


def test_probe_without_candidates_is_not_recovered() -> None:
    context = _context({"ReturnMain": {"next": []}})
    assert return_main_guard._screen_recovered(context) is False


def test_probe_hit_resolves_named_candidates() -> None:
    context = _context(
        {
            "ReturnMain": {"next": [{"name": "Confirm", "jump_back": True}, {"name": "HomeFlagCloseReturnMain"}]},
            "Confirm": _tm(),
            "HomeFlagCloseReturnMain": _tm(),
        }
    )
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
    context = _context({"ReturnMain": {"next": [{"name": "Confirm"}]}, "Confirm": _tm()})
    image = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    context.tasker.controller.post_screencap.return_value.wait.return_value.get.return_value = image
    context.run_recognition.return_value = SimpleNamespace(hit=False)

    assert return_main_guard._screen_recovered(context) is False


def test_directhit_candidates_are_excluded() -> None:
    # DirectHit 会让 Or 恒命中；含 DirectHit 的 Or 子树、以及缺省识别（默认 DirectHit）都要剔除
    context = _context(
        {
            "ReturnMain": {
                "next": [
                    {"name": "DhNode"},
                    {"name": "OrWithDh"},
                    {"name": "DefaultReco"},
                    {"name": "RealTemplate"},
                ]
            },
            "DhNode": {"recognition": {"type": "DirectHit"}},
            "OrWithDh": {"recognition": {"type": "Or", "param": {"any_of": ["DhNode"]}}},
            "DefaultReco": {},  # 无 recognition ⇒ 默认 DirectHit
            "RealTemplate": _tm(),
        }
    )

    assert return_main_guard._probe_candidates(context) == ["RealTemplate"]


def test_only_directhit_candidates_leaves_probe_not_recovered() -> None:
    context = _context(
        {
            "ReturnMain": {"next": [{"name": "DhNode"}]},
            "DhNode": {"recognition": {"type": "DirectHit"}},
        }
    )
    assert return_main_guard._probe_candidates(context) == []
    assert return_main_guard._screen_recovered(context) is False


def test_ordinary_failure_and_cancelled_return_main_do_not_block_tasks() -> None:
    guard = ReturnMainGuard()
    context = Mock(spec=Context)
    guard.on_node_pipeline_node(context, NotificationType.Failed, _node("Awards", 1))
    guard.on_node_pipeline_node(context, NotificationType.Cancelled, _node("ReturnMain", 1))
    guard.on_node_pipeline_node(context, NotificationType.Starting, _node("Awards", 2))
    context.run_action_direct.assert_not_called()
