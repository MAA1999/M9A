"""活动推图单按钮模式切换回归。

探索页上的「故事」和故事页上的「探索/探险」是切换按钮。点击必须使用
APModeGate 返回的 OCR 框；固定点 [125, 115] 落在框外时画面不会变化。
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from custom.reco.auto_promotion import APModeGate
from maa.define import OCRResult, RecognitionDetail, Rect

_PIPELINE_PATH = (
    Path(__file__).resolve().parents[1] / "resource" / "base" / "pipeline" / "activity" / "auto_promotion.json"
)
_MODE_ROI = [20, 60, 220, 260]
_LEGACY_CLICK = (125, 115)
# 720p 单按钮位置偏离历史固定点，框本身不包含 [125, 115]。
_SHIFTED_STORY_BUTTON = (28, 176, 84, 36)
_SHIFTED_EXPLORE_BUTTON = (160, 88, 64, 32)
_SETTLED_BUTTON = (210, 140, 40, 28)
_IMAGE = np.zeros((720, 1280, 3), dtype=np.uint8)

_Label = tuple[str, tuple[int, int, int, int]]


def _contains(box: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    x, y, width, height = box
    px, py = point
    return x <= px < x + width and y <= py < y + height


def _miss(name: str) -> RecognitionDetail:
    return RecognitionDetail(
        reco_id=0,
        name=name,
        algorithm="OCR",
        hit=False,
        box=None,
        all_results=[],
        filtered_results=[],
        best_result=None,
        raw_detail={},
        raw_image=_IMAGE,
        draw_images=[],
    )


def _ocr(name: str, labels: list[_Label]) -> RecognitionDetail:
    if not labels:
        return _miss(name)
    results = [OCRResult(Rect(*box), 0.99, text) for text, box in labels]
    return RecognitionDetail(
        reco_id=1,
        name=name,
        algorithm="OCR",
        hit=True,
        box=results[0].box,
        all_results=results,
        filtered_results=results,
        best_result=results[0],
        raw_detail={},
        raw_image=_IMAGE,
        draw_images=[],
    )


class _ModeScreen:
    """按给定 OCR 文本桩出模式锚点、关卡编号和开始行动。"""

    def __init__(self, labels: list[_Label], *, stage_map: bool, start_action: bool) -> None:
        self._labels = labels
        self._stage_map = stage_map
        self._start_action = start_action

    def run_recognition(self, name: str, _image: object) -> RecognitionDetail:
        if name == "APExploreAnchorOCR":
            return _ocr(name, self._labels)
        if name == "APStageNumberOCR":
            if not self._stage_map:
                return _miss(name)
            return _ocr(name, [("01", (400, 560, 40, 30))])
        if name == "AP_StartAction":
            if not self._start_action:
                return _miss(name)
            return _ocr(name, [("开始行动", (560, 620, 120, 40))])
        raise AssertionError(name)


def _pipeline() -> dict[str, Any]:
    loaded = json.loads(_PIPELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _recognize(
    query: str,
    labels: list[_Label],
    *,
    stage_map: bool = False,
    start_action: bool = False,
) -> Any:
    context = _ModeScreen(labels, stage_map=stage_map, start_action=start_action)
    argv = SimpleNamespace(custom_recognition_param=json.dumps({"query": query}), image=_IMAGE)
    return APModeGate().analyze(context, argv)  # type: ignore[arg-type]


def _box(result: Any) -> list[int]:
    assert result is not None and result.box is not None
    return [int(value) for value in result.box]


def _text_matches(expected: str | list[str], labels: list[_Label]) -> bool:
    tokens = expected if isinstance(expected, list) else [expected]
    return any(token in text for text, _box in labels for token in tokens)


def _matches(pipeline: dict[str, Any], name: str, labels: list[_Label], *, stage_map: bool) -> bool:
    """只解析本流程入口节点的识别条件，用来核对 next 顺序。"""
    recognition = pipeline[name].get("recognition")
    if not isinstance(recognition, dict):
        return True
    kind = recognition["type"]
    param = recognition.get("param", {})
    if kind == "Custom":
        assert param["custom_recognition"] == "APModeGate"
        return _recognize(param["custom_recognition_param"]["query"], labels, stage_map=stage_map) is not None
    if kind == "OCR":
        return _text_matches(param["expected"], labels)
    raise AssertionError(f"unexpected recognition on {name}: {kind}")


def _first_next(pipeline: dict[str, Any], name: str, labels: list[_Label], *, stage_map: bool = False) -> str | None:
    for successor in pipeline[name]["next"]:
        if _matches(pipeline, successor, labels, stage_map=stage_map):
            return successor
    return None


def _click_target(node: dict[str, Any]) -> Any:
    assert node["action"]["type"] == "Click"
    return node["action"].get("param", {}).get("target", True)


def _assert_single_button_switch(node: dict[str, Any], query: str, successor: str) -> None:
    recognition = node["recognition"]
    assert recognition["type"] == "Custom"
    assert recognition["param"]["custom_recognition"] == "APModeGate"
    assert recognition["param"]["custom_recognition_param"] == {"query": query}
    # 缺省 target 为 true，点击当前识别框。固定坐标 [125, 115] 不能通过。
    assert _click_target(node) is True
    assert "post_delay" not in node
    assert "pre_delay" not in node
    assert "repeat" not in node
    assert node["post_wait_freezes"] == {"time": 1000, "target": _MODE_ROI}
    assert node["next"] == [successor]


@pytest.mark.parametrize("story_label", ["探索", "探险"])
def test_shifted_story_button_reaches_story_promotion(story_label: str) -> None:
    """探索页只有偏移的「故事」按钮时，点击识别框；切到故事页后进入推图。"""
    assert not _contains(_SHIFTED_STORY_BUTTON, _LEGACY_CLICK)
    explore_page = [("故事", _SHIFTED_STORY_BUTTON)]

    hit = _recognize("explore", explore_page)
    assert _box(hit) == list(_SHIFTED_STORY_BUTTON)
    assert hit.detail == {"mode": "explore"}

    pipeline = _pipeline()
    _assert_single_button_switch(pipeline["AP_SwitchToStoryFromExplore"], "explore", "AP_EnsureStoryOrMain")
    assert _first_next(pipeline, "AP_EnsureStoryOrMain", explore_page) == "AP_SwitchToStoryFromExplore"

    story_page = [(story_label, _SETTLED_BUTTON)]
    ready = _recognize("story", story_page)
    assert _box(ready) == list(_SETTLED_BUTTON)
    assert ready.detail == {"mode": "story"}
    assert _recognize("explore", story_page) is None
    assert _first_next(pipeline, "AP_EnsureStoryOrMain", story_page) == "AP_StoryMapReady"
    assert "action" not in pipeline["AP_StoryMapReady"]
    assert pipeline["AP_StoryMapReady"]["next"] == ["AP_PromotionLoop"]


@pytest.mark.parametrize("explore_label", ["探索", "探险"])
def test_shifted_explore_button_reaches_explore_promotion(explore_label: str) -> None:
    """故事页的「探索/探险」按钮偏离固定点时，点击识别框；切到探索页后进入推图。"""
    assert not _contains(_SHIFTED_EXPLORE_BUTTON, _LEGACY_CLICK)
    story_page = [(explore_label, _SHIFTED_EXPLORE_BUTTON)]

    hit = _recognize("story", story_page)
    assert _box(hit) == list(_SHIFTED_EXPLORE_BUTTON)
    assert hit.detail == {"mode": "story"}

    pipeline = _pipeline()
    _assert_single_button_switch(pipeline["AP_SwitchToExploreFromStory"], "story", "AP_EnsureExplore")
    assert _first_next(pipeline, "AP_EnsureExplore", story_page) == "AP_SwitchToExploreFromStory"

    explore_page = [("故事", _SETTLED_BUTTON)]
    ready = _recognize("explore", explore_page)
    assert _box(ready) == list(_SETTLED_BUTTON)
    assert ready.detail == {"mode": "explore"}
    assert _recognize("story", explore_page) is None
    assert _first_next(pipeline, "AP_EnsureExplore", explore_page) == "AP_ExploreMapReady"
    assert "action" not in pipeline["AP_ExploreMapReady"]
    assert pipeline["AP_ExploreMapReady"]["next"] == ["AP_PromotionLoop"]


def test_switch_nodes_keep_recognition_click_and_mode_freeze() -> None:
    """两个单按钮切换节点保留模式查询、识别点击、冻结等待和入口后继。"""
    pipeline = _pipeline()
    assert pipeline["APExploreAnchorOCR"]["recognition"]["param"]["roi"] == _MODE_ROI
    assert pipeline["AP_SwitchToStory"]["recognition"]["param"]["roi"] == _MODE_ROI
    assert pipeline["AP_SwitchToExplore"]["recognition"]["param"]["roi"] == _MODE_ROI

    _assert_single_button_switch(pipeline["AP_SwitchToStoryFromExplore"], "explore", "AP_EnsureStoryOrMain")
    _assert_single_button_switch(pipeline["AP_SwitchToExploreFromStory"], "story", "AP_EnsureExplore")
    assert [125, 115] != _click_target(pipeline["AP_SwitchToStoryFromExplore"])
    assert [125, 115] != _click_target(pipeline["AP_SwitchToExploreFromStory"])

    assert pipeline["AP_EnsureStoryOrMain"]["next"].index("AP_StoryMapReady") < pipeline["AP_EnsureStoryOrMain"][
        "next"
    ].index("AP_SwitchToStoryFromExplore")
    assert pipeline["AP_EnsureExplore"]["next"].index("AP_ExploreMapReady") < pipeline["AP_EnsureExplore"][
        "next"
    ].index("AP_SwitchToExploreFromStory")
    assert pipeline["AP_StoryMapReady"]["recognition"]["param"]["custom_recognition_param"]["query"] == "story"
    assert pipeline["AP_ExploreMapReady"]["recognition"]["param"]["custom_recognition_param"]["query"] == "explore"

    assert pipeline["AP_SwitchToStory"]["recognition"]["param"]["expected"] == "故事"
    assert pipeline["AP_SwitchToExplore"]["recognition"]["param"]["expected"] == ["探索", "探险"]
    assert _click_target(pipeline["AP_SwitchToStory"]) is True
    assert _click_target(pipeline["AP_SwitchToExplore"]) is True
    assert pipeline["AP_SwitchToStory"]["next"] == ["AP_PromotionLoop"]
    assert pipeline["AP_SwitchToExplore"]["next"] == ["AP_PromotionLoop"]
    assert pipeline["AP_EnterStage"]["recognition"]["param"]["custom_recognition_param"]["query"] == "stage"


@pytest.mark.parametrize("explore_label", ["探索", "探险"])
def test_dual_labels_stay_ambiguous_and_ready_mode_skips_click(explore_label: str) -> None:
    """双标签不定当前模式；请求模式不符不命中；已在目标模式时直接推图。"""
    both = [("故事", _SHIFTED_STORY_BUTTON), (explore_label, _SHIFTED_EXPLORE_BUTTON)]
    assert _recognize("story", both) is None
    assert _recognize("explore", both) is None
    assert _recognize("main", both) is None

    story_button = [("故事", _SHIFTED_STORY_BUTTON)]
    explore_button = [(explore_label, _SHIFTED_EXPLORE_BUTTON)]
    assert _recognize("story", story_button) is None
    assert _recognize("explore", explore_button) is None
    assert _recognize("main", story_button) is None
    assert _recognize("main", explore_button) is None

    pipeline = _pipeline()
    assert _first_next(pipeline, "AP_EnsureStoryOrMain", both) == "AP_SwitchToStory"
    assert _first_next(pipeline, "AP_EnsureExplore", both) == "AP_SwitchToExplore"
    assert _first_next(pipeline, "AP_EnsureStoryOrMain", explore_button) == "AP_StoryMapReady"
    assert _first_next(pipeline, "AP_EnsureExplore", story_button) == "AP_ExploreMapReady"
    assert "action" not in pipeline["AP_StoryMapReady"]
    assert "action" not in pipeline["AP_ExploreMapReady"]
    assert pipeline["AP_StoryMapReady"]["next"] == ["AP_PromotionLoop"]
    assert pipeline["AP_ExploreMapReady"]["next"] == ["AP_PromotionLoop"]


def test_main_map_still_promotes_without_clicking_a_mode_button() -> None:
    """主线地图仍由 main 闸门直接推图，模式按钮和关卡详情页不走这条路径。"""
    pipeline = _pipeline()
    hit = _recognize("main", [], stage_map=True)
    assert _box(hit) == [0, 0, 0, 0]
    assert hit.detail == {"mode": "plain"}
    assert _recognize("story", [], stage_map=True) is None
    assert _recognize("explore", [], stage_map=True) is None
    assert _recognize("main", []) is None
    assert _recognize("main", [], stage_map=True, start_action=True) is None

    assert _first_next(pipeline, "AP_EnsureStoryOrMain", [], stage_map=True) == "AP_MainMapReady"
    assert "action" not in pipeline["AP_MainMapReady"]
    assert pipeline["AP_MainMapReady"]["recognition"]["param"]["custom_recognition_param"]["query"] == "main"
    assert pipeline["AP_MainMapReady"]["next"] == ["AP_PromotionLoop"]
    assert _first_next(pipeline, "AP_EnsureExplore", [], stage_map=True) == "AP_NoExploreMode"
    assert pipeline["AP_NoExploreMode"]["next"] == ["AP_AllPhasesDone"]
