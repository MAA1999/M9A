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
    CCBuyCard,
    CCChessboard,
    CCSticker,
    StrategyError,
    load_strategy,
    parse_strategy,
)
from custom.reco.critter_crash import CCBuyCardRec, CCPickEncounterRec, CCPickLeaderRec
from maa.define import BoxAndScoreResult, MaaStatusEnum, OCRResult, RecognitionDetail, Rect, Status, TaskDetail

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 4.0 是独立策略表，默认不加载；只有 CCResetData 显式指定 strategy_file 才启用
STRATEGY_4_0_PATH = Path("data/critter_crash/strategy-4.0.json")

# 4.0 棋盘 ROI（Lead 实机实测，1280x720；15/15 框在爪印上）
# 相对 3.5 整盘右移约 103/104/109px，行距也变大 —— 3.5 的 ROI 在 4.0 上全部失配。
ROIS_4_0 = [
    [
        [354, 197, 68, 44],
        [462, 175, 68, 44],
        [597, 175, 68, 44],
        [732, 175, 68, 44],
        [867, 175, 68, 44],
        [1005, 175, 68, 44],
    ],
    [
        [354, 308, 68, 44],
        [448, 286, 68, 44],
        [587, 286, 68, 44],
        [727, 286, 68, 44],
        [868, 286, 68, 44],
        [1009, 286, 68, 44],
    ],
    [
        [354, 428, 68, 44],
        [433, 406, 68, 44],
        [578, 406, 68, 44],
        [723, 406, 68, 44],
        [868, 406, 68, 44],
        [1014, 406, 68, 44],
    ],
]

# 当前基线（4.0 唯一策略表）：棋盘 ROI 见上面 ROIS_4_0，棋子白名单按解包 auto_chess id 命名。
BASE_CARDS: dict[str, tuple[int, list[tuple[int, int]]]] = {
    "32122": (1, [(0, 2), (2, 2), (0, 3), (2, 3), (0, 4), (2, 4), (0, 5), (2, 5)]),
    "32123": (3, [(0, 2), (2, 2), (0, 3), (2, 3), (0, 4), (2, 4), (0, 5), (2, 5)]),
    "32703": (3, [(0, 1), (2, 1), (0, 2), (2, 2), (0, 3), (2, 3), (0, 4), (2, 4), (0, 5), (2, 5)]),
    # 32124 木头妇孺放**棋盘中间行 row1**（用户明确），其它卡放 row0/row2 交替
    "32124": (3, [(1, 2), (1, 3), (1, 4), (1, 5)]),
    "32126": (3, [(1, 3), (1, 4), (1, 5), (1, 2)]),
}
BASE_CARD_ORDER = ["32122", "32123", "32703"]
# 4.0 购买表：鹿蜀系四张 + 石骑士（32124/32126 的模板早已在 Cards/ 下，)
# 但漏写在 cards 表里，导致商店出现时认得出却不买、随后被刷新刷掉——见 strategy source。
STRATEGY_4_0_CARD_ORDER = ["32122", "32123", "32703", "32124", "32126"]
# card_names() 返回的是 award_priority（识别顺序），不是 cards 声明顺序
STRATEGY_4_0_AWARD_ORDER = ["32123", "32703", "32122", "32124", "32126"]

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
    assert BASE_STRATEGY.board_cols == 6
    assert [[list(rect) for rect in row] for row in BASE_STRATEGY.board_rois] == ROIS_4_0

    assert {card.name: (card.max_level, list(card.positions)) for card in BASE_STRATEGY.cards} == BASE_CARDS
    # 顺序即 find_empty_position 的优先级，必须与改造前一致
    assert [card.name for card in BASE_STRATEGY.cards] == STRATEGY_4_0_CARD_ORDER

    # 类初始状态是空占位（策略表在 CCResetData 里读盘后才生效）
    assert CCChessboard.board_rois == [[[0, 0, 0, 0]]]
    assert CCChessboard.chess_types == []

    try:
        CCChessboard.apply_strategy(BASE_STRATEGY)
        assert CCChessboard.board_rois == ROIS_4_0
        assert [chess["name"] for chess in CCChessboard.chess_types] == STRATEGY_4_0_CARD_ORDER
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
    # card_names 走 award_priority（奖励区识别顺序），不是 cards 声明顺序
    assert BASE_STRATEGY.card_names() == tuple(STRATEGY_4_0_AWARD_ORDER)


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
            {"name": "32703", "max_level": 1, "positions": [[0, 0]]},
        ],
        award_priority=["32703", "32123"],
    )
    assert parse_strategy(raw).card_names() == ("32703", "32123")


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
    raw = _minimal_raw(award_priority=["32703"])
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
        CCChessboard.place_chess(0, 0, "32703")
        CCChessboard.board_reset()
        assert CCChessboard.board == [[None] * 6 for _ in range(3)]
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
        assert CCChessboard.place_chess(3, 0, "32703") is False
        assert CCChessboard.place_chess(-1, 0, "32703") is False

    def test_find_empty_position_follows_declaration_order(self) -> None:
        """positions 现在是全部可放置格，按声明顺序取第一个空位。"""
        assert CCChessboard.find_empty_position("32123") == (0, 2)
        CCChessboard.place_chess(0, 2, "32123")
        assert CCChessboard.find_empty_position("32123") == (2, 2)

    def test_find_empty_position_returns_none_for_unknown_card(self) -> None:
        assert CCChessboard.find_empty_position("NotACard") is None

    def test_upgrade_chess_stops_at_max_level(self) -> None:
        """鹿蜀上限 3 星；**两次合成升一级**，到 3 级要累计 4 次合成。"""
        assert CCChessboard.place_chess(0, 4, "32123") is True
        for _ in range(4):
            assert CCChessboard.upgrade_chess(0, 4) is True
        entry = CCChessboard.board[0][4]
        assert entry is not None
        assert (entry["name"], entry["level"]) == ("32123", 3)
        assert CCChessboard.upgrade_chess(0, 4) is False

    def test_one_merge_does_not_level_up(self) -> None:
        """合成 1 次还是 LV.1（用户实测：01/11/21 各合一次都差一次才 LV.2）。"""
        assert CCChessboard.place_chess(0, 4, "32123") is True
        assert CCChessboard.upgrade_chess(0, 4) is True
        entry = CCChessboard.board[0][4]
        assert entry is not None
        assert entry["level"] == 1
        assert entry["merges"] == 1

    def test_upgrade_chess_keeps_board_chesses_in_sync(self) -> None:
        CCChessboard.place_chess(0, 4, "32123")
        CCChessboard.upgrade_chess(0, 4)
        CCChessboard.upgrade_chess(0, 4)
        assert CCChessboard.board_chesses[0]["level"] == 2

    def test_can_upgrade_existing_only_for_placed_cards(self) -> None:
        assert CCChessboard.can_upgrade_existing("32123") is False
        CCChessboard.place_chess(0, 4, "32123")
        assert CCChessboard.can_upgrade_existing("32123") is True

    def test_can_upgrade_existing_true_below_max_level(self) -> None:
        """32703 也是星 1..3：刚放上去是 1 级，可以继续合成升级。"""
        assert CCChessboard.place_chess(0, 2, "32703") is True
        assert CCChessboard.can_upgrade_existing("32703") is True

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
        CCChessboard.place_chess(0, 0, "32703")
        CCChessboard.apply_strategy(strategy)

        assert CCChessboard.board == [[None, None], [None, None]]
        assert CCChessboard.board_chesses == []
        assert CCChessboard.board_rois == [[[1, 2, 3, 4], [5, 6, 7, 8]], [[9, 10, 11, 12], [13, 14, 15, 16]]]
        assert [chess["name"] for chess in CCChessboard.chess_types] == ["NewCard"]
        assert CCChessboard.get_chess_info("32703") == {}
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
        # run_task 收到的 pipeline_override（断言「begin/end 是否指向目标格」用）
        self.task_overrides: list[dict[str, Any]] = []
        # 按节点名脚本化任务结局；缺省成功
        self.task_statuses: dict[str, MaaStatusEnum] = {}
        self.overridden_images: list[str] = []
        self.clicks: list[tuple[int, int]] = []
        self.bought = False
        self.piece_cell: tuple[int, int] | None = None
        # 合成时额外变化的格（模拟「同时改动多格」）
        self.extra_changed: list[tuple[int, int]] = []
        # 所有格子都画成高对比（模拟棋盘全满）
        self.all_occupied = False
        # 画面强制全空（模拟新对局开始：内部还记着上一局的棋子，画面已经清空）
        self.force_empty_frame = False
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self.keys: list[int] = []
        self.touches: list[tuple[str, int, int]] = []
        self.cleared_hits: list[str] = []

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

    # --- tasker.controller：动作里会取帧、点击、拖拽、覆盖图片 ---
    class _Controller:
        def __init__(self, owner: "_ScriptedContext") -> None:
            self._owner = owner

        def post_screencap(self) -> Any:
            return self

        def post_click(self, x: int, y: int) -> Any:
            self._owner.clicks.append((x, y))
            if (x, y) == CCBuyCard._BUY_BUTTON_POINT:
                self._owner.bought = True
            return self

        def post_swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> Any:
            self._owner.swipes.append((x1, y1, x2, y2, duration))
            return self

        def post_click_key(self, code: int) -> Any:
            self._owner.keys.append(code)
            return self

        def post_touch_down(self, x: int, y: int) -> Any:
            self._owner.touches.append(("down", x, y))
            return self

        def post_touch_move(self, x: int, y: int) -> Any:
            self._owner.touches.append(("move", x, y))
            return self

        def post_touch_up(self) -> Any:
            self._owner.touches.append(("up", 0, 0))
            self._owner.bought = True
            return self

        def post_key_down(self, code: int) -> Any:
            self._owner.keys.append(code)
            return self

        def post_key_up(self, code: int) -> Any:
            return self

        def wait(self) -> Any:
            return self

        def get(self) -> np.ndarray:
            # 空格底纹：**极低**噪声（std≈2），确保被判定为空格。
            # 实机空格 std≈29，但测试里只要低于 _OCCUPIED_STD(45) 即可；
            # 用更低的噪声能避免随机波动导致误判占用。
            rng = np.random.default_rng(0)
            frame = rng.integers(195, 199, (720, 1280, 3), dtype=np.uint8)
            # 买完后在指定格画一块高对比棋子（std≈68，对应实机占用格）
            if self._owner.force_empty_frame:
                return frame
            if self._owner.all_occupied:
                for rr in range(len(CCChessboard.board)):
                    for cc in range(len(CCChessboard.board[rr])):
                        if rr >= len(CCChessboard.board_rois) or cc >= len(CCChessboard.board_rois[rr]):
                            continue
                        roi = CCChessboard.board_rois[rr][cc]
                        patch = rng.integers(0, 255, (roi[3], roi[2], 3), dtype=np.uint8)
                        frame[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]] = patch
                return frame
            # 按**内部棋盘**渲染：内部记有棋子的格画成高对比，空着保持低噪声。
            # 这样「实际画面」与内部状态一致，测试里 place_chess 之后
            # find_empty_position_on_image 才能正确判空。
            for rr in range(len(CCChessboard.board)):
                for cc in range(len(CCChessboard.board[rr])):
                    if rr >= len(CCChessboard.board_rois) or cc >= len(CCChessboard.board_rois[rr]):
                        continue
                    if CCChessboard.board[rr][cc] is None:
                        continue
                    roi = CCChessboard.board_rois[rr][cc]
                    patch = rng.integers(0, 255, (roi[3], roi[2], 3), dtype=np.uint8)
                    frame[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]] = patch
            if self._owner.bought and self._owner.piece_cell is not None:
                r, c = self._owner.piece_cell
                roi = CCChessboard.board_rois[r][c]
                patch = rng.integers(0, 255, (roi[3], roi[2], 3), dtype=np.uint8)
                frame[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]] = patch
            return frame

    def __init_tasker(self) -> None:
        pass

    @property
    def tasker(self) -> Any:
        if not hasattr(self, "_tasker"):
            ctrl = self._Controller(self)
            self._tasker = type("Tasker", (), {"controller": ctrl})()
        return self._tasker

    def override_image(self, name: str, image: Any) -> None:
        self.overridden_images.append(name)

    def clear_hit_count(self, node_name: str) -> None:
        self.cleared_hits.append(node_name)

    def run_task(self, name: str, pipeline_override: dict[str, Any] | None = None) -> TaskDetail:
        """与生产调用同签名：Context.run_task(entry, pipeline_override) -> TaskDetail。

        以前这里只收 1 个参数、返回 None，于是任何走到 run_task 的测试都会 TypeError，
        也就没人写出「部署成败判定」的用例 —— 而 .ok / .status 恰好在那里出过两次错。
        """
        self.tasks.append(name)
        self.task_overrides.append(pipeline_override or {})
        raw = self.task_statuses.get(name, MaaStatusEnum.succeeded)
        # TaskDetail.status 期望 Status 对象（.succeeded/.failed 是它的属性），
        # 直接塞 MaaStatusEnum 会让生产代码的 .status.succeeded 判断恒为 False。
        return TaskDetail(task_id=len(self.tasks), entry=name, node_id_list=[], status=Status(raw))


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
    """跑 CCBuyCardRec.analyze。

    注意 image 必须用**桩渲染出的整帧**：现在「有没有空位」是按实际画面判的
    （is_cell_occupied 会按 board_rois 裁图），传 1x1 的空数组会裁出空 patch、
    全部判成空位，跟真实行为不符。
    """
    reco = CCBuyCardRec.__new__(CCBuyCardRec)
    argv = type("Argv", (), {"image": context.tasker.controller.get()})()
    return reco.analyze(context, argv)  # pyright: ignore[reportArgumentType]


def _run_buy_card(
    context: _ScriptedContext,
    detail: dict[str, Any],
    box: tuple[int, int, int, int],
) -> Any:
    """直接跑 CCBuyCard.run —— 覆盖「部署/升级的成败判定」与 run_task 的 override。"""
    actor = CCBuyCard.__new__(CCBuyCard)
    # 生产的取值路径是 raw_detail["best"]["detail"]，两段都是字典下标
    raw_detail = {"best": {"detail": detail}}
    reco_detail = type("RecoDetail", (), {"raw_detail": raw_detail})()
    argv = type("Argv", (), {"reco_detail": reco_detail, "box": box, "custom_action_param": None})()
    return actor.run(context, argv)  # pyright: ignore[reportArgumentType]


class TestBuyCardPriority:
    """买入决策优先级：改造只是把遍历源换成策略表，优先级本身必须逐条保持。"""

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_buy_pool_follows_strategy_card_order(self) -> None:
        """购买区识别按策略表声明顺序进行，而不是按 chess_types 的其它顺序。"""
        ctx = _ScriptedContext({"CCRemainMoney": _hit((669, 29, 36, 25))})
        _analyze_buy_card(ctx)
        assert ctx.templates == [f"CritterCrash/Cards/{name}.png" for name in BASE_STRATEGY.card_names()]

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
        """奖励区是白名单卡但既没空位、所有同名棋子也都满级：跳过。"""
        # 把 32703 摆满所有可放置格并全部升到 3 级 → 既无处安放也无从升级
        for _row, _col in [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (2, 1), (2, 2), (2, 3), (2, 4), (2, 5)]:
            CCChessboard.place_chess(_row, _col, "32703")
            # 两次合成升一级 → 升到 3 级要 4 次
            while CCChessboard.upgrade_chess(_row, _col):
                pass
        # 现在「有没有空位」看实际画面，桩要同步：让所有格都判占用
        # （通过把棋盘内部状态与画面一起造出来）
        ctx = _ScriptedContext(
            {
                "CCBuyCardAwardEmptyRec": _hit((42, 580, 128, 124)),
                "32703": _hit((60, 590, 90, 100)),
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

    def test_profile_keeps_3x6_board(self) -> None:
        """4.0 棋盘 3 行 x 6 列：左列（col0）是专属贴纸列，右侧 5 列才是爪印格。

        实测（.live/acc/STICKER-FINDINGS.md）：贴纸箱与贴纸落点都在左列，
        它与 5 个爪印列共用同一套行 y，故并入同一张 board 表（用户坐标 col 0-5）。
        """
        strategy = self._load()
        assert strategy.board_rows == 3  # type: ignore[attr-defined]
        assert strategy.board_cols == 6  # type: ignore[attr-defined]

    def test_profile_uses_measured_4_0_board_rois(self) -> None:
        """4.0 ROI 必须是实机实测值：3.5 的 ROI 在 4.0 上整盘右移约 103-109px，会全部失配。"""
        strategy = self._load()
        assert [[list(r) for r in row] for row in strategy.board_rois] == ROIS_4_0  # type: ignore[attr-defined]

    def test_profile_roi_centers_are_self_consistent(self) -> None:
        """每个 ROI 的中心必须等于实测格中心（防手抄坐标错位）。"""
        strategy = self._load()
        # 左列(col0) 与爪印列共用行 y，但格子 y 不同：左列 197/308/428，爪印列 175/286/406
        centers = [
            ([219, 197, 197, 197, 197, 197], [388, 496, 631, 766, 901, 1039]),
            ([330, 308, 308, 308, 308, 308], [388, 482, 621, 761, 902, 1043]),
            ([450, 428, 428, 428, 428, 428], [388, 467, 612, 757, 902, 1048]),
        ]
        for row_index, (center_ys, center_xs) in enumerate(centers):
            for col_index, center_x in enumerate(center_xs):
                x, y, w, h = strategy.board_rois[row_index][col_index]  # type: ignore[attr-defined]
                assert (x + w // 2, y + h // 2) == (center_x, center_ys[col_index]), f"r{row_index}c{col_index}"

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
        assert names == STRATEGY_4_0_CARD_ORDER

    def test_profile_max_levels_match_star_caps(self) -> None:
        """32123/32121/32122 有 3 星行 → max_level 3；32125/32126 只当 1 级用。"""
        strategy = self._load()
        caps = {card.name: card.max_level for card in strategy.cards}  # type: ignore[attr-defined]
        # 32122 巡城兵是转化器（【成长】N回合后离场并呼唤鹿蜀），不升级
        assert caps == {"32122": 1, "32123": 3, "32703": 3, "32124": 3, "32126": 3}

    def test_profile_positions_cover_all_placeable_cells(self) -> None:
        """positions 是**全部可放置格**（row 0/2 × col 1..5），不再是优先位子集。

        4.0 买卡是「点卡→购买，游戏自动落子」，落点由游戏决定；positions 只用于
        find_empty_position 判断还有没有空位。只写 8 格会让 col 1 白白空着、更早满盘。
        """
        strategy = self._load()
        deer = next(c for c in strategy.cards if c.name == "32123")  # type: ignore[attr-defined]
        # 石骑士专属位 (0,1)/(2,1) 不在其它卡的 positions 里
        assert len(deer.positions) == 8
        assert (0, 1) not in deer.positions and (2, 1) not in deer.positions
        assert deer.positions[0] == (0, 2) and deer.positions[1] == (2, 2)

    def test_profile_award_priority_is_lushu_first(self) -> None:
        strategy = self._load()
        assert strategy.award_priority == ("32123", "32703", "32122", "32124", "32126")  # type: ignore[attr-defined]

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
            assert [c["name"] for c in CCChessboard.chess_types] == STRATEGY_4_0_CARD_ORDER
            assert CCChessboard.find_empty_position("32123") == (0, 2)
        finally:
            CCChessboard.apply_strategy(before)
        assert CCChessboard.strategy.version == "4.0"
        assert [c["name"] for c in CCChessboard.chess_types] == STRATEGY_4_0_CARD_ORDER

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
            f"CritterCrash/Cards/{name}.png" for name in STRATEGY_4_0_AWARD_ORDER
        ]

    def test_buy_deploys_lushu_to_first_placeable_cell(self) -> None:
        """positions 现在是全部可放置格，第一个空位是 (0,1)（col0 是贴纸列，不参与）。"""
        assert CCChessboard.find_empty_position("32123") == (0, 2)

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

    def test_knight_can_upgrade_to_level_3(self) -> None:
        """坚固石骑士同样是星 1..3，靠合成升级（用户明确：鹿蜀/石骑士都靠合成升级）。"""
        assert CCChessboard.place_chess(0, 2, "32703") is True
        assert CCChessboard.can_upgrade_existing("32703") is True
        for _ in range(4):   # 两次合成升一级，到 3 级要 4 次
            assert CCChessboard.upgrade_chess(0, 2) is True
        assert CCChessboard.upgrade_chess(0, 2) is False

    def test_deer_is_capped_at_level_3(self) -> None:
        """鹿蜀上限 3（auto_chess 只有 star 1..3）。"""
        CCChessboard.place_chess(0, 4, "32123")
        for _ in range(4):
            assert CCChessboard.upgrade_chess(0, 4) is True
        assert CCChessboard.upgrade_chess(0, 4) is False
        entry = CCChessboard.board[0][4]
        assert entry is not None
        assert (entry["name"], entry["level"]) == ("32123", 3)

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

    def test_already_selected_still_hits_so_next_runs(self) -> None:
        """已选中的卡位要返回有效 box，不能返回 None。

        返回 None 等于识别 miss，父节点的 next 不被求值 —— 点完领队没人去点「进入战斗」，
        节点在 20s 超时里空转（实测新开第二局 CCSelectPeople4p0 吃满 20188ms，任务 4000）。
        返回该卡位小框：重复点同一已选卡位是幂等的。
        """
        ctx = _ScriptedContext({"CCFlagInSelectPeople": _hit((550, 72, 220, 45))})
        ctx.roi_answers[(895, 460, 140, 70)] = _hit((941, 469, 52, 52))
        result = _pick_leader(ctx)
        assert result.box is not None
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
        # 2026-10-25 回滚为开局重摇奇遇（局内「卡池不符就开战」的判定始终不可靠）
        assert strategy.encounters.max_reroll == 15
        # 2026-10-24 扩名单：原 4 个「6/6 鹿蜀」命中率只有 13%，实测连摇 22 次一次没中。
        # 补入 40024/40030（覆盖 5/6，只缺 32126 这张 5 费辅助卡），命中率提到 19%。
        assert strategy.encounters.accept == (
            "杻阳有兽",
            "大大大礼帽",
            "库存盘点",
            "装修计划",
            "毛绒利率",
            "工厂广播",
        )


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
        """不在白名单的奇遇 → 点返回重摇（回滚后的默认策略）。"""
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
        """OCR 认不出名字 → 当作不在名单，走重摇。"""
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
        """入口链必须先放弃残局再开局：脚本每轮都要从干净状态开打。

        不放弃就会带着上一局的棋盘/血量/商店状态接着打，内部棋盘模型与真实棋盘立刻分叉。
        """
        nxt = self.pipeline["CCResetData"]["next"]
        assert "[JumpBack]CCStop" in nxt
        assert nxt.index("[JumpBack]CCStop") < nxt.index("CCStart")

    def test_main_menu_anchor_abandons_before_restart(self) -> None:
        """主菜单锚点必须先放弃残局再开局；清框那一项排在放弃之前。

        点完 ✕ / 清完框都会 [JumpBack] 回本列表重新识别，所以顺序就是执行顺序：
        先 CCRerollConfirm 收拾「放弃对战」框，再 CCStop 放弃残局，最后 CCStart 开局。
        """
        nxt = self.pipeline["CritterCrash"]["next"]
        assert "[JumpBack]CCStop" in nxt
        assert nxt.index("[JumpBack]CCRerollConfirm") < nxt.index("[JumpBack]CCStop")
        # 顺序本身是不变量：CCStart 若排到 CCStop 前面，就会「续旧局」而不是放弃重开。
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


class TestStickerSpec:
    """专属贴纸箱的配置解析（贴纸按角色独有，leader 决定「领队不对就不开箱」）。"""

    def test_sticker_parses_leader_open_round_and_positions(self) -> None:
        raw = _minimal_raw(
            sticker={"leader": "30027", "open_round": 2, "positions": [[0, 0]]},
        )
        strategy = parse_strategy(raw)
        assert strategy.sticker is not None
        assert strategy.sticker.leader == "30027"
        assert strategy.sticker.open_round == 2
        assert strategy.sticker.positions == ((0, 0),)

    def test_sticker_without_leader_means_no_gating(self) -> None:
        """不给 leader = 不门控，任何领队都开（保持向后兼容）。"""
        strategy = parse_strategy(_minimal_raw(sticker={"open_round": 2}))
        assert strategy.sticker is not None
        assert strategy.sticker.leader is None

    def test_sticker_rejects_empty_leader(self) -> None:
        with pytest.raises(StrategyError, match="sticker.leader"):
            parse_strategy(_minimal_raw(sticker={"leader": "", "open_round": 2}))

    def test_sticker_positions_out_of_board_rejected(self) -> None:
        with pytest.raises(StrategyError, match="sticker"):
            parse_strategy(_minimal_raw(sticker={"open_round": 2, "positions": [[5, 5]]}))

    def test_shipped_strategy_gates_sticker_on_xiao_ye_ni_sai(self) -> None:
        """随包的 4.0 策略表必须把贴纸绑定到 30027（小叶尼塞）。"""
        strategy = load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH)
        assert strategy.sticker is not None
        assert strategy.sticker.leader == "30027"


class TestLeaderState:
    """本局领队的记账：贴纸门控依赖它，且必须按局复位。"""

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_default_is_unknown(self) -> None:
        """reset_leader() 是唯一复位入口（apply_strategy 不清它）。"""
        CCChessboard.set_leader("30027")
        CCChessboard.reset_leader()
        assert CCChessboard.leader_id is None

    def test_set_leader_records_id(self) -> None:
        CCChessboard.set_leader("30027")
        assert CCChessboard.leader_id == "30027"

    def test_reset_rerolls_must_not_clear_leader(self) -> None:
        """reset_rerolls 每轮主循环都调，清领队会让贴纸永远等不到匹配（实测 21:41）。"""
        CCChessboard.set_leader("30027")
        CCChessboard.reset_rerolls()
        assert CCChessboard.leader_id == "30027"

    def test_reset_leader_clears_it(self) -> None:
        """真正开新局时才复位。"""
        CCChessboard.set_leader("30027")
        CCChessboard.reset_leader()
        assert CCChessboard.leader_id is None

    def test_concrete_leader_is_not_overwritten_by_fallback(self) -> None:
        """兜底分支每轮都会重问；它不许覆盖已经记到的具体领队。"""
        CCChessboard.set_leader("30027")
        CCChessboard.set_leader(None)   # 兜底分支
        assert CCChessboard.leader_id == "30027"


class TestBuyCardFlow:
    """4.0 买卡：从商店拖到目标格（不是点购买）。

    点购买也能买到，但棋子由游戏自动落到第一个空位 —— 会把棋盘从左往右填满、
    占掉石骑士该占的位置，且满盘后无法再点购买升级。
    拖拽可精确控制落点（实测从商店卡拖到 (0,1)，卡精确落在那里）。
    手势必须用 touch_down → touch_move → touch_up；纯两点 swipe 不会触发拖拽。
    """

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def _buy(
        self,
        ctx: _ScriptedContext,
        name: str = "32123",
        # 必须落在商店区（x≥214）：奖励区在 x<214，从那儿拖会把奖励卡拖到棋盘上
        box: tuple[int, int, int, int] = (300, 620, 90, 100),
        piece_cell: tuple[int, int] | None = (0, 5),
    ) -> Any:
        ctx.piece_cell = piece_cell
        return _run_buy_card(ctx, {"type": 0, "action": 0, "name": name}, box=box)

    def test_uses_touch_sequence_not_swipe(self) -> None:
        """拖拽必须走 touch_down/move/up；post_swipe 两点手势不会触发拖拽。"""
        ctx = _ScriptedContext({"32123": _hit((732, 175, 68, 44))})
        self._buy(ctx)
        assert ctx.swipes == [], "不能用 post_swipe（两点手势无效）"
        kinds = [k for k, _, _ in ctx.touches]
        assert kinds[0] == "down" and kinds[-1] == "up"
        assert kinds.count("move") >= 2, "必须有中途移动点"

    def test_drag_starts_from_card_and_ends_at_target_cell(self) -> None:
        ctx = _ScriptedContext({"32123": _hit((732, 175, 68, 44))})
        self._buy(ctx)
        down = next(t for t in ctx.touches if t[0] == "down")
        assert (down[1], down[2]) == (300 + 90 // 2, 620 + 100 // 2)
        moves = [t for t in ctx.touches if t[0] == "move"]
        target = CCChessboard.board_rois[0][2]   # positions 第一个格是 (0,2)（(0,1) 留给石骑士）
        assert (moves[-1][1], moves[-1][2]) == (
            target[0] + target[2] // 2,
            target[1] + target[3] // 2,
        )

    def test_landed_card_is_recorded_at_detected_cell(self) -> None:
        ctx = _ScriptedContext({"32123": _hit((732, 175, 68, 44))})
        result = self._buy(ctx, piece_cell=(0, 2))
        assert result.success is True
        entry = CCChessboard.board[0][2]
        assert entry is not None and entry["name"] == "32123"

    def test_single_slot_card_upgrades_instead_of_taking_new_cell(self) -> None:
        """辅助卡（single_slot）在棋盘上只留 1 个：有同名棋子时直接去升级，不再占新格。

        用户明确「木头妇孺就升级就行了，没必要占俩位置」。
        但它唯一的位置可能被贴纸占着，所以 positions 要给多个备选 ——
        实测 22:29 (1,1) 被小叶尼塞的鸟形贴纸占着，
        商店里 32124 识别分数 0.998 却一直买不进来。
        """
        assert CCChessboard.place_chess(1, 2, "32124") is True
        ctx = _ScriptedContext({})
        img = ctx.tasker.controller.get()
        row, col = CCBuyCard._pick_target_cell("32124", ctx, img, upgrade=True)
        assert (row, col) == (1, 2), "已有 32124 时应回同一格升级，而不是去占 (1,3)"
        assert CCChessboard.is_cell_occupied(ctx, img, 1, 3) is False

    def test_single_slot_card_skips_occupied_first_choice(self) -> None:
        """首选位被别的棋子占着时，辅助卡要顺延到下一个空格。"""
        CCChessboard.board[1][2] = {"name": "sticker", "level": 1, "row": 1, "col": 2}
        ctx = _ScriptedContext({})
        img = ctx.tasker.controller.get()
        row, col = CCBuyCard._pick_target_cell("32124", ctx, img)
        assert (row, col) == (1, 3)

    def test_pool_bad_only_after_five_empty_rounds(self) -> None:
        """连续 5 轮「钱够但没有白名单卡」才判定卡池不符。

        卡包图标判断不了（解包 auto_chess_cardpack 里同一个图标既对应含鹿蜀的卡包、
        也对应不含的，「工具采购」一名 14 个变体），所以只能在局内看商店实际出了什么。
        """
        from custom.reco.critter_crash import CCPoolBadRec

        reco = CCPoolBadRec.__new__(CCPoolBadRec)
        argv = type("Argv", (), {"image": np.zeros((720, 1280, 3), dtype=np.uint8)})()
        for i in range(CCChessboard._POOL_GIVE_UP_AFTER - 1):
            CCChessboard.no_card_streak = i
            assert reco.analyze(_ScriptedContext({}), argv).box is None, f"第 {i} 轮不该判定"
        CCChessboard.no_card_streak = CCChessboard._POOL_GIVE_UP_AFTER
        result = reco.analyze(_ScriptedContext({}), argv)
        assert result.box is not None, "达到阈值应命中，交给 pipeline 点开始战斗"

    def test_pool_bad_skips_refresh_a_finite_number_of_times(self) -> None:
        """判定卡池不符后只跳过有限次刷新，不锁死功能。

        之前用 pool_gave_up 布尔标记 → 判定一次之后刷新被永久挡住
        （实测 08:25 之后再也没刷过）。改成计数后最坏只影响 3 次。
        """
        from custom.reco.critter_crash import CCPoolBadRec

        reco = CCPoolBadRec.__new__(CCPoolBadRec)
        argv = type("Argv", (), {"image": np.zeros((720, 1280, 3), dtype=np.uint8)})()
        CCChessboard.no_card_streak = CCChessboard._POOL_GIVE_UP_AFTER
        CCChessboard.refresh_skip_left = 0

        assert reco.analyze(_ScriptedContext({}), argv).box is not None, "达到阈值应命中"
        assert CCChessboard.refresh_skip_left == CCChessboard._REFRESH_SKIP_AFTER_GIVE_UP
        # 第二次不许把跳过次数重置回满（否则永远 = 3，刷新被永久挡住）
        CCChessboard.refresh_skip_left = 1
        reco.analyze(_ScriptedContext({}), argv)
        assert CCChessboard.refresh_skip_left == 1, "已生效的跳过次数不能被重新拉满"

    def test_refresh_skip_expires(self) -> None:
        """跳过次数用一次扣一次，归零后刷新恢复（不能永久失效）。"""
        from custom.reco.critter_crash import CCRemainMoney

        reco = CCRemainMoney.__new__(CCRemainMoney)
        argv = type(
            "Argv",
            (),
            {
                "image": np.zeros((720, 1280, 3), dtype=np.uint8),
                "custom_recognition_param": '{"type": 1}',
            },
        )()
        CCChessboard.refresh_skip_left = 2
        for left in (1, 0):
            result = reco.analyze(_ScriptedContext({}), argv)
            assert result.box is None, "还有跳过次数时应 miss"
            assert CCChessboard.refresh_skip_left == left

    def test_new_match_detected_by_empty_board(self) -> None:
        """内部有棋子 + 画面全空 = 新对局 → 清空所有按局状态。

        不用回合数 OCR：实测 CCRoundRec 的 hit 恒为 false，全天「检测到新对局」0 次，
        导致按局状态跨局残留。棋盘状态是可靠信号。
        """
        CCChessboard.board[0][2] = {"name": "32123", "level": 1, "row": 0, "col": 2}
        CCChessboard.pool_gave_up = True
        CCChessboard.no_card_streak = 4
        CCChessboard.board_full = True

        ctx = _ScriptedContext({})
        ctx.force_empty_frame = True
        CCChessboard.__new__(CCChessboard)._reset_if_new_game(ctx)

        assert CCChessboard.board[0][2] is None, "内部棋盘应被清空"
        assert CCChessboard.pool_gave_up is False, "按局标记必须复位"
        assert CCChessboard.no_card_streak == 0
        assert CCChessboard.board_full is False

    def test_no_reset_when_board_still_has_pieces(self) -> None:
        """画面里还有棋子 → 还是同一局，不许清状态。"""
        CCChessboard.board[0][2] = {"name": "32123", "level": 1, "row": 0, "col": 2}
        CCChessboard.pool_gave_up = True
        ctx = _ScriptedContext({})   # 桩按内部棋盘渲染 → 画面里也有棋子
        CCChessboard.__new__(CCChessboard)._reset_if_new_game(ctx)
        assert CCChessboard.board[0][2] is not None
        assert CCChessboard.pool_gave_up is True

    def test_pool_gave_up_blocks_refresh_for_whole_match(self) -> None:
        """判定卡池不符后整局不再刷新（新局才复位）。"""
        from custom.reco.critter_crash import CCRemainMoney

        reco = CCRemainMoney.__new__(CCRemainMoney)
        argv = type(
            "Argv",
            (),
            {"image": np.zeros((720, 1280, 3), dtype=np.uint8), "custom_recognition_param": '{"type": 1}'},
        )()
        CCChessboard.pool_gave_up = True
        assert reco.analyze(_ScriptedContext({}), argv).box is None
        # 反复问也一直 miss（不是扣次数那种）
        assert reco.analyze(_ScriptedContext({}), argv).box is None

    def test_skip_expires_after_a_few_attempts(self) -> None:
        """skip 是**有限次数**，不是整回合拉黑。

        原来按回合号记录，一次偶发拖拽失败会把这张卡拉黑好几分钟 ——
        实测 21:03:15 拖 32123 失败后，到 21:03:39 的 6 次识别里鹿蜀模板压根没被调用，
        reco 一直返回「没有找到合适的卡牌」，pipeline 据此刷新商店把鹿蜀刷掉了。
        """
        CCChessboard.skip_buy("32123")
        # 连续跳过 _SKIP_TIMES 次
        assert [CCChessboard.is_buy_skipped("32123") for _ in range(CCChessboard._SKIP_TIMES)] == [
            True
        ] * CCChessboard._SKIP_TIMES
        # 之后自动恢复，不再跳过
        assert CCChessboard.is_buy_skipped("32123") is False
        assert CCChessboard.is_buy_skipped("32123") is False

    def test_skip_does_not_affect_other_cards(self) -> None:
        CCChessboard.skip_buy("32123")
        assert CCChessboard.is_buy_skipped("32124") is False

    def test_card_not_found_marks_skip_but_keeps_task_alive(self) -> None:
        """拖完棋盘没变化 → 本回合跳过该卡，但不返回失败（[JumpBack] 失败会终结任务）。"""
        ctx = _ScriptedContext({})
        result = self._buy(ctx, piece_cell=None)
        assert result.success is True
        assert CCChessboard.is_buy_skipped("32123") is True


class TestUpgradePath:
    """action==1（升级）与 action==0 共用同一套拖拽流程。"""

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_upgrade_uses_same_touch_sequence(self) -> None:
        ctx = _ScriptedContext({})
        ctx.piece_cell = (0, 5)
        _run_buy_card(ctx, {"type": 0, "action": 1, "name": "32123"}, box=(300, 620, 90, 100))
        kinds = [k for k, _, _ in ctx.touches]
        assert kinds[0] == "down" and kinds[-1] == "up"

    def test_picks_first_actually_empty_cell(self) -> None:
        """空格判定看**实际画面**：桩里画面全空 → 返回 positions 第一格 (0,2)。

        不能只看内部棋盘：内部记录一次假成功就会永久分叉，导致反复拖同一格
        （实测巡城兵连续十几次拖到已有鹿蜀的 (0,2)，游戏弹「棋子放置到错误区域」）。
        """
        CCChessboard.place_chess(0, 2, "32123")
        ctx = _ScriptedContext({})
        img = ctx.tasker.controller.get()   # 桩按内部棋盘渲染 → (0,2) 画成占用
        row, col = CCBuyCard._pick_target_cell("32123", ctx, img, upgrade=True)
        assert (row, col) == (2, 2), "(0,2) 已被占，应跳到 (2,2)"

    def test_skips_cell_occupied_in_image(self) -> None:
        """画面里该格有棋子 → 跳过它，选下一格。"""
        ctx = _ScriptedContext({})
        ctx.piece_cell = (0, 2)
        ctx.bought = True          # 让桩在 (0,2) 画出高对比棋子
        img = ctx.tasker.controller.get()
        row, col = CCBuyCard._pick_target_cell("32123", ctx, img, upgrade=True)
        assert (row, col) == (2, 2), "画面里 (0,2) 有棋子，应跳到 (2,2)"

    def test_upgrade_targets_existing_card_when_full(self) -> None:
        """棋盘全满（画面里所有格都有棋子）→ 才返回已有同名棋子的格去升级。"""
        for r, c in [(0, 2), (2, 2), (0, 3), (2, 3), (0, 4), (2, 4), (0, 5), (2, 5)]:
            CCChessboard.board[r][c] = {"name": "32123", "level": 1, "row": r, "col": c}
        ctx = _ScriptedContext({})
        ctx.all_occupied = True   # 画面里所有格都有棋子
        img = ctx.tasker.controller.get()
        row, col = CCBuyCard._pick_target_cell("32123", ctx, img, upgrade=True)
        assert (row, col) == (0, 2), "全满时应返回第一个可升级的同名棋子格"

    def test_upgrade_keeps_target_cell_record(self) -> None:
        """落点判据只看目标格，不受画面其它变化干扰。"""
        for r, c in [(0, 2), (2, 2), (0, 3), (2, 3), (0, 4), (2, 4), (0, 5), (2, 5)]:
            CCChessboard.board[r][c] = {"name": "32123", "level": 1, "row": r, "col": c}
        ctx = _ScriptedContext({})
        ctx.piece_cell = (0, 2)
        ctx.extra_changed = [(2, 5)]
        _run_buy_card(ctx, {"type": 0, "action": 1, "name": "32123"}, box=(300, 620, 90, 100))
        assert CCChessboard.board[0][2] is not None


class TestJumpBackActionMustNotFail:
    """以 [JumpBack] 挂载、且父列表末尾的 action 不许返回失败。

    框架语义（PipelineTask.cpp:68-75）：动作成功 → 轮询 node.next；
    动作失败 → 走 node.on_error。本节点没有 on_error，一旦失败 next 为空、
    任务直接以 4000 收场 —— 实测「贴纸跳过」那一步就成了最后一个节点。
    """

    def test_sticker_action_never_returns_failure(self) -> None:
        """CCSticker 的每个提前返回都必须是 success=True。"""
        import inspect

        source = inspect.getsource(CCSticker.run)
        assert "success=False" not in source, (
            "CCSticker 以 [JumpBack] 挂载且没有 on_error，返回 False 会让任务 4000 终止"
        )

    def test_sticker_runs_before_buy_card(self) -> None:
        """贴纸箱必须排在买卡**之前**。

        买卡几乎每轮都命中（实测一轮 70 次），贴纸挂在它后面就永远轮不到 ——
        表现为「贴纸一次都没开过」（实测 12:44 那轮 CCSticker 节点 0 次）。
        这条锁定顺序，防止回退。
        """
        text = (PROJECT_ROOT / "resource/base/pipeline/activity/CritterCrash.json").read_text(encoding="utf-8")
        assert '"[JumpBack]CCSticker"' in text
        assert text.index('"[JumpBack]CCSticker"') < text.index('"[JumpBack]CCBuyCard"')


class TestBoardDataConsistency:
    """board 与 board_chesses 必须共享同一 dict —— 分叉会导致无限重复升级。

    实测（2026-10-22）：两处各造一个 dict 时，upgrade_chess 涨的是 board 那份、
    can_upgrade_existing 读的是 board_chesses 那份，于是同一个位置被连升 11 次、
    每次 3-5 秒，整局时间全耗在重复升级上，买卡/刷新都被挤掉。
    """

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_place_chess_shares_one_dict(self) -> None:
        assert CCChessboard.place_chess(0, 2, "32123") is True
        entry = CCChessboard.board[0][2]
        assert entry is not None
        assert any(item is entry for item in CCChessboard.board_chesses), (
            "board_chesses 必须持有与 board 相同的对象引用"
        )

    def test_upgrade_reflected_in_board_chesses(self) -> None:
        assert CCChessboard.place_chess(0, 2, "32123") is True
        assert CCChessboard.upgrade_chess(0, 2) is True
        assert CCChessboard.upgrade_chess(0, 2) is True
        item = next(i for i in CCChessboard.board_chesses if i["row"] == 0 and i["col"] == 2)
        assert item["level"] == 2, "升级后 board_chesses 里的 level 必须同步（共享对象）"

    def test_can_upgrade_false_after_max_level(self) -> None:
        """升到上限后 can_upgrade_existing 必须立刻为 False，否则会无限重试。"""
        assert CCChessboard.place_chess(0, 2, "32123") is True
        while CCChessboard.upgrade_chess(0, 2):
            pass
        assert CCChessboard.can_upgrade_existing("32123") is False


class TestNewGameReset:
    """回合数变小 = 新对局，必须清空内部棋盘。

    不清的话：一局打完棋盘状态残留，第二局 find_empty_position 对所有卡都返回 None，
    买卡全部 miss，只剩刷新把好卡刷掉（实测 rA 局：第 13 回合起买卡/部署/升级全为 0，
    刷新 2~5 次/回合）。
    """

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_board_fills_then_blocks_all_buys(self) -> None:
        """铺满后所有卡都无处可放 —— 这就是跨局不清空会出现的状态。"""
        for name in ("32122", "32123"):
            while True:
                pos = CCChessboard.find_empty_position(name)
                if pos is None:
                    break
                assert CCChessboard.place_chess(pos[0], pos[1], name) is True
        assert CCChessboard.find_empty_position("32123") is None

    def test_board_reset_restores_placements(self) -> None:
        CCChessboard.place_chess(0, 2, "32123")
        assert CCChessboard.find_empty_position("32123") is not None
        CCChessboard.board_reset()
        assert CCChessboard.board_chesses == []
        assert CCChessboard.find_empty_position("32123") is not None

    def test_last_round_defaults_none_and_clears(self) -> None:
        CCChessboard._last_round = 9
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))
        assert CCChessboard._last_round is None


class TestClearLeader:
    """兜底选领队必须能真正清空 leader_id（set_leader(None) 有粘性保护）。"""

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_clear_leader_bypasses_stickiness(self) -> None:
        CCChessboard.set_leader("30027")
        CCChessboard.set_leader(None)      # 被粘性保护挡住
        assert CCChessboard.leader_id == "30027"
        CCChessboard.clear_leader()        # 显式清空
        assert CCChessboard.leader_id is None


class TestBoardFullShortCircuit:
    """棋盘满时买卡识别必须短路，否则详情面板反复弹出挡住后续识别。"""

    def setup_method(self) -> None:
        CCChessboard.apply_strategy(load_strategy(PROJECT_ROOT / STRATEGY_4_0_PATH))

    def teardown_method(self) -> None:
        CCChessboard.apply_strategy(BASE_STRATEGY)

    def test_has_no_empty_cell_false_when_empty(self) -> None:
        assert CCChessboard.has_no_empty_cell() is False

    def test_has_no_empty_cell_true_when_all_filled(self) -> None:
        for row in range(len(CCChessboard.board)):
            for col in range(len(CCChessboard.board[row])):
                CCChessboard.board[row][col] = {"name": "32123", "level": 1, "row": row, "col": col}
        assert CCChessboard.has_no_empty_cell() is True
