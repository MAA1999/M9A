"""翻斗棋策略表：解析、校验、回落与默认 3.5 行为回归。

默认策略必须与 3.5 版本的硬编码值逐字段一致——改造的目标是把配置搬进数据文件，
不是改变 3.5 的行为。
"""

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# 注意：自定义动作/识别要用生产代码相同的模块名（custom.*）导入，
# 否则同一个文件会被加载两次，AgentServer 会因重复注册直接抛 RuntimeError
from custom.action.critter_crash import (
    DEFAULT_BACK_BUTTON,
    DEFAULT_LEADER_BADGE_OFFSET,
    DEFAULT_LEVEL_BADGE_OFFSET,
    MATCH_SCOPED_HIT_NODES,
    STRATEGY_PATH,
    CCChessboard,
    StrategyError,
    load_strategy,
    parse_strategy,
)
from custom.reco.critter_crash import CCBuyCardRec, CCPickEncounterRec, CCPickLeaderRec
from maa.define import BoxAndScoreResult, OCRResult, RecognitionDetail, Rect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 4.0 是独立策略表，默认不加载；只有 CCResetData 显式指定 strategy_file 才启用
STRATEGY_4_0_PATH = Path("data/critter_crash/strategy-4.0.json")

# 4.0 棋盘 ROI（Lead 实机实测，1280x720；15/15 框在爪印上）
# 相对 3.5 整盘右移约 103/104/109px，行距也变大 —— 3.5 的 ROI 在 4.0 上全部失配。
ROIS_4_0 = [
    [[462, 175, 68, 44], [597, 175, 68, 44], [732, 175, 68, 44], [867, 175, 68, 44], [1005, 175, 68, 44]],
    [[448, 286, 68, 44], [587, 286, 68, 44], [727, 286, 68, 44], [868, 286, 68, 44], [1009, 286, 68, 44]],
    [[433, 406, 68, 44], [578, 406, 68, 44], [723, 406, 68, 44], [868, 406, 68, 44], [1014, 406, 68, 44]],
]

# 当前基线（4.0 唯一策略表）：棋盘 ROI 见上面 ROIS_4_0，棋子白名单按解包 auto_chess id 命名。
BASE_CARDS: dict[str, tuple[int, list[tuple[int, int]]]] = {
    "32123": (3, [(0, 4), (2, 4), (0, 3), (2, 3), (0, 2), (2, 2), (0, 1), (2, 1)]),
    "32607": (1, [(1, 4)]),
    "32122": (2, [(0, 3), (2, 3), (0, 2), (2, 2), (0, 1), (2, 1)]),
    "32124": (1, [(0, 4), (2, 4)]),
    "32126": (1, [(1, 0)]),
}
BASE_CARD_ORDER = ["32123", "32607", "32122", "32124", "32126"]

# 唯一策略表（data/critter_crash/strategy-4.0.json）解析后的基线
BASE_STRATEGY = load_strategy(STRATEGY_PATH)


def _minimal_raw(**overrides: object) -> dict[str, object]:
    """最小可用策略表，用于逐项注入非法值。"""
    raw: dict[str, object] = {
        "version": "test",
        "board": {"rows": 1, "cols": 1, "rois": [[[0, 0, 10, 10]]]},
        "cards": [{"name": "32123", "max_level": 2, "positions": [[0, 0]]}],
    }
    raw.update(overrides)
    return raw


def test_default_strategy_matches_shipped_4_0_table() -> None:
    assert BASE_STRATEGY.version == "4.0"
    assert BASE_STRATEGY.board_rows == 3
    assert BASE_STRATEGY.board_cols == 5
    assert [[list(rect) for rect in row] for row in BASE_STRATEGY.board_rois] == ROIS_4_0

    assert {card.name: (card.max_level, list(card.positions)) for card in BASE_STRATEGY.cards} == BASE_CARDS
    # 顺序即 find_empty_position 的优先级，必须与改造前一致
    assert [card.name for card in BASE_STRATEGY.cards] == BASE_CARD_ORDER

    # 类初始状态是空占位（策略表在 CCResetData 里读盘后才生效）
    assert CCChessboard.board_rois == [[[0, 0, 0, 0]]]
    assert CCChessboard.chess_types == []

    try:
        CCChessboard.apply_strategy(BASE_STRATEGY)
        assert CCChessboard.board_rois == ROIS_4_0
        assert [chess["name"] for chess in CCChessboard.chess_types] == BASE_CARD_ORDER
        for chess in CCChessboard.chess_types:
            assert chess["max_level"] == BASE_CARDS[chess["name"]][0]
            assert [tuple(position) for position in chess["positions"]] == BASE_CARDS[chess["name"]][1]
    finally:
        CCChessboard.apply_strategy(BASE_STRATEGY)


def test_default_strategy_chess_types_keep_tuple_positions() -> None:
    """positions 用 tuple 才能让 `(row, col) in positions` 判等成立。"""
    for chess in CCChessboard.chess_types:
        assert all(isinstance(position, tuple) for position in chess["positions"])


def test_shipped_strategy_file_matches_builtin_default() -> None:
    """仓库里的策略表内容必须等于内置默认值，否则默认行为会随文件漂移。"""
    raw = json.loads((PROJECT_ROOT / STRATEGY_PATH).read_text(encoding="utf-8"))
    loaded = parse_strategy(raw, source=str(STRATEGY_PATH))
    assert loaded == BASE_STRATEGY


def test_unknown_placeholder_cards_are_not_resolvable() -> None:
    """卖出分支删除后，unknown_1/unknown_2 不再是可摆放/可升级的卡。"""
    assert CCChessboard.get_chess_info("unknown_1") == {}
    assert CCChessboard.get_chess_info("unknown_2") == {}
    assert CCChessboard.find_empty_position("unknown_2") is None
    assert CCChessboard.get_chess_info("NotACard") == {}


def test_card_names_follow_award_priority_by_default() -> None:
    assert BASE_STRATEGY.card_names() == tuple(BASE_CARD_ORDER)


def test_card_names_fall_back_to_declaration_order_without_priority() -> None:
    assert parse_strategy(_minimal_raw()).card_names() == ("32123",)


class TestPeopleSpec:
    """选领队页卡位：4.0 全屏 3 卡布局，3.5 缺省时不得改变行为。"""

    def test_default_people_block_matches_4_0_slots(self) -> None:
        people = BASE_STRATEGY.people
        assert people is not None
        assert people.slots == ((215, 355), (640, 355), (1065, 355))

    def test_default_preferred_is_xiao_ye_ni_sai(self) -> None:
        """4.0 唯一策略表里优先棋手是小叶尼塞(30027)。"""
        people = BASE_STRATEGY.people
        assert people is not None
        assert people.preferred == ("30027",)
        assert people.pick_slot(["30013", None, None]) is None
        assert people.pick_slot(["30013", "30027", None]) == 1

    def test_default_refresh_is_none(self) -> None:
        """4.0 选领队页没有刷新按钮 → 跳过刷新分支。"""
        people = BASE_STRATEGY.people
        assert people is not None
        assert people.refresh is None
        assert people.has_refresh() is False

    def test_click_point_maps_slot_index(self) -> None:
        people = BASE_STRATEGY.people
        assert people is not None
        assert people.click_point(0) == (215, 355)
        assert people.click_point(2) == (1065, 355)
        assert people.click_point(3) is None
        assert people.click_point(-1) is None

    def test_pick_slot_prefers_earlier_preferred_id(self) -> None:
        people = parse_strategy(
            _minimal_raw(people={"slots": [[1, 2], [3, 4]], "preferred": ["30013", "30007"]})
        ).people
        assert people is not None
        # 两个候选都在场 → 取 preferred 里靠前的 30013（在 0 号位）
        assert people.pick_slot(["30007", "30013"]) == 1

    def test_pick_slot_uses_slot_order_within_one_preferred_id(self) -> None:
        people = parse_strategy(_minimal_raw(people={"slots": [[1, 2], [3, 4]], "preferred": ["30013"]})).people
        assert people is not None
        # 同一棋手在 0 号位 → 点 0 号位
        assert people.pick_slot(["30013", None]) == 0

    def test_pick_slot_returns_none_when_nothing_matches(self) -> None:
        people = parse_strategy(_minimal_raw(people={"slots": [[1, 2], [3, 4]], "preferred": ["30013"]})).people
        assert people is not None
        assert people.pick_slot(["30007", None]) is None
        assert people.pick_slot([None, None]) is None

    def test_people_section_is_optional(self) -> None:
        """people 段缺失 → None，调用方沿用改造前路径。"""
        assert parse_strategy(_minimal_raw()).people is None

    def test_people_accepts_refresh_roi(self) -> None:
        people = parse_strategy(
            _minimal_raw(people={"slots": [[1, 2]], "preferred": [], "refresh": [10, 20, 30, 40]})
        ).people
        assert people is not None
        assert people.refresh == (10, 20, 30, 40)
        assert people.has_refresh() is True

    def test_people_rejects_empty_slots(self) -> None:
        with pytest.raises(StrategyError, match="people.slots"):
            parse_strategy(_minimal_raw(people={"slots": []}))

    def test_people_rejects_non_string_preferred(self) -> None:
        with pytest.raises(StrategyError, match="people.preferred"):
            parse_strategy(_minimal_raw(people={"slots": [[1, 2]], "preferred": [30013]}))

    def test_people_rejects_malformed_slot(self) -> None:
        with pytest.raises(StrategyError, match=r"people\.slots\[0\]"):
            parse_strategy(_minimal_raw(people={"slots": [[1]]}))

    def test_people_rejects_malformed_refresh(self) -> None:
        with pytest.raises(StrategyError, match="people.refresh"):
            parse_strategy(_minimal_raw(people={"slots": [[1, 2]], "refresh": [1, 2]}))

    def test_people_rejects_non_object(self) -> None:
        with pytest.raises(StrategyError, match="people"):
            parse_strategy(_minimal_raw(people=[1, 2]))


def test_card_names_follow_award_priority_when_declared() -> None:
    raw = _minimal_raw(
        cards=[
            {"name": "32123", "max_level": 2, "positions": [[0, 0]]},
            {"name": "32607", "max_level": 1, "positions": [[0, 0]]},
        ],
        award_priority=["32607", "32123"],
    )
    assert parse_strategy(raw).card_names() == ("32607", "32123")


def test_load_strategy_raises_when_file_missing() -> None:
    """策略表是硬依赖：缺失直接抛，不再静默回落到另一份数据。"""
    with pytest.raises(OSError):
        load_strategy(Path("data/critter_crash/does-not-exist.json"))


def test_load_strategy_raises_on_broken_json(tmp_path: Path) -> None:
    broken = tmp_path / "strategy.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_strategy(broken)


def test_load_strategy_raises_on_invalid_schema(tmp_path: Path) -> None:
    invalid = tmp_path / "strategy.json"
    invalid.write_text(json.dumps(_minimal_raw(board={"rows": 2, "cols": 1, "rois": [[[0, 0, 1, 1]]]})), "utf-8")
    with pytest.raises(StrategyError):
        load_strategy(invalid)


def test_parse_strategy_reports_every_problem_at_once() -> None:
    raw = _minimal_raw(
        version="",
        board={"rows": 0, "cols": 1, "rois": [[[0, 0, 1]]]},
        cards=[{"name": "", "max_level": 0, "positions": []}],
    )
    with pytest.raises(StrategyError) as excinfo:
        parse_strategy(raw)
    message = str(excinfo.value)
    assert "version" in message
    assert "board.rows" in message
    assert "board.rois[0][0]" in message
    assert "cards[0]" in message


def test_parse_strategy_rejects_duplicate_card_names() -> None:
    raw = _minimal_raw(
        cards=[
            {"name": "32123", "max_level": 1, "positions": [[0, 0]]},
            {"name": "32123", "max_level": 1, "positions": [[0, 0]]},
        ]
    )
    with pytest.raises(StrategyError, match="卡名重复"):
        parse_strategy(raw)


def test_parse_strategy_rejects_unknown_award_priority_entry() -> None:
    raw = _minimal_raw(award_priority=["32607"])
    with pytest.raises(StrategyError, match="award_priority"):
        parse_strategy(raw)


def test_parse_strategy_requires_roi_shape_to_match_board() -> None:
    raw = _minimal_raw(board={"rows": 2, "cols": 2, "rois": [[[0, 0, 1, 1], [0, 0, 1, 1]]]})
    with pytest.raises(StrategyError, match="2 行 × 2 列"):
        parse_strategy(raw)


def test_parse_strategy_rejects_non_object_top_level() -> None:
    with pytest.raises(StrategyError, match="顶层应为对象"):
        parse_strategy([])


class TestBoardState:
    """棋盘状态机：改造后行为必须与 3.5 一致。"""

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_board_reset_restores_empty_board(self) -> None:
        CCChessboard.place_chess(0, 0, "32607")
        CCChessboard.board_reset()
        assert CCChessboard.board == [[None] * 5 for _ in range(3)]
        assert CCChessboard.board_chesses == []

    def test_place_chess_respects_position_whitelist(self) -> None:
        assert CCChessboard.place_chess(0, 4, "32123") is True
        # (1,1) 不在鹿蜀(32123)的白名单里
        assert CCChessboard.place_chess(1, 1, "32123") is False
        assert CCChessboard.place_chess(1, 1, "NotACard") is False

    def test_place_chess_rejects_occupied_slot(self) -> None:
        assert CCChessboard.place_chess(0, 4, "32123") is True
        assert CCChessboard.place_chess(0, 4, "32123") is False

    def test_place_chess_rejects_out_of_board_position(self) -> None:
        assert CCChessboard.place_chess(3, 0, "32607") is False
        assert CCChessboard.place_chess(-1, 0, "32607") is False

    def test_find_empty_position_follows_declaration_order(self) -> None:
        assert CCChessboard.find_empty_position("32123") == (0, 4)
        CCChessboard.place_chess(0, 4, "32123")
        assert CCChessboard.find_empty_position("32123") == (2, 4)

    def test_find_empty_position_returns_none_for_unknown_card(self) -> None:
        assert CCChessboard.find_empty_position("NotACard") is None

    def test_upgrade_chess_stops_at_max_level(self) -> None:
        """4.0 的鹿蜀(32123)上限 3 星：再升就不动了。"""
        assert CCChessboard.place_chess(0, 4, "32123") is True
        for _ in range(2):
            assert CCChessboard.upgrade_chess(0, 4) is True
        assert CCChessboard.board[0][4] == {"name": "32123", "level": 3}
        assert CCChessboard.upgrade_chess(0, 4) is False

    def test_upgrade_chess_keeps_board_chesses_in_sync(self) -> None:
        CCChessboard.place_chess(0, 4, "32123")
        CCChessboard.upgrade_chess(0, 4)
        assert CCChessboard.board_chesses[0]["level"] == 2

    def test_can_upgrade_existing_only_for_placed_cards(self) -> None:
        assert CCChessboard.can_upgrade_existing("32123") is False
        CCChessboard.place_chess(0, 4, "32123")
        assert CCChessboard.can_upgrade_existing("32123") is True

    def test_can_upgrade_existing_false_at_max_level(self) -> None:
        assert CCChessboard.place_chess(1, 4, "32607") is True
        assert CCChessboard.can_upgrade_existing("32607") is False

    def test_can_upgrade_existing_false_for_unknown_card(self) -> None:
        assert CCChessboard.can_upgrade_existing("NotACard") is False

    def test_remove_chess_clears_board_and_list(self) -> None:
        CCChessboard.place_chess(0, 4, "32123")
        assert CCChessboard.remove_chess(0, 4) is True
        assert CCChessboard.board[0][4] is None
        assert CCChessboard.board_chesses == []
        assert CCChessboard.remove_chess(0, 4) is False


def test_apply_strategy_resizes_board_and_swaps_card_table() -> None:
    """换策略时棋盘尺寸、ROI、棋子白名单必须一起换，不能留旧状态。"""
    original = CCChessboard.strategy
    try:
        strategy = parse_strategy(
            {
                "version": "4.0-test",
                "board": {
                    "rows": 2,
                    "cols": 2,
                    "rois": [[[1, 2, 3, 4], [5, 6, 7, 8]], [[9, 10, 11, 12], [13, 14, 15, 16]]],
                },
                "cards": [{"name": "NewCard", "max_level": 3, "positions": [[1, 1]]}],
            }
        )
        CCChessboard.place_chess(0, 0, "32607")
        CCChessboard.apply_strategy(strategy)

        assert CCChessboard.board == [[None, None], [None, None]]
        assert CCChessboard.board_chesses == []
        assert CCChessboard.board_rois == [[[1, 2, 3, 4], [5, 6, 7, 8]], [[9, 10, 11, 12], [13, 14, 15, 16]]]
        assert [chess["name"] for chess in CCChessboard.chess_types] == ["NewCard"]
        assert CCChessboard.get_chess_info("32607") == {}
        assert CCChessboard.find_empty_position("NewCard") == (1, 1)
    finally:
        CCChessboard.apply_strategy(original)


def test_reload_strategy_uses_shipped_file() -> None:
    original = CCChessboard.strategy
    try:
        assert CCChessboard.reload_strategy() == BASE_STRATEGY
    finally:
        CCChessboard.apply_strategy(original)


def _hit(box: tuple[int, int, int, int]) -> RecognitionDetail:
    rect = Rect(*box)
    return RecognitionDetail(
        reco_id=1,
        name="fake",
        algorithm="TemplateMatch",
        hit=True,
        box=rect,
        all_results=[],
        filtered_results=[BoxAndScoreResult(rect, 0.9)],
        best_result=BoxAndScoreResult(rect, 0.9),
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


def _miss() -> RecognitionDetail:
    return RecognitionDetail(
        reco_id=1,
        name="fake",
        algorithm="TemplateMatch",
        hit=False,
        box=None,
        all_results=[],
        filtered_results=[],
        best_result=None,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


class _ScriptedContext:
    """按脚本回答识别的 context 桩，记录被询问过的节点名、模板与 ROI 覆盖。"""

    def __init__(self, answers: dict[str, RecognitionDetail | list[RecognitionDetail]]) -> None:
        self.answers = answers
        # 同一节点被按 ROI 逐个询问时（选领队的「已选中」角标），用 ROI 键区分子调用
        self.roi_answers: dict[tuple[int, ...], RecognitionDetail] = {}
        self.asked: list[str] = []
        self.templates: list[str] = []
        self.rois: list[tuple[str, tuple[int, ...]]] = []
        self.tasks: list[str] = []

    def run_recognition(self, name: str, _image: Any, override: dict[str, Any] | None = None) -> RecognitionDetail:
        self.asked.append(name)
        if override and name in override:
            node_override = override[name]
            roi = node_override.get("roi")
            if roi is not None:
                key = tuple(int(value) for value in roi)
                self.rois.append((name, key))
                if key in self.roi_answers:
                    return self.roi_answers[key]
            template = node_override.get("template")
            if isinstance(template, str):
                self.templates.append(template)
                # 模板名映射到答案：CritterCrash/Cards/32123.png → "32123"
                key = template.rsplit("/", 1)[-1].removesuffix(".png")
                scripted = self.answers.get(key, _miss())
                return scripted if isinstance(scripted, RecognitionDetail) else scripted[0]
        scripted = self.answers.get(name, _miss())
        return scripted if isinstance(scripted, RecognitionDetail) else scripted[0]

    def run_task(self, name: str) -> None:
        self.tasks.append(name)


def _ocr_hit(text: str, box: tuple[int, int, int, int] = (520, 392, 240, 50)) -> RecognitionDetail:
    """OCR 命中桩：best_result 要带 text，ocr_text() 才取得到字。"""
    rect = Rect(*box)
    result = OCRResult(rect, 0.95, text)
    return RecognitionDetail(
        reco_id=1,
        name="fake",
        algorithm="OCR",
        hit=True,
        box=rect,
        all_results=[result],
        filtered_results=[result],
        best_result=result,
        raw_detail={},
        raw_image=np.zeros((1, 1, 3), dtype=np.uint8),
        draw_images=[],
    )


def _analyze_buy_card(context: _ScriptedContext) -> Any:
    reco = CCBuyCardRec.__new__(CCBuyCardRec)
    argv = type("Argv", (), {"image": np.zeros((1, 1, 3), dtype=np.uint8)})()
    return reco.analyze(context, argv)  # pyright: ignore[reportArgumentType]


class TestBuyCardPriority:
    """买入决策优先级：改造只是把遍历源换成策略表，优先级本身必须逐条保持。"""

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_buy_pool_follows_strategy_card_order(self) -> None:
        """购买区识别按策略表声明顺序进行，而不是按 chess_types 的其它顺序。"""
        ctx = _ScriptedContext({"CCRemainMoney": _hit((669, 29, 36, 25))})
        _analyze_buy_card(ctx)
        assert ctx.templates == [f"CritterCrash/Cards/{card.name}.png" for card in BASE_STRATEGY.cards]

    def test_buy_prefers_deploy_over_upgrade(self) -> None:
        """有空位时立即部署，不继续找升级候选。"""
        ctx = _ScriptedContext(
            {
                "CCRemainMoney": _hit((669, 29, 36, 25)),
                "32123": _hit((300, 560, 80, 90)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.detail == {"type": 0, "action": 0, "name": "32123"}

    def test_buy_falls_back_to_upgrade_when_board_full(self) -> None:
        """无空位但可升级时返回升级，且不再尝试后续卡。"""
        # Deer 的 positions 全部占满，才会走到升级分支
        for row, col in next(c for c in BASE_STRATEGY.cards if c.name == "32123").positions:
            CCChessboard.place_chess(row, col, "32123")
        assert CCChessboard.find_empty_position("32123") is None
        ctx = _ScriptedContext(
            {
                "CCRemainMoney": _hit((669, 29, 36, 25)),
                "32123": _hit((300, 560, 80, 90)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.detail == {"type": 0, "action": 1, "name": "32123"}

    def test_buy_stops_when_money_insufficient(self) -> None:
        """缪斯币不足时直接放弃，不做任何卡牌识别。"""
        ctx = _ScriptedContext({})
        result = _analyze_buy_card(ctx)
        assert result.box is None
        assert result.detail == {}
        assert ctx.templates == []

    def test_award_usable_card_without_slot_is_skipped(self) -> None:
        """奖励区是白名单卡但既没空位也没得升级：跳过（不再卖出、不再自行开战）。"""
        # Shiva 的 positions 只有 (0,0)/(2,0)，先占满 → 无处安放
        CCChessboard.place_chess(1, 4, "32607")
        ctx = _ScriptedContext(
            {
                "CCBuyCardAwardEmptyRec": _hit((42, 580, 128, 124)),
                "32607": _hit((60, 590, 90, 100)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.box is None
        assert result.detail == {}
        assert ctx.tasks == []

    def test_award_deploys_when_slot_available(self) -> None:
        ctx = _ScriptedContext(
            {
                "CCBuyCardAwardEmptyRec": _hit((42, 580, 128, 124)),
                "32123": _hit((60, 590, 90, 100)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.detail == {"type": 1, "action": 0, "name": "32123"}
        assert result.box is not None

    def test_award_unidentifiable_card_is_skipped(self) -> None:
        """奖励区认不出卡名时直接跳过 —— 4.0 的奖励区卡片拖不动，卖出分支已删除。

        跳过（返回 miss）后由 pipeline 的 next 走到 CCStartCombat 开战。
        """
        ctx = _ScriptedContext({"CCBuyCardAwardEmptyRec": _hit((42, 580, 128, 124))})
        result = _analyze_buy_card(ctx)
        assert result.box is None
        assert result.detail == {}
        assert ctx.tasks == []
        # 不再有「分辨藏品/非藏品」的识别调用
        assert "CCBuyCardAwardTypeRec_Template" not in ctx.asked


class TestStrategy40:
    """4.0 鹿蜀成长流策略表（data/critter_crash/strategy-4.0.json）。

    4.0 是**独立文件、显式 opt-in**，默认绝不加载——3.5 行为不受影响。
    棋子来源：auto_chess id=32123/32121/32122/32125/32126（star 1..3，
    卡包 auto_chess_cardpack id=11001 与 4001301 均命中 5/5）。
    """

    @staticmethod
    def _load() -> object:
        return load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)

    def test_profile_file_parses_and_is_versioned_4_0(self) -> None:
        strategy = self._load()
        assert strategy.version == "4.0"  # type: ignore[attr-defined]

    def test_profile_keeps_3x5_board(self) -> None:
        """4.0 棋盘仍是 3 行 x 5 列（AutoChessEnum.BoardSize + const id1="3#5"）。"""
        strategy = self._load()
        assert strategy.board_rows == 3  # type: ignore[attr-defined]
        assert strategy.board_cols == 5  # type: ignore[attr-defined]

    def test_profile_uses_measured_4_0_board_rois(self) -> None:
        """4.0 ROI 必须是实机实测值：3.5 的 ROI 在 4.0 上整盘右移约 103-109px，会全部失配。"""
        strategy = self._load()
        assert [[list(r) for r in row] for row in strategy.board_rois] == ROIS_4_0  # type: ignore[attr-defined]

    def test_profile_roi_centers_are_self_consistent(self) -> None:
        """每个 ROI 的中心必须等于实测格中心（防手抄坐标错位）。"""
        strategy = self._load()
        centers = [
            (197, [496, 631, 766, 901, 1039]),
            (308, [482, 621, 761, 902, 1043]),
            (428, [467, 612, 757, 902, 1048]),
        ]
        for row_index, (center_y, center_xs) in enumerate(centers):
            for col_index, center_x in enumerate(center_xs):
                x, y, w, h = strategy.board_rois[row_index][col_index]  # type: ignore[attr-defined]
                assert (x + w // 2, y + h // 2) == (center_x, center_y), f"r{row_index}c{col_index}"

    def test_profile_roi_size_matches_3_5(self) -> None:
        """4.0 格子尺寸与 3.5 同为 68x44（Lead 实测），只有位置变。"""
        strategy = self._load()
        for row in strategy.board_rois:  # type: ignore[attr-defined]
            for _x, _y, w, h in row:
                assert (w, h) == (68, 44)

    def test_profile_rois_are_on_screen(self) -> None:
        """ROI 必须落在 1280x720 内，避免拖拽终点越界。"""
        strategy = self._load()
        for row in strategy.board_rois:  # type: ignore[attr-defined]
            for x, y, w, h in row:
                assert 0 <= x and 0 <= y
                assert x + w <= 1280
                assert y + h <= 720

    def test_profile_uses_verified_lushu_core_ids(self) -> None:
        strategy = self._load()
        names = [card.name for card in strategy.cards]  # type: ignore[attr-defined]
        assert names == ["32123", "32607", "32122", "32124", "32126"]

    def test_profile_max_levels_match_star_caps(self) -> None:
        """32123/32121/32122 有 3 星行 → max_level 3；32125/32126 只当 1 级用。"""
        strategy = self._load()
        caps = {card.name: card.max_level for card in strategy.cards}  # type: ignore[attr-defined]
        assert caps == {"32123": 3, "32607": 1, "32122": 2, "32124": 1, "32126": 1}

    def test_profile_frontline_is_col4(self) -> None:
        """col4 = 最前排（报告 §2.4 推断），核心成长棋子优先放 col4。"""
        strategy = self._load()
        deer = next(c for c in strategy.cards if c.name == "32123")  # type: ignore[attr-defined]
        assert deer.positions[0] == (0, 4)
        assert deer.positions[1] == (2, 4)

    def test_profile_award_priority_is_lushu_first(self) -> None:
        strategy = self._load()
        assert strategy.award_priority == ("32123", "32607", "32122", "32124", "32126")  # type: ignore[attr-defined]

    def test_profile_preferred_leaders_are_qu_niang_then_ya_mi(self) -> None:
        """30013 曲娘（鹿蜀流推荐棋手）/ 30061 哑谜（4.0 新）。"""
        strategy = self._load()
        people = strategy.people  # type: ignore[attr-defined]
        assert people is not None
        assert people.preferred == ("30027",)

    def test_profile_does_not_reference_removed_masters(self) -> None:
        """4.0 热更把 30043/30029/30030/30017/30028 从计划组整组摘掉，不可作为优先棋手。"""
        strategy = self._load()
        people = strategy.people  # type: ignore[attr-defined]
        assert people is not None
        removed = {"30043", "30029", "30030", "30017", "30028"}
        assert not (set(people.preferred) & removed)

    def test_profile_pick_slot_selects_xiao_ye_ni_sai(self) -> None:
        """人工攻略指定的棋手是小叶尼塞 30027。"""
        strategy = self._load()
        people = strategy.people  # type: ignore[attr-defined]
        assert people is not None
        # 小叶尼塞在第 1 个卡位
        assert people.pick_slot(["30005", "30027", "30061"]) == 1

    def test_profile_pick_slot_none_when_xiao_ye_ni_sai_absent(self) -> None:
        """该奇遇没给到小叶尼塞时返回 None，由调用方回落模板匹配/重开。"""
        strategy = self._load()
        people = strategy.people  # type: ignore[attr-defined]
        assert people is not None
        # 只有曲娘/哑谜（不含 30027）→ 不选
        assert people.pick_slot(["30061", "30013", "30005"]) is None

    def test_profile_pick_slot_none_when_neither_present(self) -> None:
        """随机 3 选 1 时两个推荐棋手都可能不在场 → 回落模板匹配。"""
        strategy = self._load()
        people = strategy.people  # type: ignore[attr-defined]
        assert people is not None
        assert people.pick_slot(["30005", "30007", "30019"]) is None

    def test_profile_has_no_refresh_button(self) -> None:
        strategy = self._load()
        people = strategy.people  # type: ignore[attr-defined]
        assert people is not None
        assert people.has_refresh() is False

    def test_4_0_profile_is_the_default(self) -> None:
        """4.0 是唯一策略表：内置默认值、仓库文件、默认路径三者一致。"""
        assert BASE_STRATEGY.version == "4.0"
        assert self._load() == BASE_STRATEGY  # type: ignore[attr-defined]
        assert STRATEGY_PATH.as_posix() == STRATEGY_4_0_PATH.as_posix()

    def test_loading_4_0_does_not_mutate_default(self) -> None:
        before = CCChessboard.strategy
        try:
            strategy = self._load()
            CCChessboard.apply_strategy(strategy)  # type: ignore[arg-type]
            assert CCChessboard.strategy.version == "4.0"
            assert [c["name"] for c in CCChessboard.chess_types] == ["32123", "32607", "32122", "32124", "32126"]
            assert CCChessboard.find_empty_position("32123") == (0, 4)
        finally:
            CCChessboard.apply_strategy(before)
        assert CCChessboard.strategy.version == "4.0"
        assert [c["name"] for c in CCChessboard.chess_types] == BASE_CARD_ORDER

    def test_4_0_reload_strategy_is_opt_in_via_path(self) -> None:
        before = CCChessboard.strategy
        try:
            loaded = CCChessboard.reload_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)
            assert loaded.version == "4.0"
        finally:
            CCChessboard.apply_strategy(before)

    def test_missing_strategy_file_raises(self) -> None:
        """策略表缺失 = 任务明确失败，而不是悄悄换一份数据继续跑。"""
        with pytest.raises(OSError):
            load_strategy(Path("data/critter_crash/does-not-exist-4.0.json"))


class TestLevelBadgeOffset:
    """满级角标偏移：默认等于 3.5 硬编码值，可被策略表覆盖以便换版调参。"""

    def test_default_matches_3_5_hardcoded_offset(self) -> None:
        """默认必须是 3.5 的 [-52, -58, 45, 15]，否则 3.5 的满级判定会变。"""
        assert DEFAULT_LEVEL_BADGE_OFFSET == (-52, -58, 45, 15)
        assert BASE_STRATEGY.level_badge_offset is None
        assert BASE_STRATEGY.badge_offset() == (-52, -58, 45, 15)

    def test_4_0_profile_falls_back_to_3_5_offset(self) -> None:
        """4.0 策略表暂未覆盖该偏移（等实机跑一轮再调），故沿用 3.5 值。"""
        strategy = load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)
        assert strategy.badge_offset() == (-52, -58, 45, 15)

    def test_offset_can_be_overridden_from_data(self) -> None:
        strategy = parse_strategy(_minimal_raw(level_badge_offset=[-10, -20, 30, 40]))
        assert strategy.level_badge_offset == (-10, -20, 30, 40)
        assert strategy.badge_offset() == (-10, -20, 30, 40)

    def test_malformed_offset_is_rejected(self) -> None:
        with pytest.raises(StrategyError, match="level_badge_offset"):
            parse_strategy(_minimal_raw(level_badge_offset=[1, 2]))


class TestBuyCardUnder4_0:
    """端到端：切到 4.0 策略后，CCBuyCardRec 必须按 id 模板与 4.0 优先级决策。

    模板路径来自 name=id，所以这里同时锁定「Lead 要裁的模板文件名」。
    """

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_buy_pool_uses_id_named_templates(self) -> None:
        ctx = _ScriptedContext({"CCRemainMoney": _hit((669, 29, 36, 25))})
        _analyze_buy_card(ctx)
        assert ctx.templates == [
            "CritterCrash/Cards/32123.png",
            "CritterCrash/Cards/32607.png",
            "CritterCrash/Cards/32122.png",
            "CritterCrash/Cards/32124.png",
            "CritterCrash/Cards/32126.png",
        ]

    def test_buy_deploys_lushu_to_frontline_col4(self) -> None:
        """鹿蜀第一个空位是 (0,4) = 最前排。"""
        assert CCChessboard.find_empty_position("32123") == (0, 4)

    def test_buy_recognizes_lushu_and_returns_deploy(self) -> None:
        ctx = _ScriptedContext(
            {
                "CCRemainMoney": _hit((669, 29, 36, 25)),
                "32123": _hit((300, 560, 80, 90)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.detail == {"type": 0, "action": 0, "name": "32123"}

    def test_buy_upgrades_lushu_when_its_slots_are_full(self) -> None:
        """鹿蜀 8 个位置占满 → 转为升级候选。"""
        for row, col in next(c for c in CCChessboard.strategy.cards if c.name == "32123").positions:
            CCChessboard.place_chess(row, col, "32123")
        assert CCChessboard.find_empty_position("32123") is None
        ctx = _ScriptedContext(
            {
                "CCRemainMoney": _hit((669, 29, 36, 25)),
                "32123": _hit((300, 560, 80, 90)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.detail == {"type": 0, "action": 1, "name": "32123"}

    def test_shiva_is_capped_at_level_1(self) -> None:
        """坚固石骑士当 1 级用，放上后不再升级。"""
        assert CCChessboard.place_chess(1, 4, "32607") is True
        assert CCChessboard.can_upgrade_existing("32607") is False

    def test_deer_is_capped_at_level_3(self) -> None:
        """鹿蜀上限 3（auto_chess 只有 star 1..3）。"""
        CCChessboard.place_chess(0, 4, "32123")
        for _ in range(2):
            assert CCChessboard.upgrade_chess(0, 4) is True
        assert CCChessboard.upgrade_chess(0, 4) is False
        assert CCChessboard.board[0][4] == {"name": "32123", "level": 3}

    def test_4_0_table_excludes_unlisted_3_5_pieces(self) -> None:
        """4.0 表只保留本流派用到的卡：3.5 的 Cat/Knight/Robot 等不应再被识别或放置。"""
        assert CCChessboard.get_chess_info("Knight") == {}
        assert CCChessboard.get_chess_info("Cat4") == {}
        assert CCChessboard.find_empty_position("Knight") is None
        assert CCChessboard.can_upgrade_existing("Knight") is False

    def test_award_priority_puts_lushu_first(self) -> None:
        """奖励区先找鹿蜀：命中 Deer 时直接部署，不再试后续。"""
        ctx = _ScriptedContext(
            {
                "CCBuyCardAwardEmptyRec": _hit((42, 580, 128, 124)),
                "32123": _hit((60, 590, 90, 100)),
            }
        )
        result = _analyze_buy_card(ctx)
        assert result.detail == {"type": 1, "action": 0, "name": "32123"}
        # 鹿蜀是第一个被询问的模板，命中即返回
        assert ctx.templates[0] == "CritterCrash/Cards/32123.png"


class TestStrategyBoardBounds:
    """棋盘坐标校验：越界坐标会让 find_empty_position / board_rois[row][col] 抛 IndexError。"""

    def test_rejects_out_of_board_card_position(self) -> None:
        raw = _minimal_raw(cards=[{"name": "32123", "max_level": 1, "positions": [[0, 1]]}])
        with pytest.raises(StrategyError, match=r"32123 的位置 \[0, 1\] 超出 1×1 棋盘"):
            parse_strategy(raw)

    def test_rejects_negative_card_position(self) -> None:
        raw = _minimal_raw(cards=[{"name": "32123", "max_level": 1, "positions": [[-1, 0]]}])
        with pytest.raises(StrategyError, match="超出 1×1 棋盘"):
            parse_strategy(raw)

    def test_shipped_profiles_pass_the_bounds_check(self) -> None:
        assert parse_strategy(json.loads((PROJECT_ROOT / STRATEGY_PATH).read_text(encoding="utf-8"))).board_rows == 3
        assert load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH).board_rows == 3

    def test_find_empty_position_ignores_out_of_board_entries(self) -> None:
        """手工注入（测试/热改）的越界 positions 不能把 IndexError 抛进识别回调。"""
        original = CCChessboard.chess_types
        try:
            CCChessboard.apply_strategy(BASE_STRATEGY)
            CCChessboard.chess_types = [{"name": "Bad", "max_level": 1, "positions": [(9, 9), (0, 0)]}]
            assert CCChessboard.find_empty_position("Bad") == (0, 0)
            CCChessboard.chess_types = [{"name": "Bad", "max_level": 1, "positions": [(9, 9)]}]
            assert CCChessboard.find_empty_position("Bad") is None
        finally:
            CCChessboard.chess_types = original


def test_load_strategy_raises_on_invalid_utf8(tmp_path: Path) -> None:
    """策略表写坏编码（非 UTF-8）也要明确失败。"""
    broken = tmp_path / "strategy.json"
    broken.write_bytes(b'{"version": "\xff\xfe not utf-8"}')
    with pytest.raises(UnicodeDecodeError):
        load_strategy(broken)


class TestPeopleBadgeOffset:
    """「已被选中」角标偏移：默认 = 4.0 实测值，可被策略表覆盖以便换版调参。"""

    def test_default_matches_live_measurement(self) -> None:
        """实测：卡位点 (215, 355) 的角标窗口是 [45, 460, 140, 70]（选中 1.0 / 未选 0.40）。"""
        assert DEFAULT_LEADER_BADGE_OFFSET == (-170, 105, 140, 70)
        assert BASE_STRATEGY.people is not None
        assert BASE_STRATEGY.people.badge_offset is None
        assert BASE_STRATEGY.people.badge_roi(0) == [45, 460, 140, 70]

    def test_badge_roi_follows_every_slot(self) -> None:
        people = BASE_STRATEGY.people
        assert people is not None
        assert people.badge_roi(1) == [470, 460, 140, 70]
        assert people.badge_roi(2) == [895, 460, 140, 70]
        assert people.badge_roi(3) is None

    def test_4_0_profile_uses_the_default_offset(self) -> None:
        people = load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH).people
        assert people is not None
        assert people.badge_roi(0) == [45, 460, 140, 70]

    def test_offset_can_be_overridden_from_data(self) -> None:
        people = parse_strategy(_minimal_raw(people={"slots": [[100, 200]], "badge_offset": [-10, -20, 30, 40]})).people
        assert people is not None
        assert people.badge_offset == (-10, -20, 30, 40)
        assert people.badge_roi(0) == [90, 180, 30, 40]

    def test_malformed_badge_offset_is_rejected(self) -> None:
        with pytest.raises(StrategyError, match="people.badge_offset"):
            parse_strategy(_minimal_raw(people={"slots": [[1, 2]], "badge_offset": [1, 2]}))


def _pick_leader(context: _ScriptedContext) -> Any:
    reco = CCPickLeaderRec.__new__(CCPickLeaderRec)
    argv = type("Argv", (), {"image": np.zeros((1, 1, 3), dtype=np.uint8)})()
    return reco.analyze(context, argv)  # pyright: ignore[reportArgumentType]


def _strategy_40(max_reroll: int = 0) -> Any:
    """4.0 策略表 + 指定重摇额度（默认 0，好把兜底路径单独测干净）。"""
    strategy = load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)
    assert strategy.people is not None
    return replace(strategy, people=replace(strategy.people, max_reroll=max_reroll))


class TestPickLeader:
    """选领队：优先棋手 → 退出重摇 → 兜底卡位 0；不在该页/已选中 → miss。

    背景（实机实测 2026-10-16）：没选领队时「进入战斗」是禁用态，点了不响应，任务会在
    选领队页终结（status 4000）。而领队决定卡包→棋子池，随机兜底可能整局买不到鹿蜀，
    所以在没摇到优先棋手时先退出去重摇（有上限），额度用尽才兜底。
    """

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(_strategy_40())

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_misses_when_not_on_select_page(self) -> None:
        """门控：不在选领队页就不给 box（对局页左侧也画着同一张领队立绘）。"""
        ctx = _ScriptedContext({})
        result = _pick_leader(ctx)
        assert result.box is None
        assert ctx.asked == ["CCFlagInSelectPeople"]
        assert ctx.templates == []
        assert ctx.rois == []

    def test_picks_preferred_leader(self) -> None:
        ctx = _ScriptedContext(
            {
                "CCFlagInSelectPeople": _hit((550, 72, 220, 45)),
                "Leaders_30027": _hit((890, 240, 300, 300)),
            }
        )
        result = _pick_leader(ctx)
        assert result.box is not None
        assert result.detail == {"leader": "30027"}
        assert ctx.templates == ["CritterCrash/Leaders_30027.png"]

    def test_preferred_wins_over_already_selected_guard(self) -> None:
        """优先棋手在就点它，不必再等角标判断。"""
        ctx = _ScriptedContext(
            {
                "CCFlagInSelectPeople": _hit((550, 72, 220, 45)),
                "Leaders_30027": _hit((890, 240, 300, 300)),
            }
        )
        ctx.roi_answers[(45, 460, 140, 70)] = _hit((89, 469, 52, 52))
        result = _pick_leader(ctx)
        assert result.detail == {"leader": "30027"}
        assert ctx.rois == []

    def test_falls_back_to_first_slot_when_preferred_absent(self) -> None:
        """没有小叶尼塞时必须兜底选人，否则「进入战斗」禁用、任务死在这一页。"""
        ctx = _ScriptedContext({"CCFlagInSelectPeople": _hit((550, 72, 220, 45))})
        result = _pick_leader(ctx)
        assert result.box == [210, 350, 10, 10]
        assert result.detail == {"fallback": True}
        # 三个卡位都查过「已选中」角标
        assert [name for name, _roi in ctx.rois] == ["CCLeaderSelected_Template"] * 3

    def test_skips_when_slot_already_selected(self) -> None:
        """已经选好了就别再点一次（重复点可能取消选中）。"""
        ctx = _ScriptedContext({"CCFlagInSelectPeople": _hit((550, 72, 220, 45))})
        ctx.roi_answers[(895, 460, 140, 70)] = _hit((941, 469, 52, 52))
        result = _pick_leader(ctx)
        assert result.box is None
        assert result.detail == {"selected": 2}

    def test_misses_without_people_block(self) -> None:
        """3.5 那种没有 people 段的策略表：不读选领队，保持改造前行为。"""
        CCChessboard.apply_strategy(parse_strategy(_minimal_raw()))
        ctx = _ScriptedContext({})
        result = _pick_leader(ctx)
        assert result.box is None
        assert ctx.asked == []
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_fallback_box_center_is_the_first_slot(self) -> None:
        people = CCChessboard.strategy.people
        assert people is not None
        ctx = _ScriptedContext({"CCFlagInSelectPeople": _hit((550, 72, 220, 45))})
        box = _pick_leader(ctx).box
        assert box is not None
        assert (box[0] + box[2] // 2, box[1] + box[3] // 2) == people.click_point(0)


class TestPickLeaderReroll:
    """没摇到优先棋手时退出重摇（有上限）；额度用尽才兜底。

    机制（实机实测）：选领队页点左上返回 → 回主菜单 → 再点「箱中对决」会**重新摇**；
    而点了「进入战斗」之后再退出会回到同一局，所以重摇必须发生在选人之前。
    """

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def _ctx(self) -> _ScriptedContext:
        return _ScriptedContext({"CCFlagInSelectPeople": _hit((550, 72, 220, 45))})

    def test_rerolls_when_preferred_absent_and_budget_left(self) -> None:
        CCChessboard.apply_strategy(_strategy_40(max_reroll=3))
        result = _pick_leader(self._ctx())
        assert result.detail == {"reroll": True}
        # box 中心 = 返回键点击点
        assert result.box == [41, 38, 10, 10]
        assert CCChessboard.rerolls_used.get("leader", 0) == 1

    def test_reroll_box_center_is_the_back_button(self) -> None:
        CCChessboard.apply_strategy(_strategy_40(max_reroll=1))
        people = CCChessboard.strategy.people
        assert people is not None
        box = _pick_leader(self._ctx()).box
        assert box is not None
        assert (box[0] + box[2] // 2, box[1] + box[3] // 2) == people.back_point()
        assert people.back_point() == DEFAULT_BACK_BUTTON

    def test_reroll_budget_exhausts_then_falls_back(self) -> None:
        """摇满额度后必须兜底选人（否则退回主菜单就再没有出口）。"""
        CCChessboard.apply_strategy(_strategy_40(max_reroll=2))
        for expected_used in (1, 2):
            result = _pick_leader(self._ctx())
            assert result.detail == {"reroll": True}
            assert CCChessboard.rerolls_used.get("leader", 0) == expected_used
        result = _pick_leader(self._ctx())
        assert result.detail == {"fallback": True}
        assert CCChessboard.rerolls_used.get("leader", 0) == 2

    def test_preferred_leader_does_not_consume_reroll(self) -> None:
        CCChessboard.apply_strategy(_strategy_40(max_reroll=3))
        ctx = _ScriptedContext(
            {
                "CCFlagInSelectPeople": _hit((550, 72, 220, 45)),
                "Leaders_30027": _hit((890, 240, 300, 300)),
            }
        )
        result = _pick_leader(ctx)
        assert result.detail == {"leader": "30027"}
        assert CCChessboard.rerolls_used.get("leader", 0) == 0

    def test_already_selected_does_not_consume_reroll(self) -> None:
        """已经选好了就别再退出去重摇（重复点会取消选中）。"""
        CCChessboard.apply_strategy(_strategy_40(max_reroll=3))
        ctx = self._ctx()
        ctx.roi_answers[(45, 460, 140, 70)] = _hit((89, 469, 52, 52))
        result = _pick_leader(ctx)
        assert result.detail == {"selected": 0}
        assert CCChessboard.rerolls_used.get("leader", 0) == 0

    def test_default_strategy_has_no_reroll(self) -> None:
        """3.5 内置策略不含 max_reroll → 0 次，行为与改造前一致。"""
        CCChessboard.apply_strategy(BASE_STRATEGY)
        people = BASE_STRATEGY.people
        assert people is not None
        assert people.max_reroll == 0
        assert people.can_reroll(0) is False
        assert CCChessboard.consume_reroll("leader", people.max_reroll) is False

    def test_apply_strategy_resets_reroll_counter(self) -> None:
        """每次开任务（CCResetData → apply_strategy）都要把额度清零。"""
        CCChessboard.apply_strategy(_strategy_40(max_reroll=3))
        assert _pick_leader(self._ctx()).detail == {"reroll": True}
        assert CCChessboard.rerolls_used.get("leader", 0) == 1
        CCChessboard.apply_strategy(_strategy_40(max_reroll=3))
        assert CCChessboard.rerolls_used.get("leader", 0) == 0

    def test_consume_reroll_respects_max(self) -> None:
        CCChessboard.apply_strategy(_strategy_40(max_reroll=1))
        assert CCChessboard.consume_reroll("leader", 1) is True
        assert CCChessboard.consume_reroll("leader", 1) is False

    def test_consume_reroll_false_with_zero_budget(self) -> None:
        CCChessboard.apply_strategy(parse_strategy(_minimal_raw()))
        assert CCChessboard.consume_reroll("leader", 0) is False

    def test_board_anchor_action_resets_counter_per_match(self) -> None:
        """对局页锚点（CCFlagInCombatMain 的 CCChessboard）命中 = 已进入一局 → 额度复位。

        额度按「局」算：一个任务会连打多局，实测打完 7 轮会自动开下一局，
        不复位的话从第二局起就只能兜底、不再重摇。
        """
        CCChessboard.apply_strategy(_strategy_40(max_reroll=3))
        assert _pick_leader(self._ctx()).detail == {"reroll": True}
        assert CCChessboard.rerolls_used.get("leader", 0) == 1

        class _Ctx:
            def clear_hit_count(self, _node: str) -> bool:
                return True

        CCChessboard.__new__(CCChessboard).run(_Ctx(), None)  # pyright: ignore[reportArgumentType]

        assert CCChessboard.rerolls_used.get("leader", 0) == 0
        # 复位后又能重摇了
        assert _pick_leader(self._ctx()).detail == {"reroll": True}

    def test_board_anchor_action_resets_per_match_hit_counts(self) -> None:
        """同一处还要清「每局只用一次」节点的命中计数（max_hit 是按任务计的）。

        CCNext(奇遇下一步)/CCEnterBattle(进入战斗) 每局各命中一次，不清的话打几局就耗尽，
        之后再也认不出来 —— 实测第 3 局起 CCNext 不命中、CCStart 卡 20s 超时、任务 4000。
        """
        cleared: list[str] = []

        class _Ctx:
            def clear_hit_count(self, node_name: str) -> bool:
                cleared.append(node_name)
                return True

        CCChessboard.__new__(CCChessboard).run(_Ctx(), None)  # pyright: ignore[reportArgumentType]

        assert cleared == list(MATCH_SCOPED_HIT_NODES)

    def test_board_anchor_survives_clear_hit_count_failure(self) -> None:
        """计数复位失败不能拖垮主循环（对局页每轮都会走这里）。"""

        class _Ctx:
            def clear_hit_count(self, node_name: str) -> bool:
                raise RuntimeError("boom")

        result = CCChessboard.__new__(CCChessboard).run(_Ctx(), None)  # pyright: ignore[reportArgumentType]

        assert result.success is True

    def test_4_0_profile_disables_leader_reroll(self) -> None:
        """领队层不再重摇（池子由奇遇决定），额度挪到奇遇门控上。"""
        strategy = load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)
        assert strategy.people is not None
        assert strategy.people.max_reroll == 0
        assert strategy.encounters is not None
        assert strategy.encounters.max_reroll == 15
        assert strategy.encounters.accept == ("杻阳有兽", "大大大礼帽", "库存盘点", "装修计划")


class TestPeopleRerollConfig:
    """people.max_reroll / people.back_button 的解析与校验。"""

    def test_accepts_max_reroll_and_back_button(self) -> None:
        people = parse_strategy(
            _minimal_raw(people={"slots": [[1, 2]], "max_reroll": 2, "back_button": [10, 20]})
        ).people
        assert people is not None
        assert people.max_reroll == 2
        assert people.can_reroll(1) is True
        assert people.can_reroll(2) is False
        assert people.back_point() == (10, 20)

    def test_back_button_defaults_to_measured_point(self) -> None:
        people = parse_strategy(_minimal_raw(people={"slots": [[1, 2]]})).people
        assert people is not None
        assert people.back_button is None
        assert people.back_point() == (46, 43)

    def test_rejects_negative_max_reroll(self) -> None:
        with pytest.raises(StrategyError, match="people.max_reroll"):
            parse_strategy(_minimal_raw(people={"slots": [[1, 2]], "max_reroll": -1}))

    def test_rejects_non_integer_max_reroll(self) -> None:
        with pytest.raises(StrategyError, match="people.max_reroll"):
            parse_strategy(_minimal_raw(people={"slots": [[1, 2]], "max_reroll": "3"}))

    def test_rejects_malformed_back_button(self) -> None:
        with pytest.raises(StrategyError, match="people.back_button"):
            parse_strategy(_minimal_raw(people={"slots": [[1, 2]], "back_button": [1]}))


def _pick_encounter(context: _ScriptedContext) -> Any:
    reco = CCPickEncounterRec.__new__(CCPickEncounterRec)
    argv = type("Argv", (), {"image": np.zeros((1, 1, 3), dtype=np.uint8)})()
    return reco.analyze(context, argv)  # pyright: ignore[reportArgumentType]


class TestEncounterGate:
    """奇遇名门控：名字不在白名单就退出去重摇（棋子池由奇遇决定，领队只影响技能）。

    实机依据：按领队重摇 15 次只中 1 次（~7%）；而非目标奇遇的对局是纯浪费
    （白名单卡一张都不出，机器人只能刷新+开战）。奇遇名 OCR 实测 3/3 命中、负对照 miss。
    """

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    @staticmethod
    def _ctx(name: str) -> _ScriptedContext:
        return _ScriptedContext({"CCNext": _hit((1010, 612, 226, 50)), "CCEncounterNameRec": _ocr_hit(name)})

    def test_accepts_listed_encounter(self) -> None:
        result = _pick_encounter(self._ctx("杻阳有兽"))
        assert result.box is None
        assert result.detail == {"encounter": "杻阳有兽", "accepted": True}
        assert CCChessboard.rerolls_used.get("encounter", 0) == 0

    def test_accepts_encounter_name_with_ocr_spaces(self) -> None:
        result = _pick_encounter(self._ctx("杻阳 有兽"))
        assert result.detail.get("accepted") is True

    def test_rerolls_unlisted_encounter(self) -> None:
        result = _pick_encounter(self._ctx("大口护盾"))
        assert result.detail == {"reroll": True}
        assert result.box == [41, 38, 10, 10]
        assert CCChessboard.rerolls_used.get("encounter", 0) == 1

    def test_budget_exhausted_plays_anyway(self) -> None:
        """摇满额度后必须认了直接开打（否则会一直退出去，一个对局也开不了）。"""
        people_budget = CCChessboard.strategy.encounters
        assert people_budget is not None
        for _ in range(people_budget.max_reroll):
            assert _pick_encounter(self._ctx("大口护盾")).detail == {"reroll": True}
        result = _pick_encounter(self._ctx("大口护盾"))
        assert result.box is None
        assert result.detail == {"encounter": "大口护盾", "accepted": False}

    def test_misses_when_not_on_encounter_popup(self) -> None:
        """不在奇遇弹窗（没有「下一步」）就不要抢别的界面的 next。"""
        ctx = _ScriptedContext({})
        result = _pick_encounter(ctx)
        assert result.box is None
        assert ctx.asked == ["CCNext"]

    def test_ocr_miss_is_treated_as_unlisted(self) -> None:
        ctx = _ScriptedContext({"CCNext": _hit((1010, 612, 226, 50))})
        result = _pick_encounter(ctx)
        assert result.detail == {"reroll": True}

    def test_no_gate_without_encounters_block(self) -> None:
        CCChessboard.apply_strategy(replace(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH), encounters=None))
        ctx = self._ctx("大口护盾")
        assert _pick_encounter(ctx).box is None
        assert ctx.asked == []

    def test_no_gate_with_empty_accept_list(self) -> None:
        strategy = load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)
        assert strategy.encounters is not None
        CCChessboard.apply_strategy(replace(strategy, encounters=replace(strategy.encounters, accept=())))
        ctx = self._ctx("大口护盾")
        assert _pick_encounter(ctx).box is None
        assert ctx.asked == []

    def test_encounter_budget_resets_per_match(self) -> None:
        assert _pick_encounter(self._ctx("大口护盾")).detail == {"reroll": True}
        assert CCChessboard.rerolls_used.get("encounter", 0) == 1

        class _Ctx:
            def clear_hit_count(self, _node: str) -> bool:
                return True

        CCChessboard.__new__(CCChessboard).run(_Ctx(), None)  # pyright: ignore[reportArgumentType]

        assert CCChessboard.rerolls_used.get("encounter", 0) == 0


class TestEncounterConfig:
    """encounters 段的解析与校验。"""

    def test_accepts_names_and_budget(self) -> None:
        spec = parse_strategy(_minimal_raw(encounters={"accept": ["甲", "乙"], "max_reroll": 3})).encounters
        assert spec is not None
        assert spec.accept == ("甲", "乙")
        assert spec.max_reroll == 3
        assert spec.back_point() == DEFAULT_BACK_BUTTON

    def test_encounters_section_is_optional(self) -> None:
        assert parse_strategy(_minimal_raw()).encounters is None

    def test_accepts_matches_with_tolerant_spacing(self) -> None:
        spec = parse_strategy(_minimal_raw(encounters={"accept": ["装修 计划"]})).encounters
        assert spec is not None
        assert spec.accepts("装修计划") is True
        assert spec.accepts("大口护盾") is False
        assert spec.accepts("") is False

    def test_rejects_non_string_accept_item(self) -> None:
        with pytest.raises(StrategyError, match="encounters.accept"):
            parse_strategy(_minimal_raw(encounters={"accept": [1]}))

    def test_rejects_negative_max_reroll(self) -> None:
        with pytest.raises(StrategyError, match="encounters.max_reroll"):
            parse_strategy(_minimal_raw(encounters={"accept": ["甲"], "max_reroll": -1}))

    def test_rejects_malformed_back_button(self) -> None:
        with pytest.raises(StrategyError, match="encounters.back_button"):
            parse_strategy(_minimal_raw(encounters={"accept": ["甲"], "back_button": [1]}))


# 重摇链路回归：这次修复的**全部**内容就是 pipeline 里的顺序与 CCStop 的出口链 ——
# 把 CCStop 排到 CCStart 之后（4.0 改写就是这么写的），表现与「完全不放弃」一模一样：
# 实机连摇 4 次都是同名奇遇「大鱼吃小鱼」。顺序漂移不会让任何加载期校验报错，
# 所以拿用例把它钉住。
CC_PIPELINE_PATH = Path("resource/base/pipeline/activity/CritterCrash.json")

# pipeline 是 JSONC：行首、行尾都可能带 // 注释，而字符串里也有 "//." 这类内容
_JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*')


def _load_cc_pipeline() -> dict[str, Any]:
    raw = (PROJECT_ROOT / CC_PIPELINE_PATH).read_text(encoding="utf-8")
    text = _JSONC_TOKEN.sub(lambda match: match.group(0) if match.group(0).startswith('"') else "", raw)
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


class TestRerollAbandonsBeforeRestart:
    """重摇奇遇必须「先放弃、再开始」，而且放弃这一步要保持原子（2026-10-17 实机）。

    `CCStop` = 主菜单「箱中对决」招牌右上角的橙底 ✕（只在有未完成对局时出现）：点它才弹
    「此时放弃对战评分不变，是否确认？」，确认后 ✕ 消失、再点「箱中对决」才是新奇遇
    （实测：新科学委托 → 大大大礼帽；端到端 5 轮 5 个不同奇遇、≈7.5 s/轮）。顺序反了 =
    永远先点「箱中对决」续局，额度白烧 —— 这就是用户报的「光退到界面没用」。

    结构约定：`CCStop` 只有识别 + 点击、**没有 next**，别处一律 `[JumpBack]CCStop` 引用
    （[JumpBack] 只回父列表重新识别、不重跑父 action）。第一版写成「点 ✕ → 清框 → 开局」的
    复合节点、又让 `CritterCrash.next` 指回它，长出 `CCStop ↔ CritterCrash` 互指环 ——
    下面两条用例把这个坑封住。
    """

    def setup_method(self) -> None:
        self.pipeline = _load_cc_pipeline()

    def test_shortcut_nodes_are_atomic(self) -> None:
        """「点一下就走」的节点（CCStop / CCRerollConfirm）必须原子：只有识别 + 点击，没有 next。

        它们的 next 原本写的是**调用方的续程**（`→ CritterCrash → CCStart`）：一来和主菜单锚点
        互指成环（`CritterCrash ↔ CCStop`、`CritterCrash ↔ CCRerollConfirm`），二来会硬路由、
        跳过调用方列表里的状态判断（入口路径上「先放弃残局」就是被这么跳掉的）。
        """
        for leaf in ("CCStop", "CCRerollConfirm"):
            assert "next" not in self.pipeline[leaf], f"{leaf} 必须原子（无 next）"

    def test_shortcut_nodes_are_only_referenced_as_jumpback(self) -> None:
        """全图扫描：这两个节点只能以 `[JumpBack]X` 引用（原子节点的唯一引用形式）。"""
        offenders = [
            f"{name}.next[{entry!r}]"
            for name, node in self.pipeline.items()
            if isinstance(node, dict) and isinstance(node.get("next"), list)
            for entry in node["next"]
            if isinstance(entry, str)
            and entry.endswith(("CCStop", "CCRerollConfirm"))
            and not entry.startswith("[JumpBack]")
        ]
        assert offenders == [], f"只能以 [JumpBack]X 引用（[JumpBack] 不重跑父 action），违规：{offenders}"

    def test_entry_chain_abandons_before_start(self) -> None:
        """入口链（任务直接就停在主菜单）里 CCStop 必须排在 CCStart 之前（3.5 就是这个顺序）。"""
        nxt = self.pipeline["CCResetData"]["next"]
        assert "[JumpBack]CCStop" in nxt
        assert nxt.index("[JumpBack]CCStop") < nxt.index("CCStart")

    def test_main_menu_anchor_abandons_before_restart(self) -> None:
        """主菜单锚点是唯一的放弃决策点；清框那一项要排在放弃之前。

        点完 ✕ / 清完框都会 [JumpBack] 回本列表重新识别，所以顺序就是执行顺序：
        先 CCRerollConfirm 收拾「放弃对战」框，再 CCStop 放弃残局，最后 CCStart 开局。
        """
        nxt = self.pipeline["CritterCrash"]["next"]
        assert "[JumpBack]CCStop" in nxt
        assert nxt.index("[JumpBack]CCRerollConfirm") < nxt.index("[JumpBack]CCStop")
        assert nxt.index("[JumpBack]CCStop") < nxt.index("CCStart")

    def test_reroll_and_leader_paths_route_through_the_anchor(self) -> None:
        """两条「返回主菜单重摇」的路径都经主菜单锚点统一放弃，不各自挂一份 CCStop。"""
        for name in ("CCEncounterAccept", "CCSelectPeople4p0"):
            nxt = self.pipeline[name]["next"]
            assert "CritterCrash" in nxt, f"{name}.next 必须经主菜单锚点"
            assert nxt.index("CritterCrash") < nxt.index("CCStart")

    def test_stop_matches_the_measured_close_button(self) -> None:
        """✕ 的资产与 ROI 都是实机量出来的：模板要在资源包里，ROI 要罩住徽章圆心。"""
        param = self.pipeline["CCStop"]["recognition"]["param"]
        assert param["template"] == ["CritterCrash/Stop.png"]
        x, y, w, h = param["roi"]
        assert x <= 1231 <= x + w, f"ROI {param['roi']} 没罩住实机 ✕ 圆心 x=1231"
        assert y <= 576 <= y + h, f"ROI {param['roi']} 没罩住实机 ✕ 圆心 y=576"
        assert (PROJECT_ROOT / "resource/base/image" / param["template"][0]).is_file()

    def test_confirm_target_covers_the_measured_button(self) -> None:
        """放弃框「确认」实机圆心 (800,427)：CCRerollConfirm 的固定落点要罩得住它。"""
        x, y, w, h = self.pipeline["CCRerollConfirm"]["action"]["param"]["target"]
        assert x <= 800 <= x + w, f"落点 {[x, y, w, h]} 没罩住实机「确认」x=800"
        assert y <= 427 <= y + h, f"落点 {[x, y, w, h]} 没罩住实机「确认」y=427"
