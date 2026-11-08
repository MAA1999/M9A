from collections import Counter
from types import SimpleNamespace

import numpy as np

import agent.custom.action.eight_bit as eight_bit
from agent.custom.action.eight_bit import (
    BUY_BUTTON_ROI,
    CLEAR,
    DANGER,
    DOWN,
    FREE,
    HOLDOUT,
    HOLDOUT_ROUTE,
    HUNT_MAX_MONSTERS,
    LEFT,
    MOVE_CLICK_POSITIONS,
    MOVE_CYCLE,
    MOVE_STRATEGY_CYCLE,
    MOVE_STRATEGY_HYBRID,
    MOVE_STRATEGY_SMART,
    OBJECTIVE_ROI,
    OCCUPIED,
    OFF,
    RIGHT,
    SEARCH_ROUTE,
    SHOP_TITLES,
    UP,
    Board,
    EightBitCombatMove,
    MoveParams,
    buy_button_ready,
    classify_cell,
    clear_move,
    cycle_key,
    efficiency_per_hour,
    escape_key,
    fallback_key,
    find_player,
    forced_move,
    hunt_target,
    next_level_start,
    objective_phase,
    parse_count,
    parse_move_params,
    read_board,
    round_from_objective,
    route_key,
    safe_key,
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


def test_cycle_key_repeats_up_left_down_right() -> None:
    assert MOVE_CYCLE == (UP, LEFT, DOWN, RIGHT)
    assert [cycle_key(step) for step in range(8)] == [UP, LEFT, DOWN, RIGHT] * 2
    assert set(MOVE_CYCLE) <= MOVE_CLICK_POSITIONS.keys()


# ---- 混合策略：固定节奏 + 怪少时主动靠近


def test_hunt_target_goes_for_straggler_outside_weapon_range() -> None:
    assert hunt_target(_board(l4_u1=OCCUPIED)) == (-4, -1)


def test_hunt_target_ignores_monster_already_in_weapon_range() -> None:
    assert hunt_target(_board(r2_d2=OCCUPIED)) is None


def test_hunt_target_ignores_crowd() -> None:
    board = _board(r4_d0=OCCUPIED, l4_d0=OCCUPIED, r0_u4=OCCUPIED)
    assert len(board.monsters()) > HUNT_MAX_MONSTERS
    assert hunt_target(board) is None


def test_hunt_target_none_without_monsters() -> None:
    assert hunt_target(_board()) is None


def test_safe_key_prefers_first_free_direction() -> None:
    assert safe_key(_board(), [UP, LEFT]) == UP


def test_safe_key_skips_warning_and_occupied_cells() -> None:
    board = _board(r0_u1=DANGER, l1_d0=OCCUPIED)
    assert safe_key(board, [UP, LEFT, DOWN]) == DOWN


def test_safe_key_none_when_every_direction_is_blocked() -> None:
    board = _board(r0_u1=DANGER, r1_d0=OCCUPIED, r0_d1=OCCUPIED, l1_d0=OFF)
    assert safe_key(board, [UP, RIGHT, DOWN, LEFT]) is None


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


def test_next_level_start_keeps_timer_within_same_level() -> None:
    # 回合数在变小 = 同一关被 OCR 抖动判回，沿用旧起点
    assert next_level_start(100.0, HOLDOUT, 40, HOLDOUT, 38, 140.0) == 100.0
    # 读不到目标（已离开关卡）时也沿用，交给下一帧判断
    assert next_level_start(100.0, HOLDOUT, 40, None, None, 140.0) == 100.0


def test_next_level_start_resets_on_new_level() -> None:
    # 回合数变大 = 新的一关
    assert next_level_start(100.0, HOLDOUT, 3, HOLDOUT, 45, 140.0) == 140.0
    # 上一次已经是清场阶段，又回到坚持阶段 = 新的一关
    assert next_level_start(100.0, CLEAR, None, HOLDOUT, 45, 140.0) == 140.0
    # 没有历史状态
    assert next_level_start(None, None, None, HOLDOUT, 45, 140.0) == 140.0


def test_round_from_objective() -> None:
    assert round_from_objective("坚持45回合") == 45
    assert round_from_objective("坚持 7 回合") == 7
    assert round_from_objective("击败所有怪物") is None


class _Job:
    """假的 Job：wait() 返回自身，get() 返回载荷。"""

    def __init__(self, payload: object = None) -> None:
        self._payload = payload

    def wait(self) -> "_Job":
        return self

    def get(self) -> object:
        return self._payload


class _Detail:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeController:
    def __init__(self, screens: list[str | None]) -> None:
        self.screens = screens
        self.clicks: list[tuple[int, int]] = []

    def post_screencap(self) -> _Job:
        payload = self.screens.pop(0) if self.screens else None
        return _Job(payload)

    def post_click(self, x: int, y: int) -> _Job:
        self.clicks.append((x, y))
        return _Job()

    def post_click_key(self, code: int) -> _Job:
        self.clicks.append((code, 0))
        return _Job()


class _FakeTasker:
    def __init__(self, controller: _FakeController) -> None:
        self.controller = controller
        self.stopping = False


class _FakeContext:
    def __init__(self, screens: list[str | None]) -> None:
        self.tasker = _FakeTasker(_FakeController(screens))

    def run_recognition_direct(self, reco_type: object, param: object, img: object) -> object:
        """只对关卡目标 ROI 返回文本；商店 / 结算页一律未命中。"""
        if tuple(getattr(param, "roi", ())) != OBJECTIVE_ROI:
            return None
        return _Detail(img) if isinstance(img, str) else None


def _run_level(screens: list[str | None], monkeypatch, *, reset: bool = False) -> tuple[_FakeContext, object]:
    context = _FakeContext(screens)
    argv = SimpleNamespace(custom_action_param='{"interval_ms": 1}')
    monkeypatch.setattr(eight_bit, "is_hit", lambda detail: detail is not None)
    monkeypatch.setattr(eight_bit, "ocr_text", lambda detail, default="": getattr(detail, "text", default))
    if reset:
        EightBitCombatMove._forget_level()
    result = EightBitCombatMove().run(context, argv)  # type: ignore[arg-type]
    return context, result


def test_run_keeps_level_timer_across_reentry(monkeypatch) -> None:
    """OCR 抖动导致退出后又被判回同一关时，计时起点不变（回归：之前末尾把起点清空了）。"""
    _run_level(["坚持45回合", "坚持44回合", None, None], monkeypatch, reset=True)
    first = EightBitCombatMove._level_started
    assert first is not None

    _run_level(["坚持43回合", None, None], monkeypatch)
    assert EightBitCombatMove._level_started == first

    # 回合数回到 45 = 新的一关，计时重置
    _run_level(["坚持45回合", None, None], monkeypatch)
    assert EightBitCombatMove._level_started is not None
    assert EightBitCombatMove._level_started > first


def test_run_moves_during_holdout(monkeypatch) -> None:
    context, _ = _run_level(["坚持40回合", "坚持39回合", None, None], monkeypatch, reset=True)
    assert context.tasker.controller.clicks, "坚持阶段应当在移动"


def test_run_holdout_follows_up_left_down_right(monkeypatch) -> None:
    """坚持阶段不读棋盘，按 上→左→下→右 固定节奏走。"""
    context, _ = _run_level(["坚持40回合", "坚持39回合", None, None], monkeypatch, reset=True)
    assert context.tasker.controller.clicks == [MOVE_CLICK_POSITIONS[UP], MOVE_CLICK_POSITIONS[LEFT]]


def test_run_hybrid_hunts_straggler_in_clear_phase(monkeypatch) -> None:
    """清场阶段只剩一只远处的怪：主动朝它走，而不是只按固定节奏。"""
    monkeypatch.setattr(eight_bit, "read_board", lambda img: _board(l4_d0=OCCUPIED))
    context, _ = _run_level(["击败所有怪物", "击败所有怪物", None, None], monkeypatch, reset=True)
    assert context.tasker.controller.clicks[0] == MOVE_CLICK_POSITIONS[LEFT]


def test_run_times_out_only_while_level_is_still_visible(monkeypatch) -> None:
    """同一次调用内：读到过目标、跑满超时后本帧目标消失 → 必须按「本关结束」返回成功。

    这条锁的是超时分支上的 `phase is not None` 门控：去掉它，第二帧就会因为
    `tick - started > level_timeout_s` 直接返回失败（过场帧里商店 / 结算页还没渲染出来）。
    """

    def _run_with_clock(screens: list[str | None], *, step_s: float) -> object:
        context = _FakeContext(screens)
        clock = [1000.0]

        def _tick() -> float:
            now = clock[0]
            clock[0] += step_s
            return now

        fake_time = SimpleNamespace(time=_tick, sleep=lambda _s: None, monotonic=_tick)
        monkeypatch.setattr(eight_bit, "time", fake_time)
        monkeypatch.setattr(eight_bit, "is_hit", lambda detail: detail is not None)
        monkeypatch.setattr(eight_bit, "ocr_text", lambda detail, default="": getattr(detail, "text", default))
        EightBitCombatMove._forget_level()
        argv = SimpleNamespace(custom_action_param='{"interval_ms": 1}')
        return EightBitCombatMove().run(context, argv)  # type: ignore[arg-type]

    # 首帧读到目标（t=1000），次帧已超时（160s > 150s）且目标消失 → 本关其实结束了
    assert _run_with_clock(["坚持30回合", None, None], step_s=160.0).success

    # 首帧 t=1000 读到目标，次帧 t=1040 仍读得到目标但没超时；第三帧 t=1200 仍读得到 → 真卡住
    assert not _run_with_clock(["坚持30回合", "坚持29回合", "坚持28回合"], step_s=200.0).success


def test_fallback_steps_into_warning_when_boxed_in(monkeypatch) -> None:
    """脚下在预警里、四个邻格也都在预警里时，要挪一格而不是原地挨打。"""
    board = _board(own_danger=True, r1_d0=DANGER, l1_d0=DANGER, r0_u1=DANGER, r0_d1=DANGER)
    assert fallback_key(board, RIGHT) in (UP, DOWN, LEFT)
    assert escape_key(board) is not None


def test_fallback_works_without_last_key(monkeypatch) -> None:
    """清场阶段重入时 last_key 还是 None，同样要能挑方向。"""
    assert fallback_key(_board(), None) is not None


def test_fallback_prefers_free_cell_over_warning_in_last_direction() -> None:
    """唯一空邻格正好是上一步的方向时也要走它，不能平白走进预警格。"""
    board = Board(
        own_danger=True,
        cells={(1, 0): FREE, (0, -1): DANGER, (0, 1): DANGER, (-1, 0): DANGER},
    )
    assert forced_move(board, RIGHT) == RIGHT
    assert fallback_key(board, RIGHT) == RIGHT


def test_escape_key_only_when_standing_on_warning() -> None:
    dangerous = Board(own_danger=True, cells={(1, 0): DANGER, (0, -1): DANGER, (0, 1): DANGER, (-1, 0): DANGER})
    safe = Board(own_danger=False, cells={(1, 0): DANGER, (0, -1): DANGER, (0, 1): DANGER, (-1, 0): DANGER})
    assert escape_key(dangerous) in (UP, DOWN, LEFT, RIGHT)
    assert escape_key(safe) is None


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


def test_move_params_strategy_defaults_to_hybrid() -> None:
    assert parse_move_params(None).move_strategy == MOVE_STRATEGY_HYBRID
    assert parse_move_params('{"move_strategy": "cycle"}').move_strategy == MOVE_STRATEGY_CYCLE
    assert parse_move_params('{"move_strategy": "smart"}').move_strategy == MOVE_STRATEGY_SMART
    assert parse_move_params('{"move_strategy": "random"}').move_strategy == MOVE_STRATEGY_HYBRID
