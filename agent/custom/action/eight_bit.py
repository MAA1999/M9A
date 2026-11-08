"""
8-bit 街机秀（4.1「幸存者游戏」）。

玩法是回合制棋盘：玩家每次移动一格就结束一回合，不动则约 1 秒后超时进入下一回合；武器每 3 回合
自动攻击以玩家为中心的 5×5。怪物攻击前会先在目标格上画出红色预警，目标格在施放时就固定了，
不会跟着玩家走。

普通关的移动规则（move_strategy=hybrid，默认）：
- 平时不读棋盘，按 上 → 左 → 下 → 右 的顺序循环点击十字键：一直在动就躲得开预警。
- 清场阶段看到的怪不多（≤ HUNT_MAX_MONSTERS）且最近的怪也在武器范围外时，主动朝它走一步
  （避开预警格和有单位的格子）：落单的怪不一定主动过来，只靠固定节奏永远走不到它跟前。
- 清场阶段连续 SEARCH_AFTER_STEPS 步一只怪都看不到，就按十字路线走大圈扩大视野找怪。
- move_strategy=cycle 时始终固定节奏；smart 时走原来的读棋盘打法：「坚持N回合」阶段左右来回巡逻；
  「击败所有怪物」阶段每步读棋盘，朝最近的怪物走，走到 2 格内（武器范围）就停下等武器输出；
  看不到怪物时走十字找怪；脚下出现预警就先躲到没有预警的邻格。
  连续多步都不动（把静态装饰误判成怪物也走这条路）时强制换方向，免得站到单关超时。
难度Ⅰ第一阶段实测：左右巡逻 3 个普通关全部满血通关；站着不动则 3 次都在第 1 关被打死。

关卡之间的商店「地下流通处」：从左到右买下买得起的纯属性缪斯秘宝（白名单），首领关前的商店不买。
坐标与颜色阈值都是 1280×720 实测值；框架截图是 BGR。
"""

import math
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JOCR, JRecognitionType
from utils import logger
from utils.maa_types import is_hit, ocr_results, ocr_text
from utils.params import parse_params

KEYCODE_DPAD_UP = 19
KEYCODE_DPAD_DOWN = 20
KEYCODE_DPAD_LEFT = 21
KEYCODE_DPAD_RIGHT = 22
UP, DOWN, LEFT, RIGHT = KEYCODE_DPAD_UP, KEYCODE_DPAD_DOWN, KEYCODE_DPAD_LEFT, KEYCODE_DPAD_RIGHT
DIRECTIONS: tuple[int, ...] = (UP, DOWN, LEFT, RIGHT)
STEP: dict[int, tuple[int, int]] = {UP: (0, -1), DOWN: (0, 1), LEFT: (-1, 0), RIGHT: (1, 0)}

# 左下角十字键的四个方向按钮
MOVE_CLICK_POSITIONS: dict[int, tuple[int, int]] = {
    UP: (177, 472),
    DOWN: (174, 625),
    LEFT: (95, 543),
    RIGHT: (259, 548),
}

# 进入对局后的默认移动：按 上 → 左 → 下 → 右 顺序循环点击
MOVE_CYCLE: tuple[int, ...] = (UP, LEFT, DOWN, RIGHT)
MOVE_STRATEGY_HYBRID, MOVE_STRATEGY_CYCLE, MOVE_STRATEGY_SMART = "hybrid", "cycle", "smart"

# 清场阶段可见的怪不超过这个数量、且最近的怪也在武器范围外时，主动朝它走：
# 落单的怪不一定主动过来，只靠固定节奏永远走不到它跟前，会拖到单关超时
HUNT_MAX_MONSTERS = 2
# 清场阶段连续这么多步一只怪都看不到，就按十字路线走大圈扩大视野找怪
SEARCH_AFTER_STEPS = 6

# 两条巡逻路线都会回到起点：玩家从 32×32 地图中央出生，走不到地图边缘
# 坚持阶段：往右 5 格、往左 5 格
HOLDOUT_ROUTE: tuple[int, ...] = (RIGHT,) * 5 + (LEFT,) * 5
# 清场阶段看不到怪物时：右、左、上、下各走 4 格再走回来（十字），扩大视野找怪
SEARCH_ROUTE: tuple[int, ...] = (RIGHT,) * 4 + (LEFT,) * 8 + (RIGHT,) * 4 + (UP,) * 4 + (DOWN,) * 8 + (UP,) * 4

# 普通关左上角的关卡目标：先是「坚持N回合」，归零后变成「击败所有怪物」
OBJECTIVE_ROI: tuple[int, int, int, int] = (60, 60, 200, 40)
NORMAL_OBJECTIVES: list[str] = ["坚持\\d+回合", "击败所有怪物"]
HOLDOUT, CLEAR = "holdout", "clear"

# 普通关可见棋盘（x0, y0, x1, y1）与格子边长。镜头跟随玩家，玩家格中心一般就在棋盘中心；
# 可见范围是 10×10 格、边缘各露半格，所以只扫以玩家为中心的 9×9
BOARD: tuple[int, int, int, int] = (340, 60, 940, 660)
CELL = 60
PLAYER_CENTRE: tuple[int, int] = (639, 359)
SCAN_RADIUS = 4
# 武器攻击范围：以玩家为中心的 5×5
WEAPON_RANGE = 2

FREE, DANGER, OCCUPIED, OFF = "free", "danger", "occupied", "off"


def objective_phase(text: str) -> str | None:
    """从关卡目标文字判断阶段；不是普通关目标（商店、结算、首领关等）时返回 None。"""
    if "坚持" in text:
        return HOLDOUT
    if "所有怪物" in text:
        return CLEAR
    return None


def route_key(route: tuple[int, ...], step: int) -> int:
    """返回巡逻路线第 step 步（从 0 开始）的方向键。"""
    return route[step % len(route)]


def cycle_key(step: int) -> int:
    """进入对局后第 step 步（从 0 开始）的方向键：上 → 左 → 下 → 右 循环。"""
    return MOVE_CYCLE[step % len(MOVE_CYCLE)]


# ---------------------------------------------------------------- 棋盘读取


def _channels(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """取区域的 R/G/B 三个通道（框架截图是 BGR）。"""
    patch = img[y0:y1, x0:x1].astype(np.int32)
    return patch[:, :, 2], patch[:, :, 1], patch[:, :, 0]


def _run_lengths(mask: np.ndarray, arm: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """每个像素向右 / 向下 / 向左 / 向上 arm 个像素内的命中像素数。"""
    m = mask.astype(np.int32)
    h, w = m.shape
    row = np.zeros((h, w + 1), np.int32)
    row[:, 1:] = np.cumsum(m, axis=1)
    col = np.zeros((h + 1, w), np.int32)
    col[1:, :] = np.cumsum(m, axis=0)
    xs = np.arange(w)
    ys = np.arange(h)
    right = row[:, np.minimum(xs + arm, w)] - row[:, xs]
    left = row[:, xs + 1] - row[:, np.maximum(xs + 1 - arm, 0)]
    down = col[np.minimum(ys + arm, h), :] - col[ys, :]
    up = col[ys + 1, :] - col[np.maximum(ys + 1 - arm, 0), :]
    return right, down, left, up


def find_player(img: np.ndarray) -> tuple[int, int] | None:
    """找玩家格：玩家脚下橙色角标框的左上与右下两个 L 形折角（外框约 67×67），返回格心坐标。

    两个折角要同时成立且相距一个格子：怪物精灵、金币特效上也有零星橙色，单看颜色会误判。
    脚下格子被预警染红时角标可能被盖住，这时返回 None，调用方按镜头居中兜底。
    """
    x0, y0, x1, y1 = BOARD
    r, g, b = _channels(img, x0, y0, x1, y1)
    mask = (r > 200) & (g > 110) & (g < 195) & (b < 90)
    if int(mask.sum()) < 20:
        return None
    arm = 10
    right, down, left, up = _run_lengths(mask, arm)
    top_left = mask & (right >= arm - 2) & (down >= arm - 2)
    bottom_right = mask & (left >= arm - 2) & (up >= arm - 2)
    h, w = mask.shape
    for ty, tx in zip(*np.nonzero(top_left), strict=True):
        for span in range(62, 72):
            by, bx = ty + span, tx + span
            if by < h and bx < w and bottom_right[by, bx]:
                return x0 + int(tx) + span // 2, y0 + int(ty) + span // 2
    return None


def _is_warning_tint(r: np.ndarray, g: np.ndarray) -> bool:
    """预警格整体偏红（R−G 约 +20），普通地板 R−G 约 −5。"""
    return float(np.median(r)) - float(np.median(g)) > 12


def classify_cell(img: np.ndarray, x: int, y: int) -> str:
    """判断以 (x, y) 为中心的格子：预警格 / 有单位（怪物、医疗箱）/ 空地板 / 不在可见棋盘内。"""
    half = 22
    bx0, by0, bx1, by1 = BOARD
    if x - half < bx0 or x + half > bx1 or y - half < by0 or y + half > by1:
        return OFF
    r, g, b = _channels(img, x - half, y - half, x + half, y + half)
    if _is_warning_tint(r, g):
        return DANGER
    # 地板是低饱和的灰绿色；怪物精灵有高饱和色块和深色描边（武器范围的虚线只有零星暗点）
    hi = np.maximum(np.maximum(r, g), b)
    chroma = hi - np.minimum(np.minimum(r, g), b)
    colourful = float((chroma > 55).mean())
    dark = float((hi < 70).mean())
    return OCCUPIED if colourful > 0.05 or dark > 0.15 else FREE


def own_cell_danger(img: np.ndarray, x: int, y: int) -> bool:
    """玩家所在格是否在预警里。格心被人物挡住、左上与右下角有橙色角标，只看右上与左下两角。"""
    rs: list[np.ndarray] = []
    gs: list[np.ndarray] = []
    for px, py in ((x + 14, y - 26), (x - 26, y + 14)):
        r, g, _ = _channels(img, px, py, px + 12, py + 12)
        rs.append(r.ravel())
        gs.append(g.ravel())
    return _is_warning_tint(np.concatenate(rs), np.concatenate(gs))


@dataclass(frozen=True)
class Board:
    """以玩家为原点的格子状态（x 向右、y 向下）。"""

    own_danger: bool
    cells: dict[tuple[int, int], str]

    def neighbour(self, key: int) -> str:
        """相邻格子的状态（越界按不可达处理）。"""
        return self.cells.get(STEP[key], OFF)

    def monsters(self) -> list[tuple[int, int]]:
        """所有读到「有单位」的格子（怪物与医疗箱都算）。"""
        return [cell for cell, state in self.cells.items() if state == OCCUPIED]

    def nearest_monster(self) -> tuple[int, int] | None:
        """最近的有单位的格子（按切比雪夫距离，同距离取曼哈顿距离小的）。"""
        monsters = self.monsters()
        if not monsters:
            return None
        return min(monsters, key=lambda c: (max(abs(c[0]), abs(c[1])), abs(c[0]) + abs(c[1])))


def read_board(img: np.ndarray) -> Board:
    """读出玩家周围的格子状态。找不到角标时按镜头居中的位置读（玩家远离地图边缘时就在棋盘中心）。"""
    x, y = find_player(img) or PLAYER_CENTRE
    cells: dict[tuple[int, int], str] = {}
    for j in range(-SCAN_RADIUS, SCAN_RADIUS + 1):
        for i in range(-SCAN_RADIUS, SCAN_RADIUS + 1):
            if (i, j) != (0, 0):
                cells[(i, j)] = classify_cell(img, x + CELL * i, y + CELL * j)
    return Board(own_danger=own_cell_danger(img, x, y), cells=cells)


def toward(target: tuple[int, int]) -> list[int]:
    """朝目标格走的方向键：先走距离更远的那一轴。"""
    dx, dy = target
    horizontal = RIGHT if dx > 0 else LEFT
    vertical = DOWN if dy > 0 else UP
    order = [horizontal, vertical] if abs(dx) >= abs(dy) else [vertical, horizontal]
    return [k for k in order if STEP[k][0] * dx > 0 or STEP[k][1] * dy > 0]


def clear_move(board: Board, search_key: int) -> int | None:
    """清场阶段本步的方向键，None 表示原地等武器输出。

    朝最近的怪物走，到 2 格内就停；看不到怪物就按十字路线走一步（该方向走不通时换其他空邻格，
    不原地卡住）；不主动走进预警格和有单位的格子。脚下有预警时必须离开：优先没有预警的邻格，
    邻格全有预警（如以玩家为中心的十字）也要走，因为邻格的预警通常晚一回合才落下。
    """
    target = board.nearest_monster()
    if target is None:
        preferred = [search_key, *[k for k in DIRECTIONS if k != search_key]]
    elif max(abs(target[0]), abs(target[1])) <= WEAPON_RANGE:
        preferred = []
    else:
        preferred = toward(target)

    if board.own_danger:
        candidates = preferred + [k for k in DIRECTIONS if k not in preferred]
        for state in (FREE, DANGER):
            for key in candidates:
                if board.neighbour(key) == state:
                    return key
        return None

    for key in preferred:
        if board.neighbour(key) == FREE:
            return key
    return None


def forced_move(board: Board, last_key: int | None) -> int | None:
    """换一个空邻格走，免得站着不动。`last_key` 为 None 时（清场阶段重入）不做方向排除。"""
    for key in DIRECTIONS:
        if key != last_key and board.neighbour(key) == FREE:
            return key
    return None


def escape_key(board: Board) -> int | None:
    """脚下正在预警、四个邻格也都在预警里时（以玩家为中心的十字），随便挑一个预警邻格离开。

    预警格在施放时就固定了，邻格的预警通常晚一回合才落下，先挪走比原地挨打划算。
    """
    if not board.own_danger:
        return None
    for key in DIRECTIONS:
        if board.neighbour(key) == DANGER:
            return key
    return None


def fallback_key(board: Board, last_key: int | None) -> int | None:
    """兜底方向：先换空邻格，脚下在预警里时退而求其次走进预警邻格，都不行才站住。"""
    return forced_move(board, last_key) or escape_key(board)


def safe_key(board: Board, preferred: list[int]) -> int | None:
    """按优先级挑一个不会踩进预警格 / 有单位格的方向键；都不安全时返回 None（原地等一回合）。"""
    for key in preferred:
        if board.neighbour(key) == FREE:
            return key
    return None


def hunt_target(board: Board) -> tuple[int, int] | None:
    """清场阶段该不该主动靠近：可见的怪不多、且最近的怪也在武器范围外时，返回最近的怪。

    怪多的时候它们会自己走进武器范围，保持固定节奏躲预警就够；落单的怪不一定主动过来，
    只靠固定节奏永远走不到它跟前，会拖到单关超时。医疗箱也会被读成「有单位」，按怪处理。
    """
    monsters = board.monsters()
    if not monsters or len(monsters) > HUNT_MAX_MONSTERS:
        return None
    target = board.nearest_monster()
    if target is None or max(abs(target[0]), abs(target[1])) <= WEAPON_RANGE:
        return None
    return target


# ---------------------------------------------------------------- 参数


@dataclass(frozen=True)
class MoveParams:
    move_input: str = "click"
    # hybrid：固定节奏 + 怪少时主动靠近（默认）；cycle：始终固定节奏；smart：读棋盘靠近怪物并躲预警
    move_strategy: str = MOVE_STRATEGY_HYBRID
    interval_ms: int = 500
    # 正常一关约 50~70 秒；超时就放弃本局，已通关的关卡照样结算
    level_timeout_s: float = 150.0


def _positive_number(value: Any) -> bool:
    """有限的正数（拒绝 bool、nan、inf 与字符串）。"""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def parse_move_params(raw: Any) -> MoveParams:
    """解析 custom_action_param；非法值回落默认并记 warning。

    interval_ms 必须是正整数般的值：0.5 这种小于 1 的会被 int() 截成 0（循环不在等待），
    inf 则直接抛异常，都在这里挡掉。
    """
    default = MoveParams()
    try:
        params = raw if isinstance(raw, dict) else parse_params(raw)
    except ValueError as e:
        logger.warning(f"[8bit] 解析移动参数失败，使用默认值: {e}")
        return default

    move_input = params.get("move_input", default.move_input)
    if move_input not in ("click", "key"):
        logger.warning(f"[8bit] 未知移动输入方式: {move_input}，使用点击输入")
        move_input = default.move_input

    move_strategy = params.get("move_strategy", default.move_strategy)
    if move_strategy not in (MOVE_STRATEGY_HYBRID, MOVE_STRATEGY_CYCLE, MOVE_STRATEGY_SMART):
        logger.warning(f"[8bit] 未知移动策略: {move_strategy}，使用固定节奏 + 怪少时靠近（hybrid）")
        move_strategy = default.move_strategy

    interval = params.get("interval_ms", default.interval_ms)
    if not _positive_number(interval) or int(interval) != interval:
        logger.warning(f"[8bit] interval_ms 非法: {interval}，使用默认值")
        interval = default.interval_ms

    timeout = params.get("level_timeout_s", default.level_timeout_s)
    if not _positive_number(timeout):
        logger.warning(f"[8bit] level_timeout_s 非法: {timeout}，使用默认值")
        timeout = default.level_timeout_s

    return MoveParams(
        move_input=str(move_input),
        move_strategy=str(move_strategy),
        interval_ms=int(interval),
        level_timeout_s=float(timeout),
    )


def parse_count(text: str) -> int | None:
    """从 OCR 文本里取出数字（如结算页的「30」），没有数字时返回 None。"""
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


ROUND_PATTERN = re.compile(r"坚持\s*(\d+)\s*回合")


def round_from_objective(text: str) -> int | None:
    """从「坚持N回合」取出剩余回合数；不是坚持阶段时返回 None。"""
    match = ROUND_PATTERN.search(text)
    return int(match.group(1)) if match else None


def next_level_start(
    prev_start: float | None,
    prev_phase: str | None,
    prev_round: int | None,
    phase: str | None,
    round_no: int | None,
    now: float,
) -> float:
    """本次调用的关卡计时起点：同一关被 OCR 抖动判回时沿用旧起点，真正换关才从当前时刻重算。

    判据是关卡目标本身，不靠时间窗口猜：一关里回合数只会从大到小，「击败所有怪物」接在回合数归零之后。
    所以「回合数比上次大」或「上次已经在清场阶段却又出现坚持」都说明是新的一关；
    读不到目标（phase 为 None，即已经离开关卡界面）时一律沿用旧起点。
    """
    if prev_start is None:
        return now
    if phase == HOLDOUT and (
        prev_phase == CLEAR or (round_no is not None and prev_round is not None and round_no > prev_round)
    ):
        return now
    return prev_start


def efficiency_per_hour(total: int, first_count: int, elapsed_s: float) -> float | None:
    """每小时卡带数：分子扣掉首次结算的奖励，与计时的起点对齐（首次结算发生在计时开始那一刻）。"""
    if elapsed_s <= 0:
        return None
    return (total - first_count) / elapsed_s * 3600


# ---------------------------------------------------------------- 普通关


@AgentServer.custom_action("EightBitCombatMove")
class EightBitCombatMove(CustomAction):
    """
    8-bit 街机秀普通关：一次调用打完整关（移动规则见模块说明）。

    每隔 interval_ms 走一步，中途不停：交回 pipeline 重新识别会空过回合，站着不动的回合正是掉血的主因。
    每步都读左上角关卡目标：读不到就不按键，连续两次读不到就返回成功，由 next 里的节点接手
    （商店、结算页、首领关、关卡过场都表现为读不到目标）。
    单关超过 level_timeout_s 时只有「这一帧仍读得到关卡目标」才算真卡住并返回失败走 on_error；
    目标已经消失的帧按本关结束处理——过场帧里商店 / 结算页还没渲染出来，不能当作卡住。

    参数：
      move_input: "click"（默认，点击屏幕十字键）或 "key"（发送 Android 方向键）
      move_strategy: "hybrid"（默认，固定节奏 + 怪少时主动靠近）/ "cycle"（始终固定节奏）/
        "smart"（读棋盘靠近怪物并躲预警）
      interval_ms: 每步间隔毫秒，默认 500
      level_timeout_s: 单关超时秒数，默认 150
    """

    MISSES_TO_END = 2
    # 连续这么多步都没动（含把装饰物误判成怪物）就强制换方向
    MAX_IDLE_STEPS = 6

    # 跨调用保存的关卡状态：调用结束不清 `_level_started`，由下一帧的关卡目标决定是同一关还是新一关
    _level_started: float | None = None
    _last_phase: str | None = None
    _last_round: int | None = None

    @classmethod
    def _forget_level(cls) -> None:
        """忘掉当前关卡：确认离开关卡界面（换关或放弃本局）后调用。"""
        cls._level_started = None
        cls._last_phase = None
        cls._last_round = None

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """打完整关：读关卡目标决定阶段与计时，逐回合移动，离开关卡时返回成功；单关超时返回失败。"""
        params = parse_move_params(argv.custom_action_param)
        cls = EightBitCombatMove
        holdout_step = search_step = idle_steps = cycle_step = blind_steps = 0
        steps = misses = 0
        last_key: int | None = None
        started: float | None = None

        while not context.tasker.stopping:
            tick = time.time()
            img = context.tasker.controller.post_screencap().wait().get()
            phase, round_no = self._read_level(context, img)
            if phase is not None:
                # 第一帧决定本关计时起点：同一关沿用上次的起点，超时才不会被 OCR 抖动重置
                started = next_level_start(cls._level_started, cls._last_phase, cls._last_round, phase, round_no, tick)
                cls._level_started, cls._last_phase, cls._last_round = started, phase, round_no

            # 只有「本帧仍读得到关卡目标」才算真的卡在这一关：读不到目标时可能是过场动画、
            # 商店，或本关刚结束，交给下面的连续未命中判定处理，不要把任务直接判失败。
            if phase is not None and started is not None and tick - started > params.level_timeout_s:
                logger.warning(f"[8bit] 单关超过 {params.level_timeout_s:.0f} 秒未结束，退出本局")
                cls._forget_level()
                return CustomAction.RunResult(success=False)

            if phase is None:
                misses += 1
                if misses >= self.MISSES_TO_END:
                    break
                time.sleep(params.interval_ms / 1000)
                continue
            misses = 0

            key: int | None
            if params.move_strategy == MOVE_STRATEGY_SMART:
                if phase == HOLDOUT:
                    key = route_key(HOLDOUT_ROUTE, holdout_step)
                    holdout_step += 1
                else:
                    search_key = route_key(SEARCH_ROUTE, search_step)
                    board = read_board(img)
                    key = clear_move(board, search_key)
                    if key is None:
                        idle_steps += 1
                        if idle_steps >= self.MAX_IDLE_STEPS:
                            key = forced_move(board, last_key) or search_key
                            idle_steps = 0
                    else:
                        idle_steps = 0
                    if key is not None:
                        search_step += 1
            elif params.move_strategy == MOVE_STRATEGY_HYBRID and phase == CLEAR:
                board = read_board(img)
                target = hunt_target(board)
                if target is not None:
                    # 落单的怪不主动过来：朝它走，躲开预警格和有单位的格子
                    blind_steps = search_step = 0
                    key = safe_key(board, toward(target))
                elif board.nearest_monster() is None:
                    # 一只都看不到：先按固定节奏走几步，还是没有就走十字路线扩大视野
                    blind_steps += 1
                    if blind_steps > SEARCH_AFTER_STEPS:
                        key = safe_key(board, [route_key(SEARCH_ROUTE, search_step)])
                        search_step += 1
                    else:
                        key = cycle_key(cycle_step)
                        cycle_step += 1
                else:
                    blind_steps = search_step = 0
                    key = cycle_key(cycle_step)
                    cycle_step += 1
                if key is None:
                    # 被预警格 / 怪物堵住时换方向，别站着不动；脚下也全在预警里时按 escape_key 挪一格。
                    # last_key 为 None（清场阶段重入）时同样要兜底，否则朝怪方向被预警挡住就白站一回合
                    key = fallback_key(board, last_key)
            else:
                key = cycle_key(cycle_step)
                cycle_step += 1

            if key is not None:
                self._press(context, key, params.move_input)
                last_key = key
                steps += 1
            time.sleep(max(0.0, params.interval_ms / 1000 - (time.time() - tick)))

        elapsed = time.time() - started if started is not None else 0.0
        logger.info(f"[8bit] 关卡结束：用时 {elapsed:.0f} 秒，移动 {steps} 步")
        # 这里不清 `_level_started`：下一帧若还是同一关（OCR 抖动重入）要继续计时，
        # 若已是新一关，next_level_start 会按回合数判断后重置。
        return CustomAction.RunResult(success=True)

    # 每次都重新取 context.tasker.controller，不要持有它：agent 侧每取一次就会替换掉上一个远程控制器句柄，
    # 旧句柄再用就会访问已释放的内存（实测 access violation）。
    def _read_level(self, context: Context, img: np.ndarray) -> tuple[str | None, int | None]:
        """读左上角关卡目标，返回 (阶段, 剩余回合数)。不在普通关时两者都是 None。"""
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=OBJECTIVE_ROI, expected=NORMAL_OBJECTIVES),
            img,
        )
        if not is_hit(detail):
            return None, None
        text = ocr_text(detail)
        return objective_phase(text), round_from_objective(text)

    @staticmethod
    def _press(context: Context, key: int, move_input: str) -> None:
        """按一次方向键（点屏幕十字键或发 Android 方向键）。"""
        if move_input == "key":
            context.tasker.controller.post_click_key(key).wait()
        else:
            context.tasker.controller.post_click(*MOVE_CLICK_POSITIONS[key]).wait()


# ---------------------------------------------------------------- 商店

SHOP_TITLE_ROI: tuple[int, int, int, int] = (500, 35, 280, 55)
# 两种商店标题：普通商店「地下流通处」；持有洛佩拉的秘宝「力量投影」时换成只卖卡包的「秘密交易处」
SHOP_TITLES: list[str] = ["地下流通处", "秘密交易处"]
# 首领关前的商店副标题下多一行「下回合即将迎战强敌」
BOSS_NEXT_ROI: tuple[int, int, int, int] = (500, 110, 280, 45)
# 四个商品槽的名称行；买走的槽位会空出来，其余商品不移位
SLOT_TITLE_ROI: tuple[int, int, int, int] = (20, 278, 1240, 50)
SLOT_LEFT = 15
SLOT_WIDTH = 312
# 点商品下半部（描述区）即选中它，避开右上角的锁定按钮
SLOT_TAP: tuple[tuple[int, int], ...] = ((168, 450), (481, 450), (795, 450), (1105, 450))
BUY_BUTTON: tuple[int, int] = (849, 662)
# 「购买」按钮：买得起是橙色（实测 RGB 约 199,118,33），买不起变灰
BUY_BUTTON_ROI: tuple[int, int, int, int] = (800, 640, 100, 45)

# 只买纯属性加成的秘宝：不生成召唤物 / 炸弹 / 地板（会干扰读棋盘），不改商店规则，不开卡包
WANTED_RELICS: tuple[str, ...] = (
    # 伤害
    "仪式短剑",
    "王牌右拳套",
    "勇者之剑",
    "荆棘与蛇蜕",
    "缤纷万华镜",
    # 攻击范围
    "飞溅骨矢",
    "干草叉",
    "双蛇箭矢",
    # 生命
    "槲寄生种子",
    "舞会假面",
    "生命之心",
    "女仆头巾",
    # 暴击
    "遗落的星",
    "笔中诗",
    "丰收石桶",
    "接骨木之眼",
    "接电水雷",
    "扎人的毛线帽",
    # 闪避与减伤
    "勤奋舞鞋",
    "桌上的演绎",
    "未赠铠",
    "银绸帕",
)


def wanted_relic(text: str) -> str | None:
    """OCR 出的商品名是否在白名单里，返回对应的秘宝名。OCR 可能漏字，允许 3 字以上的片段匹配。"""
    text = text.strip()
    if not text:
        return None
    for name in WANTED_RELICS:
        if text == name or (len(text) >= 3 and text in name):
            return name
    return None


def slot_of(x_centre: float) -> int:
    """商品名中心 x 坐标所在的槽位（0~3）。"""
    return min(3, max(0, int((x_centre - SLOT_LEFT) // SLOT_WIDTH)))


def buy_button_ready(img: np.ndarray) -> bool:
    """「购买」按钮是否为橙色（选中的商品买得起）。"""
    x, y, w, h = BUY_BUTTON_ROI
    r, g, b = _channels(img, x, y, x + w, y + h)
    orange = (r > 170) & (g > 80) & (g < 150) & (b < 70)
    return float(orange.mean()) > 0.4


@AgentServer.custom_action("EightBitShopBuy")
class EightBitShopBuy(CustomAction):
    """
    8-bit 街机秀商店：从左到右买下白名单里买得起的秘宝，然后返回，由 pipeline 点「放弃」离开。

    两种商店标题（地下流通处 / 秘密交易处）都照常购买：两者都是买秘宝和卡包的店。
    每次购买：点商品选中它 → 「购买」按钮是橙色才点。点完再读一遍，商品还在就算没买成、之后跳过它。
    首领关前的商店（「下回合即将迎战强敌」）不买：本任务到首领关就结算退出，买了也用不上。
    """

    MAX_ATTEMPTS = 6

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """按白名单从左到右购买买得起的秘宝；离开商店与否由 pipeline 的「放弃」节点负责。"""
        skipped: set[int] = set()
        last: tuple[int, str] | None = None
        bought: list[str] = []

        for _ in range(self.MAX_ATTEMPTS):
            if context.tasker.stopping:
                break
            img = context.tasker.controller.post_screencap().wait().get()
            if not self._ocr_hit(context, img, SHOP_TITLE_ROI, SHOP_TITLES):
                break
            if self._ocr_hit(context, img, BOSS_NEXT_ROI, ["强敌"]):
                logger.debug("[8bit] 首领关前的商店，不购买")
                break

            slots = self._wanted_slots(context, img)
            if last is not None:
                if slots.get(last[0]) == last[1]:
                    skipped.add(last[0])
                else:
                    bought.append(last[1])
                last = None
            candidates = sorted(slot for slot in slots if slot not in skipped)
            if not candidates:
                break

            slot = candidates[0]
            context.tasker.controller.post_click(*SLOT_TAP[slot]).wait()
            time.sleep(0.5)
            img = context.tasker.controller.post_screencap().wait().get()
            if not buy_button_ready(img):
                skipped.add(slot)
                continue
            context.tasker.controller.post_click(*BUY_BUTTON).wait()
            last = (slot, slots[slot])
            time.sleep(1.5)

        if bought:
            logger.info(f"[8bit] 商店购买：{'、'.join(bought)}")
        return CustomAction.RunResult(success=True)

    @staticmethod
    def _ocr_hit(context: Context, img: np.ndarray, roi: tuple[int, int, int, int], expected: list[str]) -> bool:
        """指定 ROI 里是否出现任一 expected 文本。"""
        detail = context.run_recognition_direct(JRecognitionType.OCR, JOCR(roi=roi, expected=expected), img)
        return is_hit(detail)

    @staticmethod
    def _wanted_slots(context: Context, img: np.ndarray) -> dict[int, str]:
        """读四个槽位的商品名，返回 {槽位: 白名单秘宝名}。"""
        detail = context.run_recognition_direct(JRecognitionType.OCR, JOCR(roi=SLOT_TITLE_ROI), img)
        slots: dict[int, str] = {}
        for result in ocr_results(detail):
            name = wanted_relic(result.text)
            if name is None:
                continue
            x, _, w, _ = result.box
            slots.setdefault(slot_of(x + w / 2), name)
        return slots


# ---------------------------------------------------------------- 结算


@AgentServer.custom_action("EightBitScoreRecord")
class EightBitScoreRecord(CustomAction):
    """
    8-bit 街机秀结算页：记录本局获得的像素卡带并统计效率，然后点击空白处关闭结算页。

    结算页右侧依次展示像素宝石与像素卡带两个奖励格（未通关任何关卡时不展示），
    卡带数量在第二格右下角。数量识别失败时不记 0，而是明确记一条警告并说明累计不完整。
    """

    _cassette_roi: tuple[int, int, int, int] = (1018, 488, 70, 40)
    _close_point: tuple[int, int] = (640, 690)
    _first_time: float = 0
    _first_count: int = 0
    _total: int = 0
    _runs: int = 0

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """读本局卡带数并记日志，然后点空白处关闭结算页。"""
        img = context.tasker.controller.cached_image
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=self._cassette_roi, expected=["\\d+"], only_rec=True),
            img,
        )
        count = parse_count(ocr_text(detail)) if is_hit(detail) else None

        cls = EightBitScoreRecord
        cls._runs += 1
        if cls._runs == 1:
            cls._first_time = time.time()

        if count is None:
            logger.warning(
                "[8bit] 结算页没读到像素卡带数量（可能是本局没有通任何关卡，也可能是识别失败），本局不计入累计"
            )
        else:
            cls._total += count
            if cls._runs == 1:
                cls._first_count = count
                logger.info(f"[8bit] 本局获得像素卡带：{count}")
            else:
                rate = efficiency_per_hour(cls._total, cls._first_count, time.time() - cls._first_time)
                if rate is None:
                    logger.info(f"[8bit] 本局获得像素卡带：{count}，累计：{cls._total}")
                else:
                    logger.info(f"[8bit] 本局获得像素卡带：{count}，累计：{cls._total}，约 {rate:.0f} 个/小时")

        context.tasker.controller.post_click(*self._close_point).wait()
        return CustomAction.RunResult(success=True)
