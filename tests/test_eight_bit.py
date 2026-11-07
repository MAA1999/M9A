from collections import Counter

import numpy as np

from agent.custom.action.eight_bit import (
    BUY_BUTTON_ROI,
    DANGER,
    DOWN,
    FREE,
    HOLDOUT_ROUTE,
    LEFT,
    MOVE_CLICK_POSITIONS,
    OCCUPIED,
    OFF,
    RIGHT,
    SEARCH_ROUTE,
    UP,
    Board,
    MoveParams,
    buy_button_ready,
    clear_move,
    find_player,
    objective_phase,
    parse_count,
    parse_move_params,
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
    assert objective_phase("坚持43回合") == "holdout"
    assert objective_phase("击败所有怪物") == "clear"
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


def test_clear_sidesteps_blocked_approach() -> None:
    # 正左方有预警，怪物在左上：改走竖直轴
    assert clear_move(_board(l4_u3=OCCUPIED, l1_d0=DANGER), RIGHT) == UP


def test_clear_never_steps_into_warning_when_standing_safe() -> None:
    board = _board(l4_d0=OCCUPIED, l1_d0=DANGER)
    assert clear_move(board, RIGHT) is None


def test_clear_leaves_warning_cell() -> None:
    board = _board(own_danger=True, r2_d0=OCCUPIED, r1_d0=DANGER, r0_u1=DANGER, l1_d0=DANGER)
    assert clear_move(board, RIGHT) == DOWN


def test_clear_leaves_warning_cell_even_if_all_neighbours_warn() -> None:
    board = _board(own_danger=True, r1_d0=DANGER, l1_d0=DANGER, r0_u1=DANGER, r0_d1=DANGER)
    assert clear_move(board, RIGHT) in (UP, DOWN, LEFT, RIGHT)


def test_clear_never_walks_off_board() -> None:
    assert clear_move(_board(r1_d0=OFF), RIGHT) is None


def test_toward_prefers_longer_axis() -> None:
    assert toward((3, -1)) == [RIGHT, UP]
    assert toward((0, 4)) == [DOWN]
    assert toward((-1, -2)) == [UP, LEFT]


def test_find_player_locates_orange_corners() -> None:
    img = np.zeros((720, 1280, 3), np.uint8)
    img[:, :] = (90, 140, 140)  # BGR 地板色
    orange = (66, 165, 245)  # BGR 角标色
    left, top, span = 606, 326, 67
    img[top : top + 3, left : left + 14] = orange
    img[top : top + 14, left : left + 3] = orange
    right, bottom = left + span, top + span
    img[bottom - 2 : bottom + 1, right - 13 : right + 1] = orange
    img[bottom - 13 : bottom + 1, right - 2 : right + 1] = orange
    pos = find_player(img)
    assert pos is not None
    # 格子边长 60px，定位差 1~2px 不影响判格
    assert abs(pos[0] - (left + span // 2)) <= 2
    assert abs(pos[1] - (top + span // 2)) <= 2


def test_find_player_none_without_bracket() -> None:
    assert find_player(np.zeros((720, 1280, 3), np.uint8)) is None


# ---- 商店


def test_wanted_relic_matches_whitelist_and_fragments() -> None:
    assert wanted_relic("仪式短剑") == "仪式短剑"
    assert wanted_relic("槲寄生种") == "槲寄生种子"
    assert wanted_relic("幸运金币链") is None
    assert wanted_relic("光荣信符") is None
    assert wanted_relic("笔") is None
    assert wanted_relic("") is None


def test_slot_of_maps_title_centres() -> None:
    # 实测商品名中心 x：171 / 493 / 795 / 1108
    assert [slot_of(x) for x in (171, 493, 795, 1108)] == [0, 1, 2, 3]


def test_buy_button_ready_by_colour() -> None:
    x, y, w, h = BUY_BUTTON_ROI
    img = np.zeros((720, 1280, 3), np.uint8)
    img[y : y + h, x : x + w] = (33, 118, 199)  # BGR 橙色
    assert buy_button_ready(img)
    img[y : y + h, x : x + w] = (128, 128, 128)  # 灰色
    assert not buy_button_ready(img)


# ---- 参数与结算


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


def test_move_params_ignore_invalid_values() -> None:
    raw = '{"move_input": "mouse", "interval_ms": 0, "level_timeout_s": true}'
    assert parse_move_params(raw) == MoveParams()
    assert parse_move_params("{not json") == MoveParams()
