"""魔精诈唬牌（WeShared）：决策纯函数、识别辅助与 pipeline 契约。

概率口径以「右上『剩余』含我自己的手牌」为前提 —— 确认者必须扣掉已知手牌，
声明者侧用不扣手牌的 naive 口径作为下家决策代理（阈值就是按这个口径标定的）。
"""

import ast
import json
from pathlib import Path

import custom.action.weshared as module
import numpy as np
import pytest
from custom.action.weshared import (
    BLUE,
    BROWN,
    CLAIM_MODES,
    CLAIM_THRESHOLD,
    DEFAULT_MAX_GAMES,
    DEFAULT_MODE,
    GAME_SCORE_ROI,
    GREEN,
    HAND_NODES,
    MAX_CLAIM,
    MIN_CLAIM,
    MODE_FULL,
    MODE_ONCE,
    MY_HP_MAX,
    SCORE_MAX_WIDTH,
    TARGET_NODES,
    WILD,
    ClaimPlan,
    Counts,
    RevealState,
    WeSharedTurnLoop,
    _click,
    _game_over_line,
    _param_int,
    _param_str,
    _summary_line,
    _with_retries,
    apply_reveal,
    claim_plan,
    claimer_opponent_belief,
    confirm_choice,
    confirm_probability,
    confirmer_probability,
    counts_from_suits,
    digit_roi,
    parse_claim_k,
    parse_first_int,
    potion_is_decisive,
    reveal_advanced,
    reveal_outcomes,
    score_cap_reached,
    slot_index,
    truth_probability,
    wants_potion,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = PROJECT_ROOT / "resource" / "base" / "pipeline" / "activity" / "WeShared.json"
IMAGE_DIR = PROJECT_ROOT / "resource" / "base" / "image"
ACTION_MODULE_PATH = PROJECT_ROOT / "agent" / "custom" / "action" / "weshared.py"

# 实测开局参数：剩余 = 棕5 蓝5 绿5 万3，目标花色 = 绿
OPENING = Counts(brown=5, blue=5, green=5, wild=3)
# 开局「剩余」里合法牌 = 目标绿 5 + 万能 3
OPENING_LEGAL = 8
OPENING_TOTAL = 18


def test_confirmer_subtracts_own_hand() -> None:
    """确认者扣掉自己手牌后的 P —— 四组数值全部对过真机口径。"""
    naive = confirmer_probability(OPENING, GREEN, 2, None)
    assert naive == pytest.approx(28 / 153, abs=1e-9)
    assert naive == pytest.approx(0.1830, abs=5e-5)

    one_two_two_one = confirmer_probability(OPENING, GREEN, 2, Counts(1, 2, 2, 1))
    assert one_two_two_one == pytest.approx(10 / 66, abs=1e-9)

    three_wild = confirmer_probability(OPENING, GREEN, 2, Counts(0, 0, 0, 3))
    assert three_wild == pytest.approx(10 / 105, abs=1e-9)

    four_green_two_wild = confirmer_probability(OPENING, GREEN, 2, Counts(0, 0, 4, 2))
    assert four_green_two_wild == pytest.approx(1 / 66, abs=1e-9)


@pytest.mark.parametrize(
    ("hand", "expected", "ratio"),
    [
        (None, 28 / 153, 1.00),
        (Counts(1, 2, 2, 1), 10 / 66, 0.83),
        (Counts(0, 0, 0, 3), 10 / 105, 0.52),
        (Counts(0, 0, 4, 2), 1 / 66, 0.08),
    ],
)
def test_confirmer_hand_subtraction_ratios(hand: Counts | None, expected: float, ratio: float) -> None:
    """手里的合法牌越多，对手诈唬概率越高；相对 naive 的倍率要对得上实测表。"""
    probability = confirmer_probability(OPENING, GREEN, 2, hand)
    assert probability == pytest.approx(expected, abs=1e-9)
    assert probability / confirmer_probability(OPENING, GREEN, 2, None) == pytest.approx(ratio, abs=5e-3)


def test_revealed_legal_card_uses_bayes_form() -> None:
    """翻开一张合法牌后走 C(L'-1, k-1) / C(N'-1, k-1)，不是字面的 C(L'-1, k)。"""
    assert truth_probability(OPENING, GREEN, 2, revealed=1) == pytest.approx(7 / 17, abs=1e-9)
    assert truth_probability(OPENING, GREEN, 2, hand=Counts(1, 2, 2, 1), revealed=1) == pytest.approx(4 / 11, abs=1e-9)


def test_revealed_illegal_card_is_certain_lie() -> None:
    """合法牌数没有减少 → 翻开的这张非法，声明必假，P 直接归零。"""
    legal_reveal = apply_reveal(RevealState(), OPENING_LEGAL, OPENING_LEGAL - 1)
    assert legal_reveal == RevealState(revealed=1, illegal=False)

    illegal_reveal = apply_reveal(RevealState(), OPENING_LEGAL, OPENING_LEGAL)
    assert illegal_reveal == RevealState(revealed=1, illegal=True)
    assert confirm_probability(OPENING, GREEN, 2, None, illegal_reveal) == 0.0

    # 已经翻出过非法牌后，后续翻牌不改变「必假」的结论
    still_illegal = apply_reveal(illegal_reveal, OPENING_LEGAL, OPENING_LEGAL - 1)
    assert still_illegal == RevealState(revealed=2, illegal=True)
    assert confirm_probability(OPENING, GREEN, 2, None, still_illegal) == 0.0


def test_truth_probability_decreases_with_k() -> None:
    """P(k) 对 k 单调递减 —— 这是「说真话就把 k 拉大」的依据。"""
    probabilities = [truth_probability(OPENING, GREEN, k) for k in range(MIN_CLAIM, MAX_CLAIM + 1)]
    assert probabilities == sorted(probabilities, reverse=True)
    assert probabilities[0] == pytest.approx(28 / 153, abs=1e-9)


def test_truth_probability_handles_degenerate_inputs() -> None:
    """牌堆不够、或已全部翻开时不能抛异常。"""
    assert truth_probability(Counts(brown=1, blue=0, green=0, wild=0), GREEN, 2) == 0.0
    assert truth_probability(OPENING, GREEN, 2, revealed=2) == 1.0
    assert truth_probability(Counts(), GREEN, 2) == 0.0


def test_claimer_plays_truth_with_max_k_when_opponent_would_doubt() -> None:
    """n_legal=3 且 P_naive(3) 低于阈值 → 出 3 张真牌（下家会质疑，我们赢）。"""
    hand = [GREEN, GREEN, WILD, BROWN, BLUE, BROWN]
    plan = claim_plan(hand, OPENING, GREEN)
    assert claimer_opponent_belief(OPENING, GREEN, 3) < CLAIM_THRESHOLD
    assert plan.kind == "truth"
    assert plan.size == 3
    assert set(plan.slots) <= {0, 1, 2}
    assert plan.probability == pytest.approx(truth_probability(OPENING, GREEN, 3), abs=1e-9)


def test_claimer_bluffs_two_when_opponent_would_trust_a_truthful_claim() -> None:
    """n_legal=3 但 P_naive(3) 高于阈值（下家会信任）→ 出 2 张非合法牌诈唬。"""
    stacked = Counts(brown=2, blue=0, green=5, wild=1)
    hand = [GREEN, GREEN, WILD, BROWN, BROWN, BLUE]
    assert claimer_opponent_belief(stacked, GREEN, 3) > CLAIM_THRESHOLD

    plan = claim_plan(hand, stacked, GREEN)
    assert plan.kind == "bluff"
    assert plan.size == MIN_CLAIM
    assert set(plan.slots) <= {3, 4, 5}


def test_claimer_bluffs_two_when_truth_is_impossible() -> None:
    """只有 1 张合法牌（凑不出 2 张真话）→ 出 2 张非合法牌诈唬。"""
    hand = [GREEN, BROWN, BLUE, BROWN, BLUE, BROWN]
    plan = claim_plan(hand, OPENING, GREEN)
    assert plan.kind == "bluff"
    assert plan.size == MIN_CLAIM
    assert set(plan.slots) <= {1, 2, 3, 4, 5}


def test_claimer_bluffs_two_when_hand_has_no_legal_card() -> None:
    """一张合法牌都没有 → 仍然出 2 张非合法牌诈唬。"""
    hand = [BROWN, BLUE, BROWN, BLUE, BROWN, BLUE]
    plan = claim_plan(hand, OPENING, GREEN)
    assert plan.kind == "bluff"
    assert plan.size == MIN_CLAIM
    assert set(plan.slots) <= {0, 1, 2, 3, 4, 5}


def test_claimer_falls_back_to_truth_when_it_cannot_bluff() -> None:
    """P 高于阈值但一张非合法牌都没有 → 只能退回真话，不能空过。"""
    all_legal = Counts(brown=0, blue=0, green=5, wild=1)
    hand = [GREEN, GREEN, GREEN, WILD, GREEN, GREEN]
    assert claimer_opponent_belief(all_legal, GREEN, MAX_CLAIM) > CLAIM_THRESHOLD

    plan = claim_plan(hand, all_legal, GREEN)
    assert plan.kind == "truth"
    assert plan.size == MAX_CLAIM


def test_claimer_caps_k_at_five() -> None:
    """6 张全是合法牌时 k 封顶 5（规则上限）。"""
    hand = [GREEN, GREEN, GREEN, WILD, WILD, WILD]
    plan = claim_plan(hand, OPENING, GREEN)
    assert plan.kind == "truth"
    assert plan.size == MAX_CLAIM


def test_claimer_uses_naive_belief_not_hand_adjusted() -> None:
    """声明者侧用不扣手牌的 naive 口径预测下家，与确认者的修正式不同源。"""
    hand = [GREEN, GREEN, WILD, BROWN, BLUE, BROWN]
    plan = claim_plan(hand, OPENING, GREEN)
    assert plan.probability == pytest.approx(claimer_opponent_belief(OPENING, GREEN, plan.size), abs=1e-9)
    assert plan.probability != pytest.approx(confirmer_probability(OPENING, GREEN, plan.size, Counts(3, 0, 0, 0)))


def test_claimer_without_any_recognised_card_yields_empty_plan() -> None:
    """手牌一张都没认出来 → 空计划，由调用方兜底。"""
    plan = claim_plan([None] * 6, OPENING, GREEN)
    assert plan == ClaimPlan(kind="truth", slots=(), probability=0.0)
    assert plan.size == 0


def test_confirm_choice_threshold() -> None:
    """P 严格大于阈值才信任；等于阈值走质疑。"""
    assert confirm_choice(0.9) == "trust"
    assert confirm_choice(0.5001) == "trust"
    assert confirm_choice(0.5) == "doubt"
    assert confirm_choice(0.0) == "doubt"


def test_wants_potion_hp_scaled_tiers() -> None:
    """hp_scaled：1 血必用、2 血按带宽、3 血留着、没药水恒不用。"""
    # 1 血（含 0 血已淘汰）濒死必用，与 P 无关
    for probability in (0.0, 0.5, 0.99):
        assert wants_potion(probability, 2, 1) is True
    assert wants_potion(0.9, 1, 0) is True

    # 2 血：|P - 0.5| < HP_SCALED_BAND(0.25)
    assert wants_potion(0.5, 2, 2) is True
    assert wants_potion(0.30, 2, 2) is True  # 差 0.20
    assert wants_potion(0.24, 2, 2) is False  # 差 0.26
    assert wants_potion(0.76, 2, 2) is False

    # 3 血：留着
    assert wants_potion(0.5, 2, 3) is False

    # 没药水：任何血量都不用
    for hp in (0, 1, 2, 3, None):
        assert wants_potion(0.5, 0, hp) is False


def test_wants_potion_falls_back_to_decisive_when_hp_unknown() -> None:
    """读不到血量时退回 decisive：只有翻一张会改变结论才烧药水。"""
    assert wants_potion(0.5, 2, None, decisive=True) is True
    assert wants_potion(0.5, 2, None, decisive=False) is False
    # 血量读得到时 decisive 不参与判断
    assert wants_potion(0.5, 2, 3, decisive=True) is False


def test_reveal_outcomes_illegal_branch_is_certain_lie() -> None:
    """翻出非法牌那一支恒为 0（必假）。"""
    legal_case, illegal_case = reveal_outcomes(OPENING, GREEN, 2, None, RevealState())
    assert legal_case == pytest.approx(7 / 17, abs=1e-9)
    assert illegal_case == 0.0


def test_potion_is_decisive_when_only_one_card_is_left() -> None:
    """只剩最后一张没翻：翻了等于直接给答案，一定算决定性。"""
    assert potion_is_decisive(OPENING, GREEN, 2, None, RevealState(revealed=1)) is True


def test_potion_is_decisive_only_when_a_reveal_flips_the_call() -> None:
    """翻出合法牌后结论不变 → 不烧药水；会翻转 → 烧。"""
    # P=28/153≈0.183 质疑；翻出合法牌后 7/17≈0.412 仍质疑 → 不决定性
    assert potion_is_decisive(OPENING, GREEN, 2, None, RevealState()) is False

    # N=10 L=6：P(2)=15/45≈0.333 质疑；翻出合法牌后 5/9≈0.556 变信任 → 决定性
    borderline = Counts(brown=4, blue=0, green=5, wild=1)
    assert potion_is_decisive(borderline, GREEN, 2, None, RevealState()) is True


def test_heart_nodes_cover_the_heart_row() -> None:
    """亮心 / 暗心两个模板共用同一排 ROI；暗心用来区分「0 血」与「读不到」。"""
    nodes = _nodes()
    for name, template in (
        ("WeSharedMyHp", "WeShared/HeartFull.png"),
        ("WeSharedMyHpEmpty", "WeShared/HeartEmpty.png"),
    ):
        param = nodes[name]["recognition"]["param"]
        assert param["template"] == [template]
        assert param["roi"] == [640, 648, 130, 44]
        assert param["threshold"] == 0.85
        assert "focus" not in nodes[name]


def test_hp_max_matches_the_three_hearts() -> None:
    assert MY_HP_MAX == 3


def test_claim_threshold_sits_inside_measured_opponent_band() -> None:
    """声明者阈值必须取在实测下家确认阈值区间 0.125~0.183 之内。"""
    assert 0.125 <= CLAIM_THRESHOLD <= 0.183


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("阿夫西维声称这3张牌都是毛斗篷", 3),
        ("阿夫西维声称这2张牌都是莴苣叶", 2),
        ("野树莓声称这5张牌都是缝衣针", 5),
        ("请选择2~5张牌声明为", None),
        ("声称这6张牌都是万能", None),
        ("", None),
    ],
)
def test_parse_claim_k(text: str, expected: int | None) -> None:
    assert parse_claim_k(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("剩余次数：0", 0), ("剩余次数：2", 2), ("3450", 3450), ("5", 5), ("无", None)],
)
def test_parse_first_int(text: str, expected: int | None) -> None:
    assert parse_first_int(text) == expected


@pytest.mark.parametrize(
    ("box_x", "expected"),
    [(310, 0), (428, 1), (546, 2), (664, 3), (781, 4), (899, 5), (902, 5), (0, None), (1200, None)],
)
def test_slot_index(box_x: int, expected: int | None) -> None:
    """模板左边界 + 28 = 槽心 x；实测第 6 槽会右偏 3px，容忍范围内。"""
    assert slot_index(box_x) == expected


def test_counts_from_suits_ignores_unknown_slots() -> None:
    assert counts_from_suits([GREEN, GREEN, WILD, None, BROWN, None]) == Counts(brown=1, blue=0, green=2, wild=1)
    assert counts_from_suits([None] * 6) == Counts()
    assert counts_from_suits([]) == Counts()


def test_counts_minus_clamps_at_zero() -> None:
    """识别抖动导致手牌比剩余还多时不能出现负计数。"""
    assert Counts(1, 2, 3, 4).minus(Counts(2, 0, 5, 1)) == Counts(0, 2, 0, 3)


def _load_pipeline() -> dict[str, object]:
    return json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))


def _nodes() -> dict[str, dict[str, object]]:
    raw = _load_pipeline()
    return {name: node for name, node in raw.items() if isinstance(node, dict)}


def _custom_action_of(node: dict[str, object]) -> str | None:
    action = node.get("action")
    if not isinstance(action, dict):
        return None
    param = action.get("param")
    if not isinstance(param, dict):
        return None
    name = param.get("custom_action")
    return name if isinstance(name, str) else None


def _custom_param_of(node: dict[str, object]) -> dict[str, object]:
    action = node.get("action")
    if not isinstance(action, dict):
        return {}
    param = action.get("param")
    if not isinstance(param, dict):
        return {}
    custom = param.get("custom_action_param")
    return custom if isinstance(custom, dict) else {}


def test_pipeline_file_exists_and_entry_node_is_we_shared() -> None:
    assert PIPELINE_PATH.is_file()
    assert "WeShared" in _nodes()


def test_pipeline_contract_params_have_expected_defaults() -> None:
    """另一子任务依赖的固定契约：节点名与两个默认参数。"""
    nodes = _nodes()
    assert _custom_param_of(nodes["WeSharedScoreCheck"])["score_cap"] == 9000
    assert _custom_param_of(nodes["WeSharedTurnLoop"])["max_games"] == 50


def test_custom_action_name_matches_node_name() -> None:
    """仓库约定：自定义动作名必须与 pipeline 节点名一致。"""
    for name, node in _nodes().items():
        custom = _custom_action_of(node)
        if custom is not None:
            assert custom == name


def test_pipeline_next_references_existing_nodes() -> None:
    """next / on_error 的目标必须在本文件里定义；[JumpBack] 引用的跨文件公共节点除外。"""
    nodes = _nodes()
    external = {"CheckStopping", "ReturnMain", "ObtainedAwards"}
    missing: list[str] = []
    for name, node in nodes.items():
        for key in ("next", "on_error"):
            targets = node.get(key)
            if not isinstance(targets, list):
                continue
            for target in targets:
                if not isinstance(target, str):
                    continue
                bare = target.removeprefix("[JumpBack]")
                if bare not in nodes and bare not in external:
                    missing.append(f"{name}.{key} -> {target}")
    assert not missing, f"引用了未定义的节点: {missing}"


def test_pipeline_marks_public_nodes_as_jump_back() -> None:
    """复用性高的公共节点必须带 [JumpBack] 前缀，否则回跳后会断链。"""
    nodes = _nodes()
    for node in nodes.values():
        targets = node.get("next")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if isinstance(target, str) and target in {"ReturnMain", "ObtainedAwards"}:
                assert target.startswith("[JumpBack]"), f"公共节点 {target} 缺少 [JumpBack] 前缀"


def test_pipeline_recognition_nodes_exist_for_runtime_lookups() -> None:
    """自定义动作里写死的节点名必须真的在 pipeline 里，否则运行期 run_recognition 会空转。"""
    nodes = _nodes()
    referenced = [*TARGET_NODES, *HAND_NODES]
    for attribute in (
        "ENTRY_NODE",
        "COUNT_NODE",
        "SCORE_NODE",
        "CLAIM_BAR_NODE",
        "POTION_LEFT_NODE",
        "CONFIRM_PHASE_NODE",
        "PICK_PROMPT_NODE",
        "ROUND_BANNER_NODE",
        "GAME_OVER_NODE",
        "START_GAME_NODE",
        "CONFIRM_PLAY_NODE",
        "TRUST_NODE",
        "DOUBT_NODE",
        "POTION_NODE",
        "SCORE_CHECK_NODE",
        "TURN_LOOP_NODE",
    ):
        referenced.append(getattr(module, attribute))
    for name in referenced:
        assert name in nodes, f"{name} 不在 pipeline 里"


def test_pipeline_templates_exist_on_disk() -> None:
    """模板路径用正斜杠且文件真实存在（含 WeShared/ 目录）。"""
    templates: list[str] = []
    for node in _nodes().values():
        recognition = node.get("recognition")
        if not isinstance(recognition, dict):
            continue
        param = recognition.get("param")
        if not isinstance(param, dict):
            continue
        template = param.get("template")
        if isinstance(template, str):
            templates.append(template)
        elif isinstance(template, list):
            templates.extend(item for item in template if isinstance(item, str))
    assert templates, "pipeline 里没有任何模板"
    for template in templates:
        assert "\\" not in template
        assert (IMAGE_DIR / template).is_file(), f"缺少模板图 {template}"


def test_game_gate_always_allows_the_first_game(monkeypatch: pytest.MonkeyPatch) -> None:
    """第一局之前 games_played == 0，门控恒放行（哪怕上限配成 0，也至少打一局）。"""
    for limit in (0, 1, 50):
        monkeypatch.setattr(WeSharedTurnLoop, "games_played", 0)
        monkeypatch.setattr(WeSharedTurnLoop, "max_games", limit)
        assert WeSharedTurnLoop.gate_reached() is False


def test_game_gate_stops_once_max_games_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    """full 模式：打满 max_games 局后门控生效 —— 必须在 WeSharedStartGame 之前停下。"""
    monkeypatch.setattr(WeSharedTurnLoop, "mode", MODE_FULL)
    monkeypatch.setattr(WeSharedTurnLoop, "max_games", 2)
    for played, expected in ((1, False), (2, True), (3, True)):
        monkeypatch.setattr(WeSharedTurnLoop, "games_played", played)
        assert WeSharedTurnLoop.gate_reached() is expected


def test_once_mode_stops_after_a_single_game(monkeypatch: pytest.MonkeyPatch) -> None:
    """once 模式：打完 1 局就停，与 max_games 无关。"""
    monkeypatch.setattr(WeSharedTurnLoop, "mode", MODE_ONCE)
    monkeypatch.setattr(WeSharedTurnLoop, "max_games", 50)
    monkeypatch.setattr(WeSharedTurnLoop, "games_played", 0)
    assert WeSharedTurnLoop.game_limit() == 1
    assert WeSharedTurnLoop.gate_reached() is False

    monkeypatch.setattr(WeSharedTurnLoop, "games_played", 1)
    assert WeSharedTurnLoop.gate_reached() is True


def test_mode_defaults_to_full_and_rejects_unknown_values() -> None:
    """mode 缺省或非法都回落 full（不抛异常）；合法值原样返回。"""
    assert _param_str({}, "mode", DEFAULT_MODE, CLAIM_MODES) == MODE_FULL
    assert _param_str({"mode": "full"}, "mode", DEFAULT_MODE, CLAIM_MODES) == MODE_FULL
    assert _param_str({"mode": "once"}, "mode", DEFAULT_MODE, CLAIM_MODES) == MODE_ONCE
    for bad in ("ONCE", "always", "", None, 1, True):
        assert _param_str({"mode": bad}, "mode", DEFAULT_MODE, CLAIM_MODES) == MODE_FULL


def test_mode_and_max_games_coexist_in_one_param_object() -> None:
    """custom_action_param 里同时给出 max_games 与 mode 时互不覆盖。"""
    params = {"max_games": 7, "mode": MODE_ONCE}
    assert _param_int(params, "max_games", DEFAULT_MAX_GAMES) == 7
    assert _param_str(params, "mode", DEFAULT_MODE, CLAIM_MODES) == MODE_ONCE


def test_reset_task_clears_gate_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WeSharedTurnLoop, "games_played", 7)
    monkeypatch.setattr(WeSharedTurnLoop, "max_games", 3)
    monkeypatch.setattr(WeSharedTurnLoop, "mode", MODE_ONCE)
    monkeypatch.setattr(WeSharedTurnLoop, "hand", Counts(1, 1, 1, 1))
    monkeypatch.setattr(WeSharedTurnLoop, "previous_total", 12)

    WeSharedTurnLoop.reset_task()

    assert WeSharedTurnLoop.games_played == 0
    assert WeSharedTurnLoop.max_games == DEFAULT_MAX_GAMES
    assert WeSharedTurnLoop.mode == DEFAULT_MODE
    assert WeSharedTurnLoop.hand is None
    assert WeSharedTurnLoop.previous_total == 0
    assert WeSharedTurnLoop.gate_reached() is False


def test_score_check_runs_before_any_start_game_click() -> None:
    """结构不变式：WeSharedStartGame 只能由 WeSharedScoreCheck 引出。

    这样「诈唬分达标」和「局数超限」两道门控一定在**点第一次「开始游戏」之前**生效 ——
    实测点第一次就已经进入对局，之后退出会被算作放弃本局。
    """
    callers = [
        name
        for name, node in _nodes().items()
        if isinstance(node.get("next"), list) and "WeSharedStartGame" in node["next"]
    ]
    # 自身那条是「点击没被响应就再点一次」的重试出口，不算别的节点引进来
    assert sorted(set(callers) - {"WeSharedStartGame"}) == ["WeSharedScoreCheck"]


def test_game_gate_value_comes_from_turn_loop_node() -> None:
    """max_games 仍挂在 WeSharedTurnLoop 上（task 的 override 目标不变），由它发布给门控。"""
    param = _custom_param_of(_nodes()["WeSharedTurnLoop"])
    assert param["max_games"] == DEFAULT_MAX_GAMES
    assert DEFAULT_MAX_GAMES == 50


def test_entry_navigation_priority_order() -> None:
    """入口 next 按「越具体的界面越靠前」排：活动页 > 活动总览 > 主界面 > 回主界面兜底。"""
    assert _nodes()["WeShared"]["next"] == [
        "CheckStopping",
        "WeSharedEventHome",
        "WeSharedNavOverview",
        "WeSharedNavHome",
        "[JumpBack]ReturnMain",
    ]


def test_nav_nodes_form_a_linear_chain() -> None:
    """主界面 → 书页与小憩 → 活动页：每个导航节点先指向下一站，末尾留自身做点击重试。"""
    nodes = _nodes()
    assert nodes["WeSharedNavHome"]["next"] == ["CheckStopping", "WeSharedNavOverview", "WeSharedNavHome"]
    assert nodes["WeSharedNavOverview"]["next"] == ["CheckStopping", "WeSharedEventHome", "WeSharedNavOverview"]


def test_nav_home_clicks_the_third_top_left_icon() -> None:
    """主界面左上角第三个图标（高礼帽 + 摊开的书）点下去直接进「书页与小憩」。

    ROI 必须留足纵向余量：图标中心实测在主界面两帧里差约 30px（nav_main y≈35、
    真机失败帧 y≈65），ROI 高 80 时纵向最多滑到 y=26，够不到真机的 y=38 命中框。
    """
    node = _nodes()["WeSharedNavHome"]
    recognition = node["recognition"]
    assert isinstance(recognition, dict)
    param = recognition["param"]
    assert isinstance(param, dict)
    assert param["template"] == ["WeShared/NavHomeHub.png"]
    assert param["roi"] == [280, 0, 160, 140]
    assert param["threshold"] == 0.8
    action = node["action"]
    assert isinstance(action, dict)
    assert action["param"]["target"] is True


def test_click_nodes_follow_the_recognition_box() -> None:
    """有识别框的点击节点不写死坐标（界面会漂移），一律点识别框中心。"""
    offenders: list[str] = []
    for name, node in _nodes().items():
        action = node.get("action")
        if not isinstance(action, dict) or action.get("type") != "Click":
            continue
        if not isinstance(node.get("recognition"), dict):
            continue
        param = action.get("param")
        target = param.get("target") if isinstance(param, dict) else None
        if target is not None and target is not True:
            offenders.append(f"{name} target={target}")
    assert not offenders, f"这些点击节点写死了坐标: {offenders}"


def test_game_over_is_an_anchor_and_exit_has_its_own_click() -> None:
    """游戏结束只做识别锚点（自定义动作也用它判本局结束），退出由 WeSharedExitGame 点。"""
    nodes = _nodes()
    assert "action" not in nodes["WeSharedGameOver"]
    assert nodes["WeSharedGameOver"]["next"] == ["CheckStopping", "WeSharedExitGame"]
    assert nodes["WeSharedExitGame"]["next"][:3] == ["CheckStopping", "WeSharedClaimReward", "WeSharedScoreCheck"]
    assert nodes["WeSharedExitGame"]["next"][-1] == "WeSharedExitGame"
    assert nodes["WeSharedExitGame"]["action"]["param"]["target"] is True


STOP_AWARE_NODES = (
    "WeShared",
    "WeSharedNavHome",
    "WeSharedNavOverview",
    "WeSharedEventHome",
    "WeSharedClaimReward",
    "WeSharedScoreCheck",
    "WeSharedStartGame",
    "WeSharedDeckOverview",
    "WeSharedTurnLoop",
    "WeSharedGameOver",
    "WeSharedExitGame",
)


def test_looping_nodes_check_stopping_first() -> None:
    """点「停止任务」要立刻收手：按仓库惯例把共享的 `CheckStopping` 放 next 第一位。

    `general.json` 定义该节点，`activity/auto_trail.json` 的 `AutoTrail.next` 就是
    `["CheckStopping", …]`。自定义动作内部的轮询循环则直接查 `context.tasker.stopping`
    （同 `eight_bit.py`）—— 两处都到位，点了停止才不会继续截图、继续点屏幕。
    """
    nodes = _nodes()
    for name in STOP_AWARE_NODES:
        assert nodes[name]["next"][0] == "CheckStopping", f"{name} 的 next 第一位应是 CheckStopping"


def test_score_roi_covers_the_whole_number() -> None:
    """诈唬分 ROI 左边界必须到 x=15：旧 ROI [55,628,52,26] 会把首位数字切掉（3660 读成 660）。"""
    param = _nodes()["WeSharedScore"]["recognition"]["param"]
    assert param["roi"] == [15, 620, 130, 42]


def test_no_node_raises_a_focus_popup() -> None:
    """MXU 把 focus 渲染成底部弹窗；用户只要右侧运行日志，所以 pipeline 里一个都不能留。"""
    offenders = [name for name, node in _nodes().items() if "focus" in node]
    assert offenders == [], f"这些节点还带 focus 弹窗: {offenders}"


def test_log_lines_never_mention_the_mode() -> None:
    """once / full 是内部参数，不能出现在给用户看的文案里。"""
    for builder in (
        _game_over_line(210, 2),
        _game_over_line(None, 2),
        _summary_line(4440, 9000, 2),
        _summary_line(9200, 9000, 5),
        _summary_line(None, 9000, 1),
        _summary_line(300, 0, 1),
    ):
        lowered = builder.lower()
        assert "once" not in lowered
        assert "full" not in lowered
        assert "模式" not in builder


def test_game_over_line_carries_score_and_count() -> None:
    assert _game_over_line(210, 2) == "结束单轮游戏：本局 +210 分，已刷 2 次"
    assert "未知" in _game_over_line(None, 3)
    assert "已刷 3 次" in _game_over_line(None, 3)


def test_summary_line_reports_whether_the_cap_was_hit() -> None:
    assert _summary_line(9200, 9000, 4) == "任务结束，总共刷了 4 次（诈唬分 9200/9000，已达标）"
    assert _summary_line(4440, 9000, 2) == "任务结束，总共刷了 2 次（诈唬分 4440/9000，未达标）"
    # 没配上限（cap <= 0）就只报次数
    assert _summary_line(300, 0, 1) == "任务结束，总共刷了 1 次"
    # 分数读不到时也不瞎报达标
    assert _summary_line(None, 9000, 1) == "任务结束，总共刷了 1 次"


def test_score_cap_of_zero_means_no_cap() -> None:
    """cap <= 0 表示没配上限：不能在开打前就把任务结束掉（与 _summary_line 口径一致）。"""
    assert score_cap_reached(12330, 0) is False
    assert score_cap_reached(12330, -1) is False
    assert score_cap_reached(None, 9000) is False
    assert score_cap_reached(8999, 9000) is False
    assert score_cap_reached(9000, 9000) is True
    assert score_cap_reached(12330, 9000) is True


def test_potion_reveal_requires_the_remaining_total_to_drop() -> None:
    """药水翻牌要以「剩余总数减少」为生效判据。

    点击没生效、或计数还没刷新时，读到的还是翻牌前的值。把它当成「翻出非法牌」会让
    P(真) 归零、必然质疑，还白扣一瓶药水。
    """
    assert reveal_advanced(18, Counts(brown=5, blue=5, green=5, wild=2)) is True
    # 计数没变 = 这次没翻开
    assert reveal_advanced(18, Counts(brown=5, blue=5, green=5, wild=3)) is False
    # 剩余回涨 = 换圈重发，也不该继续烧药水
    assert reveal_advanced(18, Counts(brown=5, blue=5, green=6, wild=3)) is False
    assert reveal_advanced(18, None) is False


def test_score_cap_description_does_not_claim_it_is_mode_specific() -> None:
    """分数上限与刷取模式无关：两种模式都会生效，文案不能只说其中一种。"""
    for name in ("zh_cn", "en_us"):
        data = json.loads((PROJECT_ROOT / "locales" / f"{name}.json").read_text(encoding="utf-8"))
        desc = data["Option.WeShared.ScoreCap.desc"]
        assert "跑到满分" not in desc, desc
        assert "Farm to Full Score" not in desc, desc


class _FakeJob:
    def wait(self) -> "_FakeJob":
        return self

    def get(self) -> str:
        return "fake-frame"


class _FakeController:
    def post_screencap(self) -> _FakeJob:
        return _FakeJob()


class _FakeTasker:
    controller = _FakeController()


class _FakeContext:
    tasker = _FakeTasker()


def test_with_retries_recovers_after_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """读数失败会换新帧重试，动画期偶发读空不该判死。"""
    monkeypatch.setattr(module, "READ_RETRY_DELAY", 0.0)
    seen: list[str] = []

    def read(frame: str) -> int | None:
        seen.append(frame)
        return 7 if len(seen) == 3 else None

    assert _with_retries(_FakeContext(), "first-frame", read, "测试字段") == 7
    assert len(seen) == 3


def test_with_retries_gives_up_and_names_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "READ_RETRY_DELAY", 0.0)
    calls: list[str] = []

    def read(frame: str) -> int | None:
        calls.append(frame)
        return None

    assert _with_retries(_FakeContext(), "first-frame", read, "测试字段") is None
    assert len(calls) == module.READ_ATTEMPTS


def test_click_nodes_retry_themselves_when_the_click_does_not_register() -> None:
    """点击没被游戏响应时，节点要把自己放到 next 末尾再点一次。

    实测过一次「点开始游戏游戏没反应」：没有自循环就会卡在 WeSharedDeckOverview 等 20s 超时，
    整条任务失败。节点 timeout + rate_limit 负责给重试封顶。
    """
    nodes = _nodes()
    for name in ("WeSharedStartGame", "WeSharedNavHome", "WeSharedNavOverview", "WeSharedExitGame"):
        next_list = nodes[name]["next"]
        assert isinstance(next_list, list)
        assert len(next_list) >= 2, f"{name} 的 next 只有 {next_list}，没有重试出口"
        assert next_list[-1] == name, f"{name} 的 next 末尾应是自身，实际 {next_list}"


class _CountingController:
    def __init__(self) -> None:
        self.captures = 0
        self.clicks = 0

    def post_screencap(self) -> _FakeJob:
        self.captures += 1
        return _FakeJob()

    def post_click(self, x: int, y: int) -> _FakeJob:
        self.clicks += 1
        return _FakeJob()


class _StoppingTasker:
    """stopping 在第 after 次检查后翻成 True，模拟用户中途点「停止任务」。"""

    def __init__(self, controller: _CountingController, after: int) -> None:
        self.controller = controller
        self.after = after
        self.checks = 0

    @property
    def stopping(self) -> bool:
        self.checks += 1
        return self.checks > self.after


class _StoppingContext:
    def __init__(self, tasker: _StoppingTasker) -> None:
        self.tasker = tasker

    def run_recognition(self, *args: object, **kwargs: object) -> None:
        return None


def test_drive_match_exits_promptly_after_the_user_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """点了停止必须立刻退出对局循环。

    不查 context.tasker.stopping 的话，这个循环最长要转 MATCH_TIMEOUT（600s）才结束，
    期间还在不停截图、继续点屏幕 —— 表现就是「任务开始后停不下来」。
    """
    monkeypatch.setattr(module, "POLL_INTERVAL", 0.0)
    controller = _CountingController()
    WeSharedTurnLoop()._drive_match(_StoppingContext(_StoppingTasker(controller, after=2)))
    assert controller.captures <= 4, f"停止后仍在轮询：截图 {controller.captures} 次"


def test_clicks_go_through_while_running() -> None:
    controller = _CountingController()
    _click(_StoppingContext(_StoppingTasker(controller, after=5)), (100, 200))
    assert controller.clicks == 1


def test_no_more_clicks_once_the_user_asks_to_stop() -> None:
    """停止之后不能再碰屏幕：点击全走 _click，在这里挡一道，误触就没了。"""
    controller = _CountingController()
    _click(_StoppingContext(_StoppingTasker(controller, after=0)), (100, 200))
    assert controller.clicks == 0


def test_game_score_roi_covers_four_digits_without_the_decorations() -> None:
    """结算页基础搜索区：留出 4 位数余量，又不伸进两侧的金色藤蔓花纹。

    实测 3 位笔画在 x 785..848 / y 482..506，一位约 21px，所以 4 位数首笔约在 x=764。
    真正喂给识别的框由 digit_roi() 按墨迹收紧，这里只保证基础框「装得下 4 位、够不着花纹」。
    """
    roi = _nodes()["WeSharedGameScore"]["recognition"]["param"]["roi"]
    assert tuple(roi) == GAME_SCORE_ROI, "JSON 的基础框必须和 agent 侧的常量一致"
    left, right = roi[0], roi[0] + roi[2]
    assert left <= 764, f"左边界 {left} 装不下 4 位数（实测首笔在 x=785，一位约 21px）"
    assert 855 <= right <= 880, f"右边界 {right} 出界：<855 装不下 4 位数，>880 会圈进装饰花纹"
    assert roi[3] <= 56, f"高度 {roi[3]} 会吃到相邻行"


def _score_frame(ink: tuple[int, int, int, int] | None) -> np.ndarray:
    """造一帧：只在 ink 指定的绝对矩形里画亮色（模拟数字笔画），其余全暗。"""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    if ink is not None:
        x, y, width, height = ink
        frame[y : y + height, x : x + width] = 240
    return frame


def test_digit_roi_hugs_the_number() -> None:
    """墨迹就是数字本身时，框贴着数字收紧（四周各留 4px），不把整条横幅送给识别。"""
    roi = digit_roi(_score_frame((785, 482, 64, 25)), GAME_SCORE_ROI)
    assert roi == (785 - 4, 482 - 4, 64 + 8, 25 + 8)


def test_digit_roi_gives_up_while_the_number_is_fading_in() -> None:
    """数字还没渐入（这一带全暗）时返回 None，交给 _with_retries 换帧，而不是读成 0。"""
    assert digit_roi(_score_frame(None), GAME_SCORE_ROI) is None


def test_digit_roi_rejects_the_banner_that_precedes_the_panel() -> None:
    """面板出来之前这一带是「诈唬失败」横幅文字，墨迹横跨整个基础框 —— 必须拒掉。

    真机上这一帧被固定框认成了 1300（实际 300），是本节点唯一的错误来源。
    """
    assert digit_roi(_score_frame((745, 470, GAME_SCORE_ROI[2], 40)), GAME_SCORE_ROI) is None
    assert GAME_SCORE_ROI[2] > SCORE_MAX_WIDTH, "基础框必须比数字宽，否则这条用例测不到拒识"


def test_game_score_read_tightens_the_roi_before_recognising() -> None:
    """识别前必须先按墨迹收紧 roi，否则横幅帧会被认成一串数字。"""
    tree = ast.parse(ACTION_MODULE_PATH.read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_read_game_score")
    called = {call.func.id for call in ast.walk(fn) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
    assert "digit_roi" in called, "_read_game_score 必须先调 digit_roi 收紧 roi"
    overrides = [
        call
        for call in ast.walk(fn)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "run_recognition"
        and len(call.args) >= 3
    ]
    assert overrides, "_read_game_score 必须给 run_recognition 传 roi override"


def test_game_score_read_goes_through_retries() -> None:
    """结算数字是渐入的：读空要换帧重试，不能在第一帧上就判「本局积分未知」。"""
    tree = ast.parse(ACTION_MODULE_PATH.read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_read_game_score")
    called = {call.func.id for call in ast.walk(fn) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
    assert "_with_retries" in called, "_read_game_score 必须走 _with_retries，否则结算面板渐入时会读空"


def _logger_calls(level: str) -> list[ast.Call]:
    tree = ast.parse(ACTION_MODULE_PATH.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == level
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            calls.append(node)
    return calls


def test_console_shows_only_the_three_milestones() -> None:
    """console sink 是 INFO 级，MXU 把它渲染进右侧运行日志；warning 一律不许出现。

    运行日志只留三条里程碑：开始单轮游戏 / 结束单轮游戏 / 任务结束，其余全部 debug。
    """
    assert _logger_calls("warning") == [], "warning 也会进运行日志，应降级为 debug"
    infos = _logger_calls("info")
    assert len(infos) == 3, f"运行日志只应有 3 条里程碑，实际 {[ast.unparse(c) for c in infos]}"
    assert any("开始单轮游戏" in ast.unparse(call) for call in infos), "右侧运行日志要能看到「开始单轮游戏」"
    contents = [
        call for call in infos if call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == "content"
    ]
    assert len(contents) == 2, "「结束单轮游戏」「任务结束」应各有一条 logger.info(content)"


def test_console_echoes_never_mention_the_mode() -> None:
    """once / full / 「模式」是内部参数，不能出现在会进前端的 logger.info 里。"""
    for call in _logger_calls("info"):
        source = ast.unparse(call).lower()
        assert "模式" not in source, ast.unparse(call)
        assert "once" not in source, ast.unparse(call)
        assert "full" not in source, ast.unparse(call)


def _registered_custom_actions() -> list[tuple[str, str]]:
    tree = ast.parse(ACTION_MODULE_PATH.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "custom_action"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                found.append((decorator.args[0].value, node.name))
    return found


def test_module_registers_the_three_actions_and_is_in_action_modules() -> None:
    from custom.action import ACTION_MODULES

    registered = _registered_custom_actions()
    assert sorted(name for name, _ in registered) == ["WeShared", "WeSharedScoreCheck", "WeSharedTurnLoop"]
    for action_name, class_name in registered:
        assert action_name == class_name
    assert "weshared" in ACTION_MODULES
