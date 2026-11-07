"""
8-bit 街机秀（4.1「幸存者游戏」）。

玩法是回合制棋盘：玩家每次移动一格就结束一回合，不动则约 1 秒后超时进入下一回合；武器每 3 回合
自动攻击以玩家为中心的 5×5。怪物攻击前会先在目标格上画出红色预警，目标格在施放时就固定了，
不会跟着玩家走。

普通关的移动规则：
- 「坚持N回合」阶段：左右来回巡逻，不读棋盘。一直在动就躲得开预警，追过来的怪物会进入武器范围。
- 「击败所有怪物」阶段：每步读棋盘，朝最近的怪物走，走到 2 格内（武器范围）就停下等武器输出；
  看不到怪物时走十字找怪；脚下出现预警就先躲到没有预警的邻格。
难度Ⅰ第一阶段实测：左右巡逻 3 个普通关全部满血通关；站着不动则 3 次都在第 1 关被打死。

关卡之间的商店「地下流通处」：从左到右买下买得起的纯属性缪斯秘宝（白名单），首领关前的商店不买。
坐标与颜色阈值都是 1280×720 实测值；框架截图是 BGR。
"""

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
    脚下格子被预警染红时角标可能被盖住，这时返回 None。
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
        return self.cells.get(STEP[key], OFF)

    def nearest_monster(self) -> tuple[int, int] | None:
        monsters = [cell for cell, state in self.cells.items() if state == OCCUPIED]
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

    朝最近的怪物走，到 2 格内就停；看不到怪物就按十字路线走一步；不主动走进预警格和有单位的格子。
    脚下有预警时必须离开：优先没有预警的邻格，邻格全有预警（如以玩家为中心的十字）也要走，
    因为邻格的预警通常晚一回合才落下。
    """
    target = board.nearest_monster()
    if target is None:
        preferred = [search_key]
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


# ---------------------------------------------------------------- 参数


@dataclass(frozen=True)
class MoveParams:
    move_input: str = "click"
    interval_ms: int = 500
    # 正常一关约 50~70 秒；超时就放弃本局，已通关的关卡照样结算
    level_timeout_s: float = 150.0


def _positive_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def parse_move_params(raw: Any) -> MoveParams:
    """解析 custom_action_param；非法值回落默认并记 warning。"""
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

    interval = params.get("interval_ms", default.interval_ms)
    if not _positive_number(interval):
        logger.warning(f"[8bit] interval_ms 非法: {interval}，使用默认值")
        interval = default.interval_ms

    timeout = params.get("level_timeout_s", default.level_timeout_s)
    if not _positive_number(timeout):
        logger.warning(f"[8bit] level_timeout_s 非法: {timeout}，使用默认值")
        timeout = default.level_timeout_s

    return MoveParams(move_input=str(move_input), interval_ms=int(interval), level_timeout_s=float(timeout))


def parse_count(text: str) -> int | None:
    """从 OCR 文本里取出数字（如结算页的「30」），没有数字时返回 None。"""
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


# ---------------------------------------------------------------- 普通关


@AgentServer.custom_action("EightBitCombatMove")
class EightBitCombatMove(CustomAction):
    """
    8-bit 街机秀普通关：一次调用打完整关（移动规则见模块说明）。

    每隔 interval_ms 走一步，中途不停：交回 pipeline 重新识别会空过回合，站着不动的回合正是掉血的主因。
    每步都读左上角关卡目标：读不到就不按键，连续两次读不到（进入商店、结算页或首领关）就返回成功，
    由 next 里的节点接手；单关超过 level_timeout_s 还没结束就返回失败，走 on_error 退出本局。

    参数：
      move_input: "click"（默认，点击屏幕十字键）或 "key"（发送 Android 方向键）
      interval_ms: 每步间隔毫秒，默认 500
      level_timeout_s: 单关超时秒数，默认 150
    """

    MISSES_TO_END = 2

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        params = parse_move_params(argv.custom_action_param)
        started = time.time()
        phase = HOLDOUT
        steps = holdout_step = search_step = misses = 0

        while not context.tasker.stopping:
            tick = time.time()
            if tick - started > params.level_timeout_s:
                logger.warning(f"[8bit] 单关超过 {params.level_timeout_s:.0f} 秒未结束，退出本局")
                return CustomAction.RunResult(success=False)

            img = context.tasker.controller.post_screencap().wait().get()
            current = self._read_phase(context, img)
            if current is None:
                misses += 1
                if misses >= self.MISSES_TO_END:
                    break
                time.sleep(params.interval_ms / 1000)
                continue
            misses = 0
            phase = current

            if phase == HOLDOUT:
                key: int | None = route_key(HOLDOUT_ROUTE, holdout_step)
                holdout_step += 1
            else:
                search_key = route_key(SEARCH_ROUTE, search_step)
                key = clear_move(read_board(img), search_key)
                if key == search_key:
                    search_step += 1

            if key is not None:
                self._press(context, key, params.move_input)
                steps += 1
            time.sleep(max(0.0, params.interval_ms / 1000 - (time.time() - tick)))

        logger.info(f"[8bit] 关卡结束：用时 {time.time() - started:.0f} 秒，移动 {steps} 步")
        return CustomAction.RunResult(success=True)

    # 每次都重新取 context.tasker.controller，不要持有它：agent 侧每取一次就会替换掉上一个远程控制器句柄，
    # 旧句柄再用就会访问已释放的内存（实测 access violation）。
    @staticmethod
    def _read_phase(context: Context, img: np.ndarray) -> str | None:
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=OBJECTIVE_ROI, expected=NORMAL_OBJECTIVES),
            img,
        )
        return objective_phase(ocr_text(detail)) if is_hit(detail) else None

    @staticmethod
    def _press(context: Context, key: int, move_input: str) -> None:
        if move_input == "key":
            context.tasker.controller.post_click_key(key).wait()
        else:
            context.tasker.controller.post_click(*MOVE_CLICK_POSITIONS[key]).wait()


# ---------------------------------------------------------------- 商店

SHOP_TITLE_ROI: tuple[int, int, int, int] = (500, 35, 280, 55)
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
    8-bit 街机秀商店「地下流通处」：从左到右买下白名单里买得起的秘宝，然后返回，由 pipeline 点「放弃」离开。

    每次购买：点商品选中它 → 「购买」按钮是橙色才点。点完再读一遍，商品还在就算没买成、之后跳过它。
    首领关前的商店（「下回合即将迎战强敌」）不买：本任务到首领关就结算退出，买了也用不上。
    """

    MAX_ATTEMPTS = 6

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        skipped: set[int] = set()
        last: tuple[int, str] | None = None
        bought: list[str] = []

        for _ in range(self.MAX_ATTEMPTS):
            if context.tasker.stopping:
                break
            img = context.tasker.controller.post_screencap().wait().get()
            if not self._ocr_hit(context, img, SHOP_TITLE_ROI, ["地下流通处"]):
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
    卡带数量在第二格右下角。
    """

    _cassette_roi: tuple[int, int, int, int] = (1018, 488, 70, 40)
    _close_point: tuple[int, int] = (640, 690)
    _first_time: float = 0
    _total: int = 0
    _runs: int = 0

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
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
            logger.info("[8bit] 本局未获得像素卡带")
        else:
            cls._total += count
            elapsed = time.time() - cls._first_time
            if cls._runs > 1 and elapsed > 0:
                rate = cls._total / elapsed * 3600
                logger.info(f"[8bit] 本局获得像素卡带：{count}，累计：{cls._total}，约 {rate:.0f} 个/小时")
            else:
                logger.info(f"[8bit] 本局获得像素卡带：{count}")

        context.tasker.controller.post_click(*self._close_point).wait()
        return CustomAction.RunResult(success=True)
