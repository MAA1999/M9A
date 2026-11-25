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


def _screencap(
    context: Context,
    *,
    image: Any = None,
    succeeded: bool = True,
    get_exc: BaseException | None = None,
    post_exc: BaseException | None = None,
) -> None:
    """配置 context.tasker.controller.post_screencap() 的返回链。"""
    controller = context.tasker.controller
    if post_exc is not None:
        controller.post_screencap.side_effect = post_exc
        return
    job = Mock()
    job.wait.return_value = job
    job.status.succeeded = succeeded
    if get_exc is not None:
        job.get.side_effect = get_exc
    else:
        job.get.return_value = image
    controller.post_screencap.return_value = job


def _tm() -> dict[str, Any]:
    return {"recognition": {"type": "TemplateMatch"}}


@pytest.fixture
def guard_context() -> Context:
    return _context({"ReturnMain": {"next": [{"name": "HomeFlagCloseReturnMain"}]}, "HomeFlagCloseReturnMain": _tm()})


def _arm(guard: ReturnMainGuard, context: Context) -> None:
    guard.on_node_pipeline_node(context, NotificationType.Failed, _node("ReturnMain", 10))


def test_only_later_tasks_reaching_return_main_are_stopped(
    monkeypatch: pytest.MonkeyPatch, guard_context: Context
) -> None:
    probe = Mock(return_value=False)
    monkeypatch.setattr(return_main_guard, "_screen_recovered", probe)
    guard = ReturnMainGuard()
    guard.on_node_pipeline_node(guard_context, NotificationType.Failed, _node("ReturnMain", 30, 10))
    guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("ReturnMain", 31, 10))

    guard_context.get_task_job.return_value.job_id = 11
    for name in ["ManualPageTask", "ReadPage", "Done"]:
        guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node(name, 11))
    probe.assert_not_called()
    guard_context.run_action_direct.assert_not_called()

    for root_id, node in [(12, _node("ReturnMain", 12)), (13, _node("ReturnMain", 32, 13))]:
        guard_context.get_task_job.return_value.job_id = root_id
        guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("Awards", root_id))
        guard.on_node_pipeline_node(guard_context, NotificationType.Starting, node)
    assert probe.call_count == 2
    assert guard_context.run_action_direct.call_count == 2
    guard_context.run_action_direct.assert_called_with(JActionType.StopTask, JStopTask())


def test_recovered_lets_task_run_and_disarms(monkeypatch: pytest.MonkeyPatch, guard_context: Context) -> None:
    probe = Mock(return_value=True)
    monkeypatch.setattr(return_main_guard, "_screen_recovered", probe)
    guard = ReturnMainGuard()
    _arm(guard, guard_context)

    for task_id in [11, 12]:
        guard_context.get_task_job.return_value.job_id = task_id
        guard.on_node_pipeline_node(guard_context, NotificationType.Starting, _node("ReturnMain", task_id))
    probe.assert_called_once_with(guard_context)
    guard_context.run_action_direct.assert_not_called()


def test_probe_post_exception_is_conservative() -> None:
    context = _context({"ReturnMain": {"next": [{"name": "Confirm"}]}, "Confirm": _tm()})
    _screencap(context, post_exc=RuntimeError("boom"))

    assert return_main_guard._screen_recovered(context) is False
    context.run_recognition.assert_not_called()


def test_probe_rejects_stale_frame_when_screencap_job_failed() -> None:
    # 作业失败但 get() 仍返回旧帧：若不判作业状态，旧帧命中会误放行
    context = _context({"ReturnMain": {"next": [{"name": "Confirm"}]}, "Confirm": _tm()})
    stale = numpy.zeros((4, 4, 3), dtype=numpy.uint8)
    _screencap(context, image=stale, succeeded=False)

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
    _screencap(context, image=image, succeeded=True)
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
    _screencap(context, image=image, succeeded=True)
    context.run_recognition.return_value = SimpleNamespace(hit=False)

    assert return_main_guard._screen_recovered(context) is False


def test_directhit_candidates_are_excluded() -> None:
    # DirectHit / 含 DirectHit 的 Or / 全恒命中的 And / 缺省识别，都要剔除
    dh_direct = {"recognition": {"type": "DirectHit"}}
    and_all_dh = {"recognition": {"type": "And", "param": {"all_of": [dh_direct, "DhNode"]}}}
    and_with_template = {"recognition": {"type": "And", "param": {"all_of": ["DhNode", "RealTemplate"]}}}
    context = _context(
        {
            "ReturnMain": {
                "next": [
                    {"name": "DhNode"},
                    {"name": "OrWithDh"},
                    {"name": "AndAllDh"},
                    {"name": "DefaultReco"},
                    {"name": "AndWithTemplate"},
                    {"name": "RealTemplate"},
                ]
            },
            "DhNode": {"recognition": {"type": "DirectHit"}},
            "OrWithDh": {"recognition": {"type": "Or", "param": {"any_of": ["DhNode"]}}},
            "AndAllDh": and_all_dh,
            "DefaultReco": {},  # 无 recognition ⇒ 默认 DirectHit
            "AndWithTemplate": and_with_template,
            "RealTemplate": _tm(),
        }
    )

    assert return_main_guard._probe_candidates(context) == ["AndWithTemplate", "RealTemplate"]


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
    guard.on_node_pipeline_node(context, NotificationType.Starting, _node("ReturnMain", 2))
    context.get_node_data.assert_not_called()
    context.run_action_direct.assert_not_called()
