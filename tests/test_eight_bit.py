from collections import Counter

import numpy as np

from agent.custom.action.eight_bit import (
    BUY_BUTTON_ROI,
    CLEAR,
    DANGER,
    DOWN,
    FREE,
    HOLDOUT,
    HOLDOUT_ROUTE,
    LEFT,
    MOVE_CLICK_POSITIONS,
    OCCUPIED,
    OFF,
    RIGHT,
    SEARCH_ROUTE,
    SHOP_TITLES,
    UP,
    Board,
    MoveParams,
    buy_button_ready,
    classify_cell,
    clear_move,
    efficiency_per_hour,
    find_player,
    forced_move,
    objective_phase,
    parse_count,
    parse_move_params,
    read_board,
    resolve_level_start,
    route_key,
    slot_of,
    toward,
    wanted_relic,
)


def _board(own_danger: bool = False, **cells: str) -> Board:
    """Board whose unspecified cells are free. Keys look like ``r1_d0`` (right 1, down 0) or ``l4_u1``."""
    grid: dict[tuple[int, int], str] = {}
    for j in range(-4, 5):
        for i in range(-4, 5):
            if (i, j) != (0, 0):
                grid[(i, j)] = FREE
    for key, state in cells.items():
        dx, dy = (int(part[1:]) * (1 if part[0] in "rd" else -1) for part in key.split("_"))
        grid[(dx, dy)] = state
    return Board(own_danger=own_danger, cells=grid)


def _frame(size: tuple[int, int] = (720, 1280)) -> np.ndarray:
    """BGR 空棋盘：地板色 (140,140,90)、棋盘范围外暗一些。"""
    img = np.zeros((*size, 3), np.uint8)
    img[:, :] = (90, 140, 140)
    return img


def _paint_cell(img: np.ndarray, x: int, y: int, colour: tuple[int, int, int], half: int = 20) -> None:
    img[y - half : y + half, x - half : x + half] = colour


def _paint_player(img: np.ndarray, left: int, top: int, span: int = 67) -> None:
    orange = (66, 165, 245)
    img[top : top + 3, left : left + 14] = orange
    img[top : top + 14, left : left + 3] = orange
    right, bottom = left + span, top + span
    img[bottom - 2 : bottom + 1, right - 13 : right + 1] = orange
    img[bottom - 13 : bottom + 1, right - 2 : right + 1] = orange


# ---- 棋盘读取（图像级，覆盖 颜色判据 → 棋盘状态 → 移动方向 的联动）


def test_read_board_marks_monster_warning_and_off_board() -> None:
    img = _frame()
    _paint_player(img, 606, 326)
    # 以玩家格心 (639, 359) 为原点：右侧 2 格放蓝紫色怪物，左侧 1 格放预警格
    _paint_cell(img, 639 + 120, 359, (200, 90, 60))
    _paint_cell(img, 639 - 60, 359, (60, 70, 90))
    board = read_board(img)
    assert board.cells[(2, 0)] == OCCUPIED
    assert board.cells[(-1, 0)] == DANGER
    assert board.cells[(0, -1)] == FREE
    # 棋盘右边界外（x > 940）不可达，判为 OFF
    assert classify_cell(img, 1000, 359) == OFF


def test_read_board_then_clear_move_walks_to_monster() -> None:
    img = _frame()
    _paint_player(img, 606, 326)
    _paint_cell(img, 639 + 180, 359, (200, 90, 60))  # 右侧 3 格
    board = read_board(img)
    assert board.nearest_monster() == (3, 0)
    assert clear_move(board, RIGHT) == RIGHT


def test_read_board_then_clear_move_stops_in_range() -> None:
    img = _frame()
    _paint_player(img, 606, 326)
    _paint_cell(img, 639 + 60, 359, (200, 90, 60))  # 右侧 1 格，已在武器范围
    board = read_board(img)
    assert clear_move(board, RIGHT) is None


def test_read_board_detects_warning_under_player() -> None:
    img = _frame()
    _paint_player(img, 606, 326)
    # 玩家格被预警染红（角标区域之外的两块采样角也要红）
    _paint_cell(img, 639, 359, (60, 70, 90), half=29)
    board = read_board(img)
    assert board.own_danger


# ---- 巡逻路线


def test_holdout_route_walks_right_then_left_and_repeats() -> None:
    route = [route_key(HOLDOUT_ROUTE, step) for step in range(20)]
    assert route[:10] == [RIGHT] * 5 + [LEFT] * 5
    assert route[10:] == route[:10]


def test_routes_return_to_start() -> None:
    for route in (HOLDOUT_ROUTE, SEARCH_ROUTE):
        counts = Counter(route)
        assert counts[RIGHT] == counts[LEFT]
        assert counts[UP] == counts[DOWN]


def test_route_keys_all_have_click_positions() -> None:
    assert set(HOLDOUT_ROUTE) | set(SEARCH_ROUTE) <= MOVE_CLICK_POSITIONS.keys()


def test_objective_phase() -> None:
    assert objective_phase("坚持43回合") == HOLDOUT
    assert objective_phase("击败所有怪物") == CLEAR
    assert objective_phase("击败战争型火炮") is None
    assert objective_phase("") is None


# ---- 清场阶段


def test_clear_walks_toward_far_monster() -> None:
    assert clear_move(_board(l4_u1=OCCUPIED), RIGHT) == LEFT
    assert clear_move(_board(r1_d4=OCCUPIED), RIGHT) == DOWN


def test_clear_waits_when_monster_in_weapon_range() -> None:
    assert clear_move(_board(r2_d2=OCCUPIED), RIGHT) is None


def test_clear_searches_along_route_without_monster() -> None:
    assert clear_move(_board(), UP) == UP


def test_clear_switches_direction_when_search_is_blocked() -> None:
    # 搜索方向向右但右邻有预警：换到别的空邻格，而不是原地不动
    board = _board(r1_d0=DANGER)
    assert clear_move(board, RIGHT) in (UP, DOWN, LEFT)


def test_clear_sidesteps_blocked_approach() -> None:
    assert clear_move(_board(l4_u3=OCCUPIED, l1_d0=DANGER), RIGHT) == UP


def test_clear_never_steps_into_warning_when_standing_safe() -> None:
    assert clear_move(_board(l4_d0=OCCUPIED, l1_d0=DANGER), RIGHT) is None


def test_clear_leaves_warning_cell() -> None:
    board = _board(own_danger=True, r2_d0=OCCUPIED, r1_d0=DANGER, r0_u1=DANGER, l1_d0=DANGER)
    assert clear_move(board, RIGHT) == DOWN


def test_clear_leaves_warning_cell_even_if_all_neighbours_warn() -> None:
    board = _board(own_danger=True, r1_d0=DANGER, l1_d0=DANGER, r0_u1=DANGER, r0_d1=DANGER)
    assert clear_move(board, RIGHT) in (UP, DOWN, LEFT, RIGHT)


def test_clear_never_walks_off_board() -> None:
    assert clear_move(_board(r1_d0=OFF), RIGHT) is not None


def test_forced_move_breaks_idle_stall() -> None:
    board = _board(r1_d0=OFF, l1_d0=OFF, r0_u1=OFF, r0_d1=OFF)
    assert forced_move(board, RIGHT) is None
    board = _board()
    assert forced_move(board, RIGHT) in (UP, DOWN, LEFT)


def test_toward_prefers_longer_axis() -> None:
    assert toward((3, -1)) == [RIGHT, UP]
    assert toward((0, 4)) == [DOWN]
    assert toward((-1, -2)) == [UP, LEFT]


def test_find_player_locates_orange_corners() -> None:
    img = _frame()
    _paint_player(img, 606, 326)
    pos = find_player(img)
    assert pos is not None
    assert abs(pos[0] - 639) <= 2
    assert abs(pos[1] - 359) <= 2


def test_find_player_none_without_bracket() -> None:
    assert find_player(_frame()) is None


# ---- 商店


def test_shop_titles_cover_both_names() -> None:
    assert SHOP_TITLES == ["地下流通处", "秘密交易处"]


def test_wanted_relic_matches_whitelist_and_fragments() -> None:
    assert wanted_relic("仪式短剑") == "仪式短剑"
    assert wanted_relic("槲寄生种") == "槲寄生种子"
    assert wanted_relic("幸运金币链") is None
    assert wanted_relic("光荣信符") is None
    assert wanted_relic("笔") is None
    assert wanted_relic("") is None


def test_slot_of_maps_title_centres() -> None:
    assert [slot_of(x) for x in (171, 493, 795, 1108)] == [0, 1, 2, 3]


def test_buy_button_ready_by_colour() -> None:
    x, y, w, h = BUY_BUTTON_ROI
    img = _frame()
    img[y : y + h, x : x + w] = (33, 118, 199)  # BGR 橙色
    assert buy_button_ready(img)
    img[y : y + h, x : x + w] = (128, 128, 128)  # 灰色
    assert not buy_button_ready(img)


# ---- 结算与参数


def test_efficiency_excludes_first_settlement() -> None:
    # 两局各 30 个、间隔 180 秒：只算第二局 → 600 个/小时
    assert efficiency_per_hour(total=60, first_count=30, elapsed_s=180) == 600
    assert efficiency_per_hour(total=60, first_count=30, elapsed_s=0) is None


def test_resolve_level_start_keeps_timer_on_quick_reentry() -> None:
    assert resolve_level_start(prev_start=100.0, last_exit_at=120.0, now=123.0, window_s=5.0) == 100.0
    assert resolve_level_start(prev_start=100.0, last_exit_at=120.0, now=140.0, window_s=5.0) == 140.0
    assert resolve_level_start(prev_start=None, last_exit_at=0.0, now=140.0, window_s=5.0) == 140.0


def test_parse_count() -> None:
    assert parse_count("30") == 30
    assert parse_count("x30") == 30
    assert parse_count("") is None
    assert parse_count("卡带") is None


def test_move_params_defaults() -> None:
    assert parse_move_params(None) == MoveParams()
    assert parse_move_params("null") == MoveParams()


def test_move_params_accept_overrides() -> None:
    assert parse_move_params('{"move_input": "key", "interval_ms": 400, "level_timeout_s": 120}') == MoveParams(
        move_input="key", interval_ms=400, level_timeout_s=120.0
    )


def test_move_params_reject_fractional_and_unbounded_interval() -> None:
    assert parse_move_params('{"interval_ms": 0.5}').interval_ms == 500
    assert parse_move_params('{"interval_ms": 0}').interval_ms == 500
    assert parse_move_params('{"interval_ms": 1e999}').interval_ms == 500


def test_move_params_ignore_invalid_values() -> None:
    raw = '{"move_input": "mouse", "interval_ms": 0, "level_timeout_s": true}'
    assert parse_move_params(raw) == MoveParams()
    assert parse_move_params("{not json") == MoveParams()
