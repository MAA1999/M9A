import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from maa.define import OCRResult, RecognitionDetail, RecognitionResult, Rect

import agent.custom.action.combat as combat_module
from agent.custom.action.combat import (
    SSReopenReplay,
    TargetCountDetermine,
    TargetCountEatCandy,
    TargetCountSelectTimes,
    _TargetCountPage,
    _TargetCountState,
    _tc_calculate_available_count,
    _tc_get_availability,
)


def _recognition_detail(text: str | None = None) -> RecognitionDetail:
    rect = Rect(1, 1, 2, 2)
    best_result: RecognitionResult | None = OCRResult(rect, 0.9, text) if text is not None else None
    return RecognitionDetail(
        reco_id=1,
        name="TestRecognition",
        algorithm="Test",
        hit=True,
        box=rect,
        all_results=[best_result] if best_result is not None else [],
        filtered_results=[best_result] if best_result is not None else [],
        best_result=best_result,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


class _ScreenshotRequest:
    def wait(self) -> "_ScreenshotRequest":
        return self

    def get(self) -> object:
        return object()


class _RecognitionContext:
    def __init__(self, results: dict[str, RecognitionDetail | None], eat_candy_enabled: bool = True) -> None:
        self.results = results
        self.calls: list[str] = []
        self.eat_candy_enabled = eat_candy_enabled
        self.override: tuple[str, list[str]] | None = None
        self.tasker = SimpleNamespace(controller=SimpleNamespace(post_screencap=lambda: _ScreenshotRequest()))

    def run_recognition(self, name: str, _image: object) -> RecognitionDetail | None:
        self.calls.append(name)
        return self.results.get(name)

    def get_node_data(self, name: str) -> dict[str, object] | None:
        if name != "EatCandy":
            return None
        return {"enabled": self.eat_candy_enabled}

    def override_next(self, node: str, next_nodes: list[str]) -> None:
        self.override = (node, next_nodes)


class _ActionContext:
    def __init__(self, task_failed: bool | None = None) -> None:
        self.override: tuple[str, list[str]] | None = None
        self.task_failed = task_failed

    def run_task(self, *_args: object, **_kwargs: object) -> object | None:
        if self.task_failed is None:
            return None
        return SimpleNamespace(status=SimpleNamespace(failed=self.task_failed))

    def override_next(self, node: str, next_nodes: list[str]) -> None:
        self.override = (node, next_nodes)


class _SSActionContext:
    def __init__(self, eat_candy_failed: bool | None = False, eat_candy_enabled: bool = True) -> None:
        self.tasks: list[str] = []
        self.stopped = False
        self.eat_candy_failed = eat_candy_failed
        self.eat_candy_enabled = eat_candy_enabled
        self.pipeline_overridden = False
        self.tasker = SimpleNamespace(
            controller=SimpleNamespace(cached_image=object()),
            post_stop=self._post_stop,
        )

    def run_task(self, name: str, *_args: object, **_kwargs: object) -> object | None:
        self.tasks.append(name)
        if name == "EatCandy" and self.eat_candy_failed is None:
            return None
        failed = self.eat_candy_failed if name == "EatCandy" else False
        return SimpleNamespace(status=SimpleNamespace(failed=failed))

    def run_recognition(self, _name: str, _image: object) -> None:
        return None

    def get_node_data(self, name: str) -> dict[str, object] | None:
        if name != "EatCandy":
            return None
        return {"enabled": self.eat_candy_enabled}

    def override_pipeline(self, _pipeline: object) -> None:
        self.pipeline_overridden = True

    def _post_stop(self) -> None:
        self.stopped = True


def _reset_target_count_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_TargetCountState, "target_count", 10)
    monkeypatch.setattr(_TargetCountState, "already_count", 0)
    monkeypatch.setattr(_TargetCountState, "current_times", 0)
    monkeypatch.setattr(_TargetCountState, "candy_attempts", 0)


def test_calculate_available_count_distinguishes_zero_and_invalid_values() -> None:
    assert _tc_calculate_available_count(60, 60, 3) == 3
    assert _tc_calculate_available_count(0, 20, 1) == 0
    assert _tc_calculate_available_count(60, 0, 1) is None
    assert _tc_calculate_available_count(60, 60, 0) is None
    assert _tc_calculate_available_count(60, 61, 3) is None


def test_get_availability_recognizes_an_already_open_recovery_page() -> None:
    context = _RecognitionContext({"EatCandyPage": _recognition_detail()})

    availability = _tc_get_availability(context)  # type: ignore[arg-type]

    assert availability.page is _TargetCountPage.RECOVERY
    assert availability.available_count == 0
    assert context.calls == ["EatCandyPage"]


def test_get_availability_aborts_when_page_and_required_values_are_unknown() -> None:
    context = _RecognitionContext(
        {
            "RecognizeRemainingAp": _recognition_detail("60"),
            "RecognizeCombatTimes": _recognition_detail("3"),
        }
    )

    availability = _tc_get_availability(context)  # type: ignore[arg-type]

    assert availability.page is _TargetCountPage.UNKNOWN
    assert availability.available_count is None


def test_eat_candy_pipeline_accepts_open_page_before_stage_entry() -> None:
    pipeline_path = Path(__file__).parents[1] / "resource" / "base" / "pipeline" / "eat_candy.json"
    pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))

    assert pipeline["EatCandy"]["next"] == ["EatCandyPage", "EatCandyEnter"]
    assert pipeline["EatCandyEnter"]["post_delay"] == 1500


def test_select_times_aborts_when_subtask_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _ActionContext()
    monkeypatch.setattr(_TargetCountState, "current_times", 3)

    TargetCountSelectTimes().run(context, None)  # type: ignore[arg-type]

    assert context.override == ("TargetCountSelectTimes", ["TargetCountAbort"])


def test_select_times_keeps_normal_next_when_subtask_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _ActionContext(task_failed=False)
    monkeypatch.setattr(_TargetCountState, "current_times", 3)

    TargetCountSelectTimes().run(context, None)  # type: ignore[arg-type]

    assert context.override is None


def test_eat_candy_aborts_when_subtask_fails() -> None:
    context = _ActionContext()

    TargetCountEatCandy().run(context, None)  # type: ignore[arg-type]

    assert context.override == ("TargetCountEatCandy", ["TargetCountAbort"])


def test_eat_candy_returns_to_determine_when_subtask_succeeds() -> None:
    context = _ActionContext(task_failed=False)

    TargetCountEatCandy().run(context, None)  # type: ignore[arg-type]

    assert context.override == ("TargetCountEatCandy", ["TargetCountDetermine"])


def test_determine_finishes_when_eat_candy_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_target_count_state(monkeypatch)
    context = _RecognitionContext(
        {
            "RecognizeRemainingAp": _recognition_detail("10"),
            "RecognizeStageAp": _recognition_detail("25"),
            "RecognizeCombatTimes": _recognition_detail("1"),
        },
        eat_candy_enabled=False,
    )

    result = TargetCountDetermine().run(context, None)  # type: ignore[arg-type]

    assert result.success
    assert context.override == ("TargetCountDetermine", ["TargetCountFinish"])


def test_determine_keeps_eat_candy_next_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_target_count_state(monkeypatch)
    context = _RecognitionContext(
        {
            "RecognizeRemainingAp": _recognition_detail("10"),
            "RecognizeStageAp": _recognition_detail("25"),
            "RecognizeCombatTimes": _recognition_detail("1"),
        },
        eat_candy_enabled=True,
    )

    result = TargetCountDetermine().run(context, None)  # type: ignore[arg-type]

    assert result.success
    assert context.override == ("TargetCountDetermine", ["TargetCountEatCandy"])


def test_ss_reopen_stops_when_initial_availability_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _SSActionContext()
    unknown = combat_module._TargetCountAvailability(page=_TargetCountPage.UNKNOWN)
    monkeypatch.setattr(combat_module, "_tc_get_availability", lambda _context: unknown)

    result = SSReopenReplay().run(context, None)  # type: ignore[arg-type]

    assert not result.success
    assert context.tasks == ["SSToReplayIfCan", "HomeButton"]
    assert context.stopped


def test_ss_reopen_stops_when_availability_is_unknown_after_eating_candy(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _SSActionContext()
    availabilities = iter(
        [
            combat_module._TargetCountAvailability(page=_TargetCountPage.RECOVERY, available_count=0),
            combat_module._TargetCountAvailability(page=_TargetCountPage.UNKNOWN),
        ]
    )
    monkeypatch.setattr(combat_module, "_tc_get_availability", lambda _context: next(availabilities))

    result = SSReopenReplay().run(context, None)  # type: ignore[arg-type]

    assert not result.success
    assert context.tasks == ["SSToReplayIfCan", "EatCandy", "HomeButton"]
    assert context.stopped


def test_ss_reopen_stops_eating_after_first_successful_restoration(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _SSActionContext()
    availabilities = iter(
        [
            combat_module._TargetCountAvailability(page=_TargetCountPage.RECOVERY, available_count=0),
            combat_module._TargetCountAvailability(page=_TargetCountPage.STAGE, available_count=1),
        ]
    )
    monkeypatch.setattr(combat_module, "_tc_get_availability", lambda _context: next(availabilities))

    result = SSReopenReplay().run(context, None)  # type: ignore[arg-type]

    assert result.success
    assert context.tasks == ["SSToReplayIfCan", "EatCandy", "OpenReplaysTimes", "SSReopenBackToMain"]
    assert context.pipeline_overridden
    assert not context.stopped


@pytest.mark.parametrize("eat_candy_failed", [None, True])
def test_ss_reopen_stops_when_eat_candy_subtask_fails(
    monkeypatch: pytest.MonkeyPatch,
    eat_candy_failed: bool | None,
) -> None:
    context = _SSActionContext(eat_candy_failed=eat_candy_failed)
    recovery = combat_module._TargetCountAvailability(page=_TargetCountPage.RECOVERY, available_count=0)
    monkeypatch.setattr(combat_module, "_tc_get_availability", lambda _context: recovery)

    result = SSReopenReplay().run(context, None)  # type: ignore[arg-type]

    assert not result.success
    assert context.tasks == ["SSToReplayIfCan", "EatCandy", "HomeButton"]
    assert context.stopped


def test_ss_reopen_ends_when_eat_candy_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _SSActionContext(eat_candy_enabled=False)
    recovery = combat_module._TargetCountAvailability(page=_TargetCountPage.RECOVERY, available_count=0)
    monkeypatch.setattr(combat_module, "_tc_get_availability", lambda _context: recovery)

    result = SSReopenReplay().run(context, None)  # type: ignore[arg-type]

    assert result.success
    assert context.tasks == ["SSToReplayIfCan", "HomeButton"]
    assert not context.stopped
