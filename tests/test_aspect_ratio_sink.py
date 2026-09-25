from collections.abc import Callable
from typing import cast

import pytest
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink

from agent.custom.sink import aspect_ratio
from agent.custom.sink.aspect_ratio import AspectRatioChecker


class _ScreencapJob:
    def __init__(self, on_done: Callable[[], None]) -> None:
        self._on_done = on_done

    def wait(self) -> "_ScreencapJob":
        return self

    def get(self) -> object:
        self._on_done()
        return object()


class _FakeController:
    """复现 maa 的缓存语义：没有截图时 resolution 恒为 (0, 0)。"""

    def __init__(
        self,
        resolution: tuple[int, int] = (1280, 720),
        *,
        cached: bool = False,
        screencap_works: bool = True,
    ) -> None:
        self._pending_resolution = resolution
        self._resolution = resolution if cached else (0, 0)
        self._screencap_works = screencap_works
        self.screencap_count = 0

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution

    def post_screencap(self) -> _ScreencapJob:
        self.screencap_count += 1
        return _ScreencapJob(self._apply_screencap)

    def _apply_screencap(self) -> None:
        if self._screencap_works:
            self._resolution = self._pending_resolution


class _RaisingResolutionController(_FakeController):
    @property
    def resolution(self) -> tuple[int, int]:
        raise RuntimeError("Failed to get cached image.")


class _FailingScreencapController(_FakeController):
    def post_screencap(self) -> _ScreencapJob:
        raise RuntimeError("Failed to screencap.")


class _FakeTasker:
    def __init__(self, controller: object) -> None:
        self.controller = controller
        self.post_stop_count = 0

    def post_stop(self) -> None:
        self.post_stop_count += 1


def _detail(entry: str = "StartUp") -> TaskerEventSink.TaskerTaskDetail:
    return TaskerEventSink.TaskerTaskDetail(task_id=1, entry=entry, uuid="uuid", hash="hash")


def _fake_tasker(controller: object) -> tuple[_FakeTasker, Tasker]:
    fake = _FakeTasker(controller)
    return fake, cast(Tasker, fake)


def _speed_up_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aspect_ratio, "MAX_RESOLUTION_RETRIES", 3)
    monkeypatch.setattr(aspect_ratio, "RESOLUTION_RETRY_INTERVAL_SECONDS", 0.0)


def test_get_controller_resolution_screencaps_when_cache_is_cold() -> None:
    controller = _FakeController()

    assert aspect_ratio.get_controller_resolution(controller) == (1280, 720)
    assert controller.screencap_count == 1


def test_get_controller_resolution_reuses_warm_cache() -> None:
    controller = _FakeController(cached=True)

    assert aspect_ratio.get_controller_resolution(controller) == (1280, 720)
    assert controller.screencap_count == 0


def test_get_controller_resolution_gives_up_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_retries(monkeypatch)
    controller = _FakeController(screencap_works=False)

    assert aspect_ratio.get_controller_resolution(controller) == (0, 0)
    assert controller.screencap_count == 3


def test_get_controller_resolution_survives_screencap_failure() -> None:
    assert aspect_ratio.get_controller_resolution(_FailingScreencapController()) == (0, 0)


def test_read_controller_resolution_swallows_errors() -> None:
    assert aspect_ratio.read_controller_resolution(_RaisingResolutionController()) == (0, 0)


def test_sink_screencaps_cold_cache_instead_of_stopping() -> None:
    controller = _FakeController()
    fake, tasker = _fake_tasker(controller)

    AspectRatioChecker().on_tasker_task(tasker, NotificationType.Starting, _detail())

    assert controller.screencap_count == 1
    assert fake.post_stop_count == 0


def test_sink_skips_check_when_resolution_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _speed_up_retries(monkeypatch)
    fake, tasker = _fake_tasker(_FakeController(screencap_works=False))

    AspectRatioChecker().on_tasker_task(tasker, NotificationType.Starting, _detail())

    assert fake.post_stop_count == 0


def test_sink_stops_task_on_non_16x9_resolution() -> None:
    fake, tasker = _fake_tasker(_FakeController((1280, 1024)))

    AspectRatioChecker().on_tasker_task(tasker, NotificationType.Starting, _detail())

    assert fake.post_stop_count == 1


def test_sink_requires_exact_resolution_for_switch_account() -> None:
    fake, tasker = _fake_tasker(_FakeController((1920, 1080)))

    AspectRatioChecker().on_tasker_task(tasker, NotificationType.Starting, _detail("SwitchAccount"))

    assert fake.post_stop_count == 1


def test_sink_ignores_non_starting_events() -> None:
    controller = _FakeController()
    fake, tasker = _fake_tasker(controller)

    AspectRatioChecker().on_tasker_task(tasker, NotificationType.Succeeded, _detail())

    assert controller.screencap_count == 0
    assert fake.post_stop_count == 0


def test_sink_ignores_post_stop_entry() -> None:
    controller = _FakeController()
    fake, tasker = _fake_tasker(controller)

    AspectRatioChecker().on_tasker_task(tasker, NotificationType.Starting, _detail("MaaTaskerPostStop"))

    assert controller.screencap_count == 0
    assert fake.post_stop_count == 0
