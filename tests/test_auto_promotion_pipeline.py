import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

_agent_custom = importlib.import_module("agent.custom")
assert sys.modules["custom"] is _agent_custom

from agent.custom.reco.auto_promotion import APCardFinder, APMapAnalyze


def _load_json(path: str):
    with (ROOT / path).open(encoding="utf-8") as f:
        return json.load(f)


def test_auto_promotion_unlock_flow_order():
    pipeline = _load_json("assets/resource/base/pipeline/activity/auto_promotion.json")
    loop = pipeline["AP_PromotionLoop"]["next"]

    expected_order = [
        "AP_UnlockInsufficientCanister",
        "[JumpBack]AP_UnlockConfirm",
        "[JumpBack]AP_UnlockStage",
        "[JumpBack]AP_StartAction",
        "[JumpBack]AP_EnterStage",
    ]
    positions = [loop.index(node) for node in expected_order]
    assert positions == sorted(positions)

    assert pipeline["AP_UnlockStage"]["recognition"]["param"]["expected"] == "解锁"
    assert "显影罐不足" in pipeline["AP_UnlockInsufficientCanister"]["recognition"][
        "param"
    ]["expected"]


def test_auto_promotion_activity_cases_use_exact_card_names():
    task = _load_json("assets/resource/tasks/AutoPromotion.json")
    cases = task["option"]["选择活动"]["cases"]

    card_nodes = {
        "AP_Navigate": "nav",
        "AP_NavCardClick": "card",
        "AP_NavRewind": "rewind",
        "AP_NavForward": "swipe",
        "AP_NavNotFound": "notfound",
        "AP_NavPVTap": "pv",
    }

    historical_cases = []
    for case in cases:
        name = case["name"]
        override = case.get("pipeline_override", {})
        if name == "当前页面":
            assert override == {}
            continue

        for node, query in card_nodes.items():
            params = override[node]["recognition"]["param"]["custom_recognition_param"]
            assert params["query"] == query
            assert params["card_name"] == name

        if name == "当期活动":
            assert override["AP_NavCurrentEntry"]["enabled"] is True
            assert override["AP_NavStoryEnter"]["enabled"] is True
        else:
            historical_cases.append(name)

    assert "行于漫漫长路上" in historical_cases
    assert len(historical_cases) >= 19


def test_auto_promotion_card_title_match_tolerates_ocr_drift():
    assert APCardFinder._title_match("绿湖噩梦", "绿湖疆梦")
    assert APCardFinder._title_match("圣火纪行：东区黎明", "圣纪行：东区黎明")
    assert APCardFinder._title_match("疯癫与文明", "疯癫与明")
    assert APCardFinder._title_match("唐人街影话", "唐街影话")
    assert APCardFinder._title_match("朔日手记", "朔手记")
    assert APCardFinder._title_match("朔日手记", "朔记")
    assert APCardFinder._title_match("朔日手记", "朔日记")
    assert APCardFinder._title_match("7号往事", "往事")
    assert APCardFinder._title_match("7号往事", "号往事")
    assert APCardFinder._title_match("行于漫漫长路上", "行於漫漫长路上")
    assert not APCardFinder._title_match("两人的同谋", "Fv下长")
    assert not APCardFinder._title_match("两人的同谋", "往事")


def test_auto_promotion_card_signature_normalizes_ocr_variants():
    assert APCardFinder._signature_text("行於漫漫长路上") == "行于漫漫长路上"


def test_auto_promotion_stage_number_filters_ocr_noise():
    analyzer = APMapAnalyze()

    assert analyzer._parse_stage_number("01", [200, 560, 24, 20]) == (
        1,
        [200, 560, 24, 20],
    )
    assert analyzer._parse_stage_number("A1333", [200, 560, 48, 20]) == (
        13,
        [200, 560, 48, 20],
    )
    assert analyzer._parse_stage_number("0", [200, 560, 24, 20]) is None
    assert analyzer._parse_stage_number("70", [200, 560, 24, 20]) is None
    assert analyzer._parse_stage_number("75+", [200, 560, 24, 20]) is None
    assert analyzer._parse_stage_number("76", [200, 560, 24, 20]) is None
