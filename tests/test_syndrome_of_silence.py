"""SOS 节点分类与中断恢复的回归测试。

覆盖：事件归属、备用 ROI，以及弹窗恢复、重试预算和子任务结果。
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from agent.custom.action import syndrome_of_silence as sos
from agent.custom.action.syndrome_of_silence import SOSNodeProcess, SOSSelectNode

_JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*')
_SOS_PIPELINE = Path("resource/base/pipeline/activity/TheSyndromeOfSilence.json")
_SOS_NODES = Path("data/sos/nodes.json")
_ATTRIBUTES_MARKERS = {"改造状态", "属性详情"}


def _load_jsonc(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    text = _JSONC_TOKEN.sub(lambda match: match.group(0) if match.group(0).startswith('"') else "", raw)
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


def _ocr_expected(node: dict[str, Any]) -> set[str]:
    expected = node.get("recognition", {}).get("param", {}).get("expected", [])
    return set(expected if isinstance(expected, list) else [expected])


_NODES = {
    "types": ["已完成节点", "冲突", "途中偶遇", "必经之路", "休憩处"],
    "common_interrupts": {"stats": ["SOSWarning"]},
    "已完成节点": {"event_name_roi": None, "actions": []},
    "冲突": {"event_name_roi": None, "actions": []},
    "恶战": {"event_name_roi": None, "actions": []},
    "途中偶遇": {
        "event_name_roi": [45, 74, 207, 29],
        "events": {"鬃毛的回报": {"actions": []}},
    },
    "必经之路": {
        "event_name_roi": [858, 72, 155, 33],
        "events": {"黑袍访客": {"actions": []}, "旅途的开始": {"actions": []}},
    },
    "休憩处": {
        "event_name_roi": [858, 72, 132, 33],
        "events": {"俱乐部来客": {"actions": []}},
    },
}


def test_find_event_owner_exact_hit() -> None:
    """OCR 文本与事件表精确一致时返回归属类型。"""
    assert SOSSelectNode._find_event_owner("黑袍访客", _NODES) == "必经之路"


def test_find_event_owner_fuzzy_hit() -> None:
    """OCR 有轻微错字时按 0.6 相似度兜底命中。"""
    assert SOSSelectNode._find_event_owner("黑袍访容", _NODES) == "必经之路"


def test_find_event_owner_miss_returns_none() -> None:
    """完全无关文本不强行归属。"""
    assert SOSSelectNode._find_event_owner("毫不相干的乱码", _NODES) is None


def test_find_event_owner_ignores_meta_keys() -> None:
    """types / common_interrupts 等元数据键不参与查找且不抛错。"""
    assert SOSSelectNode._find_event_owner("stats", _NODES) is None


def test_collect_alt_event_rois_excludes_own_and_dedup() -> None:
    """备用 ROI 排除自身类型，跨类型重复 ROI 只保留一次，保持首现顺序。"""
    rois = SOSSelectNode._collect_alt_event_rois(_NODES, "途中偶遇")
    assert rois == [[858, 72, 155, 33], [858, 72, 132, 33]]


def test_collect_alt_event_rois_skips_null_roi_types() -> None:
    """无事件名类型（event_name_roi=None）不产生备用 ROI。"""
    assert SOSSelectNode._collect_alt_event_rois(_NODES, "必经之路") == [
        [45, 74, 207, 29],
        [858, 72, 132, 33],
    ]


def test_match_node_type_exact_hit() -> None:
    """预览面板 OCR 文本与类型名完全一致。"""
    assert SOSSelectNode._match_node_type("必经之路", _NODES) == "必经之路"


def test_match_node_type_containment_hit() -> None:
    """类型名带前后缀修饰时按包含关系命中（如「恶战·试炼」→ 恶战）。"""
    assert SOSSelectNode._match_node_type("恶战·试炼", _NODES) == "恶战"


def test_match_node_type_miss_returns_empty() -> None:
    """无法归属的文本返回空串，保留模板识别结果。"""
    assert SOSSelectNode._match_node_type("毫不相干的乱码", _NODES) == ""


def test_persistent_banner_stops_before_later_event_action(monkeypatch) -> None:
    context = Mock()
    context.clone.return_value = context
    context.tasker.stopping = False
    context.run_recognition.side_effect = lambda name, *_: SimpleNamespace(
        hit=name == "SOSClickEventRec", box=[0, 0, 1, 1], algorithm="OCR"
    )
    context.run_task.return_value = SimpleNamespace(status=SimpleNamespace(succeeded=True))
    monkeypatch.setattr(sos.time, "sleep", lambda _: None)
    monkeypatch.setattr(sos.time, "monotonic", lambda: 0)
    monkeypatch.setattr(SOSSelectNode, "node_type", "途中偶遇")
    monkeypatch.setattr(SOSSelectNode, "event_name", "鬃毛的回报")
    process = SOSNodeProcess()
    monkeypatch.setattr(process, "_skip_stranded_event", lambda *_: False)
    result = process.run(context, SimpleNamespace(custom_action_param="{}"))
    assert not result.success
    assert context.run_task.call_count <= 5
    assert all(call.args == ("SOSClickEventRec",) for call in context.run_task.call_args_list)
    assert (
        sum(call.args[0] == "SOSSelectEncounterOptionRec_Template" for call in context.run_recognition.call_args_list)
        == 5
    )


@pytest.mark.parametrize("action", ["SOSStatsUp", {"type": "RunNode", "name": "SOSStatsUp"}])
@pytest.mark.parametrize("succeeded", [None, False, True])
def test_interrupt_requires_successful_task_result(action, succeeded) -> None:
    context = Mock()
    context.tasker.stopping = False
    context.run_recognition.return_value = SimpleNamespace(hit=True, box=[0, 0, 1, 1], algorithm="OCR")
    context.run_task.return_value = (
        None if succeeded is None else SimpleNamespace(status=SimpleNamespace(succeeded=succeeded))
    )
    assert SOSNodeProcess().exec_action(context, action) is (succeeded is True)


@pytest.mark.parametrize("method", ["OCR", "HSV"])
@pytest.mark.parametrize(
    ("succeeded", "page_still_open", "expected"),
    [(True, True, True), (False, True, False), (False, False, True), (None, True, False)],
)
def test_encounter_option_failure_is_reported(monkeypatch, method, succeeded, page_still_open, expected) -> None:
    """子任务失败且选项页仍在时必须返回失败；选项页已离开说明选择生效，仍算完成。"""
    monkeypatch.setattr(sos.time, "sleep", lambda _: None)
    context = Mock()
    context.tasker.stopping = False
    calls = {"n": 0}

    def recognize(name, *_):
        calls["n"] += 1
        hit = calls["n"] == 1 or page_still_open
        return SimpleNamespace(hit=hit, box=[0, 0, 1, 1], algorithm="TemplateMatch")

    context.run_recognition.side_effect = recognize
    context.run_task.return_value = (
        None if succeeded is None else SimpleNamespace(status=SimpleNamespace(succeeded=succeeded))
    )
    action = {"type": "SelectEncounterOption", "method": method, "expected": "x", "index": 0}
    assert SOSNodeProcess().exec_action(context, action) is expected


@pytest.mark.parametrize(("page_still_open", "expected"), [(True, False), (False, True)])
def test_failed_interrupt_counts_when_screen_moved_on(page_still_open, expected) -> None:
    """中断子任务失败时：画面仍在算点击失败；画面已推进（如共鸣器确认后 next 超时）算已处理。"""
    context = Mock()
    context.tasker.stopping = False
    calls = {"n": 0}

    def recognize(*_):
        calls["n"] += 1
        return SimpleNamespace(hit=calls["n"] == 1 or page_still_open, box=[0, 0, 1, 1], algorithm="OCR")

    context.run_recognition.side_effect = recognize
    context.run_task.return_value = SimpleNamespace(status=SimpleNamespace(succeeded=False))
    assert SOSNodeProcess().exec_action(context, "SOSSelectResonator") is expected
    assert calls["n"] == 2


def test_direct_hit_without_box_executes() -> None:
    context = Mock()
    context.tasker.stopping = False
    context.run_recognition.return_value = SimpleNamespace(hit=True, box=None, algorithm="DirectHit")
    context.run_task.return_value = SimpleNamespace(status=SimpleNamespace(succeeded=True))
    assert SOSNodeProcess().exec_action(context, {"type": "RunNode", "name": "Pending"})


def test_attributes_close_pipeline_gates_click_and_successor() -> None:
    """属性关闭必须同时命中页面文字和返回按钮，点击 BackButton，并在后继节点确认页面已消失。"""
    pipeline = _load_jsonc(_SOS_PIPELINE)
    nodes = json.loads(_SOS_NODES.read_text(encoding="utf-8"))

    close = pipeline["SOSAttributesClose"]
    all_of = close["recognition"]["param"]["all_of"]
    assert close["recognition"]["type"] == "And"
    assert "BackButton" in all_of
    marker_nodes = [item for item in all_of if isinstance(item, dict)]
    assert marker_nodes, "属性页 OCR 标记不能缺失，否则其他带返回键的界面也会被点返回"
    assert _ATTRIBUTES_MARKERS <= _ocr_expected(marker_nodes[0])
    assert close["recognition"]["param"]["box_index"] == 0
    assert close["action"] == {"type": "Click"}
    assert close["next"] == ["SOSAttributesClosed", "SOSAttributesCloseRetry1"]
    # max_hit 是任务内累计额度，长跑局会被耗尽；重试改为每次关闭流程独立的有限链
    chain = ["SOSAttributesClose", "SOSAttributesCloseRetry1", "SOSAttributesCloseRetry2"]
    for name in chain:
        assert "max_hit" not in pipeline[name]
    for prev, name in zip(chain, chain[1:], strict=False):
        retry = pipeline[name]
        assert retry["recognition"]["type"] == "And"
        assert retry["recognition"]["param"]["all_of"] == ["SOSAttributesClose"]
        assert retry["action"] == {"type": "Click"}
        assert pipeline[prev]["next"] == ["SOSAttributesClosed", name]
    assert pipeline[chain[-1]]["next"] == ["SOSAttributesClosed"], "属性页重试链必须有终点"

    closed = pipeline["SOSAttributesClosed"]
    assert closed.get("inverse") is True
    assert closed["recognition"]["type"] == "OCR"
    assert _ATTRIBUTES_MARKERS <= _ocr_expected(closed)
    assert "inverse" not in json.dumps(closed["recognition"])
    assert "SOSResonatorTransition" not in json.dumps(closed)
    assert "SOSAttributesClose" not in json.dumps(closed)

    assert "SOSAttributesClose" in nodes["common_interrupts"]["stats"]
    error_next = pipeline["SOSNodeProcessErrorLoop"]["next"]
    assert "[JumpBack]SOSAttributesClose" in error_next
    close_idx = error_next.index("[JumpBack]SOSAttributesClose")
    for destructive in ("[JumpBack]SOSGiveup", "[JumpBack]SOSStart", "[JumpBack]SOSAbortConfirm"):
        assert close_idx < error_next.index(destructive)


@pytest.mark.parametrize("successor", ["SOSAttributesClose", "SOSStatsUp", "SOSSelectHarmonic"])
@pytest.mark.parametrize("completed", [False, True])
def test_real_interrupts_resume_pending_action(monkeypatch, successor, completed) -> None:
    pipeline = _load_jsonc(_SOS_PIPELINE)
    context = Mock()
    context.clone.return_value = context
    context.tasker.stopping = False
    screens = iter(["SOSSelectResonatorConfirm", successor, "SOSNodeProcessFinished"])
    screen = next(screens)

    def recognize(name, *_):
        return SimpleNamespace(hit=name == screen, box=[0, 0, 1, 1], algorithm="OCR")

    def run_task(name=None, *_, **kwargs):
        nonlocal screen
        entry = name or kwargs.get("entry")
        if entry == "SOSAttributesClose":
            close = pipeline["SOSAttributesClose"]
            assert "BackButton" in close["recognition"]["param"]["all_of"]
            assert close["action"]["type"] == "Click"
            assert close["next"] == ["SOSAttributesClosed", "SOSAttributesCloseRetry1"]
            closed = pipeline["SOSAttributesClosed"]
            assert closed.get("inverse") is True
            assert _ATTRIBUTES_MARKERS <= _ocr_expected(closed)
            screen = "SOSNodeProcessFinished"
            return SimpleNamespace(status=SimpleNamespace(succeeded=True))
        screen = next(screens, "SOSNodeProcessFinished")
        return SimpleNamespace(
            status=SimpleNamespace(succeeded=completed if kwargs.get("entry") == "SOSNodeProcessFinished" else True)
        )

    context.run_recognition.side_effect = recognize
    context.run_task.side_effect = run_task
    monkeypatch.setattr(sos.time, "sleep", lambda _: None)
    monkeypatch.setattr(sos.time, "monotonic", lambda: 0)
    assert (
        SOSNodeProcess().exec_main(
            context,
            {"type": "RunNode", "name": "SOSNodeProcessFinished"},
            ["SOSSelectResonatorConfirm", successor],
        )
        is completed
    )
    assert context.run_task.call_args_list[0].args == ("SOSSelectResonatorConfirm",)
    assert context.run_task.call_args_list[1].args == (successor,)
    assert context.run_task.call_args_list[2].kwargs == {"entry": "SOSNodeProcessFinished"}


@pytest.mark.parametrize("mode", ["cancel_before", "cancel_scanning", "deadline", "unknown", "complete"])
def test_main_action_boundaries(monkeypatch, mode) -> None:
    context = Mock()
    context.clone.return_value = context
    context.tasker.stopping = mode == "cancel_before"
    clock = 0

    def recognize(*_):
        nonlocal clock
        clock += 120 if mode == "deadline" else 0
        if mode == "cancel_scanning":
            context.tasker.stopping = True
        return SimpleNamespace(hit=mode == "complete", box=[0, 0, 1, 1], algorithm="OCR")

    context.run_recognition.side_effect = recognize
    context.run_task.return_value = SimpleNamespace(status=SimpleNamespace(succeeded=True))
    monkeypatch.setattr(sos.time, "sleep", lambda _: None)
    monkeypatch.setattr(sos.time, "monotonic", lambda: clock)
    assert SOSNodeProcess().exec_main(context, {"type": "RunNode", "name": "Pending"}, ["Interrupt"]) is (
        mode == "complete"
    )
    if mode in ("cancel_before", "cancel_scanning", "deadline"):
        assert context.run_recognition.call_count <= 1
    elif mode == "unknown":
        assert context.run_recognition.call_count == 10
