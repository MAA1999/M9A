"""魔精诈唬牌（共读之忆 · WeShared）：牌局决策与对局驱动。

决策层全是纯函数（`truth_probability` / `confirmer_probability` / `claimer_opponent_belief` /
`claim_plan` / `confirm_choice` / `wants_potion` 与几个解析函数），阈值都提到模块级常量，
便于单测和调参；只有 `WeSharedTurnLoop._drive_match` 会真的读帧、点屏幕。
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import comb
from typing import Any, Literal

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.define import BoxAndScoreResult
from maa.pipeline import JWaitFreezes
from utils.logger import logger
from utils.maa_types import is_hit, ocr_text, results_as
from utils.params import parse_params

# ---------------------------------------------------------------- 花色与概率模型

# 花色下标 = 右上「剩余」四个计数框的固定顺序（从左到右：棕 / 蓝 / 绿 / 紫）
BROWN, BLUE, GREEN, WILD = 0, 1, 2, 3
SUIT_COUNT = 4
SUIT_NAMES = ("棕·缝衣针", "蓝·毛斗篷", "绿·莴苣叶", "紫·万能")
# 「万能」恒为合法牌，不会成为声明目标，所以目标牌图标只需三种真花色
TARGET_SUITS = (BROWN, BLUE, GREEN)

# 确认者：P(真) 高于它就信任，否则质疑
CONFIRM_TRUST_THRESHOLD = 0.5
# 药水按血量分档（hp_scaled）：2 血时 P 落在这个带宽里就烧一瓶；1 血必用、3 血留着。
# 整局口径实测（8000 局/格）：hp_scaled 均值 76.2%，远高于旧的固定带宽 0.08（68.2%）。
HP_SCALED_BAND = 0.25
# 声明者：下家视角的 P 低于它就说明下家会质疑 —— 此时说真话才能让下家猜错。
# 可调：实测下家确认阈值落在 0.125~0.183，本值取区间中段；蒙特卡洛显示 θ≈0.155 附近
# 有约 3pp 下凹（naive 代理与下家实际口径错位所致），换版本后需按实测重新标定。
CLAIM_THRESHOLD = 0.15

MIN_CLAIM = 2
MAX_CLAIM = 5
# 我方三颗心：亮心数就是血量
MY_HP_MAX = 3

# ---------------------------------------------------------------- 720p 坐标标定

COUNT_ROIS = ((945, 55, 48, 42), (993, 55, 48, 42), (1041, 55, 48, 42), (1089, 55, 46, 42))
HAND_SLOT_CENTERS = (338, 456, 574, 691, 809, 927)
HAND_SLOT_Y = 452
# 手牌模板按「槽心 x - 28」裁切（见 resource/base/image/WeShared/Card*.png）
HAND_TEMPLATE_DX = 28
HAND_SLOT_TOLERANCE = 40
# pipeline 节点阈值放到 0.6 让四个模板的分数都拿得到，这里再按分数做一次下限与择优：
# 跨帧实测棕牌（缝衣针）只有 0.758~0.77，其它花色在同一个槽里恒为 0.000。
HAND_MIN_SCORE = 0.65
# 目标牌图标：胜出者实测 0.868~0.961，落败者 0.000~0.721
TARGET_MIN_SCORE = 0.8

# 结算页「本局积分」的基础搜索区。数字 3~4 位、约 21px/位，居中排在 y 482..506；
# 基础框要留出 4 位数的余量，所以左边界比 3 位数的首笔（x=785）还靠左。真正喂给识别的框
# 由 digit_roi() 按墨迹收紧 —— 直接拿这个框去认会把左右两侧的金色藤蔓花纹一起送进去。
GAME_SCORE_ROI = (745, 468, 130, 52)
# 墨迹阈值：数字笔画亮度 >170，藤蔓花纹在 170 以下（实测），据此把数字从背景里择出来
SCORE_INK_THRESHOLD = 170
SCORE_INK_PAD = 4
# 一位约 21px：4 位数上限 100 刚好装得下，而横幅文字会横跨整个基础框（实测 133px）
SCORE_MAX_WIDTH = 100
SCORE_MIN_HEIGHT = 16
SCORE_MAX_HEIGHT = 40
# 结算面板是渐入的：横幅先出现、数字后到（实测相差约 1.5s），重试窗口要盖住这段动画
SCORE_READ_ATTEMPTS = 8
SCORE_READ_DELAY = 0.5

POINT_TRUST = (465, 521)
POINT_DOUBT = (815, 521)
POINT_POTION = (1160, 640)
POINT_START_GAME = (1090, 585)
POINT_CONFIRM_PLAY = (1090, 585)

# ---------------------------------------------------------------- pipeline 节点名

ENTRY_NODE = "WeShared"
TURN_LOOP_NODE = "WeSharedTurnLoop"
SCORE_CHECK_NODE = "WeSharedScoreCheck"
COUNT_NODE = "WeSharedRemainCount"
SCORE_NODE = "WeSharedScore"
CLAIM_BAR_NODE = "WeSharedClaimBar"
POTION_LEFT_NODE = "WeSharedPotionLeft"
CONFIRM_PHASE_NODE = "WeSharedConfirmPhase"
PICK_PROMPT_NODE = "WeSharedPickPrompt"
ROUND_BANNER_NODE = "WeSharedRoundBanner"
GAME_OVER_NODE = "WeSharedGameOver"
GAME_SCORE_NODE = "WeSharedGameScore"
START_GAME_NODE = "WeSharedStartGame"
CONFIRM_PLAY_NODE = "WeSharedConfirmPlay"
TRUST_NODE = "WeSharedTrust"
DOUBT_NODE = "WeSharedDoubt"
POTION_NODE = "WeSharedPotion"
MY_HP_NODE = "WeSharedMyHp"
MY_HP_EMPTY_NODE = "WeSharedMyHpEmpty"
REPORT_SUMMARY_NODE = "WeSharedReportSummary"
# 顺序必须与 BROWN / BLUE / GREEN 对齐
TARGET_NODES = ("WeSharedTargetNeedle", "WeSharedTargetHood", "WeSharedTargetLettuce")
# 顺序必须与 BROWN / BLUE / GREEN / WILD 对齐
HAND_NODES = ("WeSharedHandNeedle", "WeSharedHandHood", "WeSharedHandLettuce", "WeSharedHandWild")

# ---------------------------------------------------------------- 运行时节奏

DEFAULT_SCORE_CAP = 9000
DEFAULT_MAX_GAMES = 50
# 刷取模式：once = 只打一局就停；full = 打到诈唬分达标（默认，与旧行为一致）
MODE_ONCE = "once"
MODE_FULL = "full"
CLAIM_MODES = (MODE_ONCE, MODE_FULL)
DEFAULT_MODE = MODE_FULL
POLL_INTERVAL = 0.4
SETTLE_DELAY = 1.2
CLICK_INTERVAL = 0.35
MATCH_TIMEOUT = 600.0
# 确认阶段的读数重试：动画未稳时 OCR/模板会读空，换新帧重试几次比一次判死稳
READ_ATTEMPTS = 3
READ_RETRY_DELAY = 0.35
# 等确认阶段画面静止的区域：覆盖右上「剩余」计数 + 出牌内容 + 声称文案条
CONFIRM_STABLE_ROI = (390, 40, 770, 420)
FREEZE_TIME = 300


@dataclass(frozen=True)
class Counts:
    """四个花色各有多少张，顺序与右上「剩余」四框一致（棕 / 蓝 / 绿 / 万能）。"""

    brown: int = 0
    blue: int = 0
    green: int = 0
    wild: int = 0

    def of(self, suit: int) -> int:
        return (self.brown, self.blue, self.green, self.wild)[suit]

    def total(self) -> int:
        return self.brown + self.blue + self.green + self.wild

    def legal(self, target: int) -> int:
        """目标花色为 target 时，合法牌（目标花色 + 万能）的张数。"""
        return self.of(target) + self.wild

    def minus(self, other: "Counts") -> "Counts":
        """逐花色相减，负值截到 0：识别抖动时不要把 N' / L' 算成负数。"""
        return Counts(
            _floor0(self.brown - other.brown),
            _floor0(self.blue - other.blue),
            _floor0(self.green - other.green),
            _floor0(self.wild - other.wild),
        )


def _floor0(value: int) -> int:
    return value if value > 0 else 0


def counts_from_suits(suits: Sequence[int | None]) -> Counts:
    """按花色下标统计张数；None 是没认出来的槽位，不计入。"""
    values = [0, 0, 0, 0]
    for suit in suits:
        if suit is not None and 0 <= suit < SUIT_COUNT:
            values[suit] += 1
    return Counts(values[0], values[1], values[2], values[3])


def truth_probability(
    counts: Counts,
    target: int,
    k: int,
    *,
    hand: Counts | None = None,
    revealed: int = 0,
) -> float:
    """P(声明的 k 张全是合法牌) = C(L'-j, k-j) / C(N'-j, k-j)。

    Args:
        counts: **用药水之前**读到的「剩余」四项。
        target: 目标花色下标。
        k: 声明张数。
        hand: 我方手牌计数；None 表示本圈还没见过自己的手牌，降级为不扣手牌的 naive 口径。
        revealed: 已用药水翻开、且全部合法的张数 j。
    """
    pool = counts if hand is None else counts.minus(hand)
    total = pool.total() - revealed
    legal = pool.legal(target) - revealed
    remaining = k - revealed
    if remaining <= 0:
        return 1.0
    if legal < remaining or total < remaining:
        return 0.0
    return comb(legal, remaining) / comb(total, remaining)


def confirmer_probability(
    counts: Counts,
    target: int,
    k: int,
    hand: Counts | None,
    revealed: int = 0,
) -> float:
    """确认者视角：右上「剩余」含我自己的手牌，我已知它们，必须扣掉才算不确定性。"""
    return truth_probability(counts, target, k, hand=hand, revealed=revealed)


def claimer_opponent_belief(counts: Counts, target: int, k: int) -> float:
    """声明者视角的下家决策代理。

    下家只扣它自己的手牌（我不知道它拿了什么），所以这里用不扣手牌的 naive 口径；
    CLAIM_THRESHOLD 也按这个口径标定（实测下家阈值落在 naive P 的 12.5%~18.3%）。
    """
    return truth_probability(counts, target, k)


def confirm_choice(probability: float) -> Literal["trust", "doubt"]:
    """确认者：P 高于阈值就信任，否则质疑（质疑猜对 → 声明者扣血）。"""
    return "trust" if probability > CONFIRM_TRUST_THRESHOLD else "doubt"


@dataclass(frozen=True)
class RevealState:
    """一次确认阶段里「透视药水已经翻开了什么」的累计状态。"""

    revealed: int = 0
    illegal: bool = False


def apply_reveal(state: RevealState, legal_before: int, legal_now: int) -> RevealState:
    """把一次药水翻牌并进状态。

    合法牌（目标 + 万能）数没有减少 → 翻开的这张不在合法集合里，声明必假。
    """
    return RevealState(state.revealed + 1, state.illegal or legal_now >= legal_before)


def reveal_advanced(total_before: int, fresh: Counts | None) -> bool:
    """药水翻牌是否真的生效：剩余总数必须减少。

    点击没生效、或计数还没刷新时，读到的还是翻牌前的值。那种情况不能当成「翻出非法牌」，
    否则 P(真) 会被置 0、必然质疑，药水也白扣一瓶 —— 直接当作没翻开收手即可。
    """
    return fresh is not None and fresh.total() < total_before


def confirm_probability(
    counts: Counts,
    target: int,
    k: int,
    hand: Counts | None,
    state: RevealState,
) -> float:
    """确认者此刻的 P(真)：翻出过非法牌就是 0，否则按贝叶斯条件式重算。"""
    if state.illegal:
        return 0.0
    return confirmer_probability(counts, target, k, hand, state.revealed)


def reveal_outcomes(
    counts: Counts,
    target: int,
    k: int,
    hand: Counts | None,
    state: RevealState,
) -> tuple[float, float]:
    """再翻一张的两种结局：(翻出合法牌后的 P, 翻出非法牌后的 P)。

    非法牌那一支恒为 0（翻出来就是必假），所以这里只算合法那一支，非法支固定给 0.0。
    """
    if k - state.revealed <= 0:
        return (confirm_probability(counts, target, k, hand, state), 0.0)
    legal_case = confirmer_probability(counts, target, k, hand, state.revealed + 1)
    return (legal_case, 0.0)


def potion_is_decisive(counts: Counts, target: int, k: int, hand: Counts | None, state: RevealState) -> bool:
    """翻一张到底会不会改变「信任 / 质疑」的结论。

    只剩最后一张没翻时翻了就等于直接给答案，一定算决定性；否则看「翻出合法牌」这一支
    会不会把结论翻过来（翻出非法牌那一支恒为必假、必质疑，所以只在不质疑时才额外算决定性）。
    """
    if k - state.revealed <= 1:
        return True
    now = confirm_choice(confirm_probability(counts, target, k, hand, state))
    legal_case, illegal_case = reveal_outcomes(counts, target, k, hand, state)
    return confirm_choice(legal_case) != now or (now != "doubt" and confirm_choice(illegal_case) != now)


def wants_potion(
    probability: float,
    potions_left: int,
    hp: int | None,
    *,
    decisive: bool = False,
) -> bool:
    """要不要在确认阶段烧一瓶透视药水（按血量分档 hp_scaled）。

    Args:
        probability: 当前 P(真)。
        potions_left: 我方药水剩余次数。
        hp: 我方当前血量（0~3）；None 表示读不到。
        decisive: 翻一张是否会改变结论，仅在 hp 读不到时用作降级判据。
    """
    if potions_left <= 0:
        return False
    if hp is None:
        # 读不到血量：退回 decisive（只在翻一张能翻转判断时用），比盲用 / 不用都稳
        return decisive
    if hp <= 1:
        return True  # 濒死，必用
    if hp == 2:
        return abs(probability - CONFIRM_TRUST_THRESHOLD) < HP_SCALED_BAND
    return False  # 3 血，留着


@dataclass(frozen=True)
class ClaimPlan:
    """一次出牌决策：kind 只用于日志，slots 是手牌槽下标。"""

    kind: Literal["truth", "bluff"]
    slots: tuple[int, ...]
    probability: float

    @property
    def size(self) -> int:
        return len(self.slots)


def claim_plan(hand_suits: Sequence[int | None], counts: Counts, target: int) -> ClaimPlan:
    """声明者决策（自适应）：目标是让下家猜错。

    胜负条件是「下家猜错 → 下家掉血」，所以：
      · 下家视角的 P 低于 CLAIM_THRESHOLD 时下家会**质疑** —— 此时说**真话**才能让下家猜错，
        且 k 取到能凑的最大值（P(k) 对 k 单调递减，k 越大 P 越低，越稳）；
      · P 高于阈值时下家会**信任** —— 此时**诈唬**（出 2 张非合法牌）才能让下家猜错；
      · 手上合法牌不足 2 张就凑不出真话，只能诈唬。
    这里的 P 用不扣手牌的 naive 口径：这一步预测的是下家的判断，而下家是从它自己视角算的。
    """
    legal = [i for i, suit in enumerate(hand_suits) if suit is not None and suit in (target, WILD)]
    illegal = [i for i, suit in enumerate(hand_suits) if suit is not None and suit != target and suit != WILD]

    if len(legal) >= MIN_CLAIM:
        size = min(MAX_CLAIM, len(legal))
        probability = claimer_opponent_belief(counts, target, size)
        if probability < CLAIM_THRESHOLD:
            return ClaimPlan("truth", tuple(legal[:size]), probability)
        if len(illegal) >= MIN_CLAIM:
            return ClaimPlan("bluff", tuple(illegal[:MIN_CLAIM]), claimer_opponent_belief(counts, target, MIN_CLAIM))
        # 凑不出诈唬牌，退回真话（下家会信任，但总比空过强）
        return ClaimPlan("truth", tuple(legal[:size]), probability)

    bluffable = (illegal + legal)[:MIN_CLAIM]
    if len(bluffable) >= MIN_CLAIM:
        return ClaimPlan("bluff", tuple(bluffable), claimer_opponent_belief(counts, target, MIN_CLAIM))
    return ClaimPlan("truth", (), 0.0)


_CLAIM_K = re.compile(r"这\s*([0-9])\s*张牌")
_FIRST_INT = re.compile(r"[0-9]+")


def parse_claim_k(text: str) -> int | None:
    """从「阿夫西维声称这3张牌都是毛斗篷」里取 k；越界或读不到返回 None。"""
    found = _CLAIM_K.search(text)
    if found is None:
        return None
    value = int(found.group(1))
    return value if MIN_CLAIM <= value <= MAX_CLAIM else None


def parse_first_int(text: str) -> int | None:
    """取文本里的第一个整数（「剩余次数：0」→ 0，「3450」→ 3450）。"""
    found = _FIRST_INT.search(text)
    return int(found.group()) if found is not None else None


def slot_index(box_x: int) -> int | None:
    """手牌模板命中框的左边界 → 手牌槽下标。

    模板是按「槽心 x - 28」裁的，所以先把槽心还原出来再就近取整；偏太远视为误匹配。
    """
    slot_x = box_x + HAND_TEMPLATE_DX
    nearest = min(range(len(HAND_SLOT_CENTERS)), key=lambda i: abs(HAND_SLOT_CENTERS[i] - slot_x))
    return nearest if abs(HAND_SLOT_CENTERS[nearest] - slot_x) <= HAND_SLOT_TOLERANCE else None


def digit_roi(frame: np.ndarray, base: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    """在 base 里框出亮色数字的紧致包围盒；数字还没渐入、或这一带被别的界面占着就返回 None。

    结算页刚出现时这一带还是「诈唬失败」横幅文字（墨迹横跨整个基础框），数字面板随后才渐入。
    固定框会把横幅认成一串数字（实测 300 被读成 1300），所以这里按墨迹的宽度和高度把两种
    情况都挡掉，让调用方换帧重试 —— 宁可判「积分未知」，也不报一个错数。
    """
    x, y, width, height = base
    patch = np.asarray(frame)[y : y + height, x : x + width]
    if patch.ndim == 3:
        patch = patch[:, :, :3]
    mask = patch > SCORE_INK_THRESHOLD
    if mask.ndim == 3:
        mask = mask.all(axis=2)

    columns = np.flatnonzero(mask.any(axis=0))
    rows = np.flatnonzero(mask.any(axis=1))
    if columns.size == 0 or rows.size == 0:
        return None

    ink_width = int(columns[-1]) - int(columns[0]) + 1
    ink_height = int(rows[-1]) - int(rows[0]) + 1
    if not (SCORE_MIN_HEIGHT <= ink_height <= SCORE_MAX_HEIGHT) or ink_width > SCORE_MAX_WIDTH:
        return None
    return (
        x + int(columns[0]) - SCORE_INK_PAD,
        y + int(rows[0]) - SCORE_INK_PAD,
        ink_width + SCORE_INK_PAD * 2,
        ink_height + SCORE_INK_PAD * 2,
    )


def _frame(context: Context) -> np.ndarray:
    return context.tasker.controller.post_screencap().wait().get()


def _hit(context: Context, img: np.ndarray, node: str) -> bool:
    return is_hit(context.run_recognition(node, img))


def _click(context: Context, point: tuple[int, int]) -> None:
    """所有点击的唯一入口 —— 用户点了停止就不再碰屏幕。"""
    if context.tasker.stopping:
        return
    context.tasker.controller.post_click(point[0], point[1]).wait()


def _click_node(context: Context, img: np.ndarray, node: str, fallback: tuple[int, int]) -> None:
    """点识别框中心，识别不到时回落到标定坐标。

    界面元素会随主界面/活动状态漂移（实测主界面左上图标纵向差约 30px），写死坐标会点空；
    识别框中心天然跟随漂移。fallback 只在识别失败时用，保证不会因为一次识别 miss 就卡死。
    """
    detail = context.run_recognition(node, img)
    if detail is not None and detail.hit and detail.box is not None:
        x, y, width, height = detail.box
        _click(context, (int(x + width // 2), int(y + height // 2)))
        return
    logger.debug(f"{node} 识别失败，回落标定坐标 {fallback}")
    _click(context, fallback)


def _param_int(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        logger.debug(f"参数 {key} 非法（{value!r}），回落到默认值 {default}")
        return default
    return int(value)


def _param_str(params: dict[str, Any], key: str, default: str, allowed: tuple[str, ...]) -> str:
    """取枚举型字符串参数；缺省或非法都回落默认值（不抛异常，任务不能因为一个坏参数就崩）。"""
    value = params.get(key, default)
    if isinstance(value, str) and value in allowed:
        return value
    logger.debug(f"参数 {key} 非法（{value!r}），回落到默认值 {default}")
    return default


def _with_retries[T](
    context: Context,
    img: np.ndarray,
    read: Callable[[np.ndarray], T | None],
    what: str,
    *,
    attempts: int = READ_ATTEMPTS,
    delay: float = READ_RETRY_DELAY,
) -> T | None:
    """读一次不行就换新帧重试；全部失败返回 None 并写清是哪个字段。"""
    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
            img = _frame(context)
        value = read(img)
        if value is not None:
            return value
    logger.debug(f"{what} 连续 {attempts} 次读取失败")
    return None


def _game_over_line(score: int | None, games_played: int) -> str:
    """「结束单轮游戏」的日志行：带本局积分与已刷次数（不出现 once / full 等模式字样）。"""
    if score is None:
        return f"结束单轮游戏：本局积分未知，已刷 {games_played} 次"
    return f"结束单轮游戏：本局 +{score} 分，已刷 {games_played} 次"


def _summary_line(score: int | None, cap: int, games_played: int) -> str:
    """「任务结束」的日志行：总次数；配了积分上限时再说是否达标。"""
    head = f"任务结束，总共刷了 {games_played} 次"
    if cap <= 0 or score is None:
        return head
    verdict = "已达标" if score >= cap else "未达标"
    return f"{head}（诈唬分 {score}/{cap}，{verdict}）"


def score_cap_reached(score: int | None, cap: int) -> bool:
    """诈唬分是否已达上限。cap <= 0 视为没配上限，与 _summary_line 的口径保持一致。"""
    return score is not None and cap > 0 and score >= cap


@AgentServer.custom_action("WeShared")
class WeShared(CustomAction):
    """任务入口：清空本次任务的局数与手牌缓存。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        WeSharedTurnLoop.reset_task()
        logger.debug("魔精诈唬牌：开始刷诈唬分")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("WeSharedScoreCheck")
class WeSharedScoreCheck(CustomAction):
    """停在活动页时的双重门控：诈唬分到 score_cap、或局数到 max_games，任一达标就结束任务。

    局数门控必须放在这里而不是 WeSharedTurnLoop：实测点**第一次**「开始游戏」（活动页 → 牌桌总览）
    就已经算进入对局了 —— 那时按左上返回会弹「中途退出将视为放弃本局游戏」。所以超限必须停在
    **活动页**，也就是 WeSharedStartGame 之前。
    """

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        cap = _param_int(parse_params(argv.custom_action_param), "score_cap", DEFAULT_SCORE_CAP)
        score = parse_first_int(ocr_text(context.run_recognition(SCORE_NODE, _frame(context))))
        if score is None:
            logger.debug("诈唬分读数失败，本次不按分数结束")
        else:
            logger.debug(f"当前诈唬分 {score} / 目标 {cap}")
            if score_cap_reached(score, cap):
                self._finish(context, score, cap)
                return CustomAction.RunResult(success=True)

        if WeSharedTurnLoop.gate_reached():
            self._finish(context, score, cap)
        return CustomAction.RunResult(success=True)

    @staticmethod
    def _finish(context: Context, score: int | None, cap: int) -> None:
        """把「任务结束，总共刷了 N 次」写进运行日志，再 override_next 触发报告节点收尾。"""
        content = _summary_line(score, cap, WeSharedTurnLoop.games_played)
        context.override_next(SCORE_CHECK_NODE, [REPORT_SUMMARY_NODE])
        logger.info(content)


@AgentServer.custom_action("WeSharedTurnLoop")
class WeSharedTurnLoop(CustomAction):
    """牌局循环：点牌桌总览上的「开始游戏」并自主驱动一局，直到「游戏结束」。

    局数上限**不在这里判**（见 WeSharedScoreCheck 的说明）：这里只负责记账，并把 task 通过
    override 传进来的 max_games 发布到类变量上供 WeSharedScoreCheck 读取 —— 参数仍挂在
    WeSharedTurnLoop 上（tasks/WeShared.json 的 override 目标就是本节点），门控前移后不必改 task 文件。
    """

    games_played: int = 0
    # 本局数上限：每次进本节点时从自己的 custom_action_param 刷新（task 会 override 这个节点）
    max_games: int = DEFAULT_MAX_GAMES
    # 刷取模式：once = 只打一局；full = 打到诈唬分达标
    mode: str = DEFAULT_MODE
    # 本圈我方手牌计数；None = 本圈还没见过自己的手牌（确认阶段降级用 naive 口径）
    hand: Counts | None = None
    # 上一次读到的「剩余」总数，回涨即新一圈
    previous_total: int = 0

    @classmethod
    def reset_task(cls) -> None:
        cls.games_played = 0
        cls.max_games = DEFAULT_MAX_GAMES
        cls.mode = DEFAULT_MODE
        cls.hand = None
        cls.previous_total = 0

    @classmethod
    def game_limit(cls) -> int:
        """本次任务最多打几局：只跑一遍 = 1，跑到满分 = max_games。"""
        return 1 if cls.mode == MODE_ONCE else cls.max_games

    @classmethod
    def gate_reached(cls) -> bool:
        """局数门控：第一局之前（games_played == 0）恒放行，之后按 game_limit() 判。"""
        return cls.games_played > 0 and cls.games_played >= cls.game_limit()

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        cls = type(self)
        params = parse_params(argv.custom_action_param)
        cls.max_games = _param_int(params, "max_games", DEFAULT_MAX_GAMES)
        cls.mode = _param_str(params, "mode", DEFAULT_MODE, CLAIM_MODES)
        cls.games_played += 1
        logger.info(f"开始单轮游戏：第 {cls.games_played} 局")
        logger.debug(f"本局参数：模式 {cls.mode}，局数上限 {cls.game_limit()}")
        cls.hand = None
        cls.previous_total = 0
        _click_node(context, _frame(context), START_GAME_NODE, POINT_START_GAME)
        time.sleep(SETTLE_DELAY)
        self._drive_match(context)
        return CustomAction.RunResult(success=True)

    def _drive_match(self, context: Context) -> None:
        """轮询判别四种界面，直到「游戏结束」、超时或用户点了停止。对手思考有数秒延迟，只能等。"""
        deadline = time.monotonic() + MATCH_TIMEOUT
        while time.monotonic() < deadline and not context.tasker.stopping:
            img = _frame(context)
            if _hit(context, img, GAME_OVER_NODE):
                self._report_game_over(context, img)
                return
            if _hit(context, img, CONFIRM_PHASE_NODE):
                self._act_confirm(context, img)
                continue
            if _hit(context, img, PICK_PROMPT_NODE):
                self._act_claim(context, img)
                continue
            if _hit(context, img, ROUND_BANNER_NODE):
                logger.debug("Round 宣告中，等待出牌阶段")
                time.sleep(SETTLE_DELAY)
                continue
            time.sleep(POLL_INTERVAL)
        if context.tasker.stopping:
            logger.debug("收到停止请求，放弃本局")
            return
        logger.debug("本局超时未识别到「游戏结束」，交给后续节点处理")

    def _report_game_over(self, context: Context, img: np.ndarray) -> None:
        """把「结束单轮游戏（本局积分、已刷次数）」写进运行日志。"""
        content = _game_over_line(self._read_game_score(context, img), type(self).games_played)
        logger.info(content)

    def _read_game_score(self, context: Context, img: np.ndarray) -> int | None:
        """结算数字是渐入的：先等数字墨迹出现，再按墨迹收紧框去识别。

        数字没出来之前这一带是横幅文字，固定框会把它认成一串数字，所以 digit_roi 返回 None
        就当「还没出来」，交给 _with_retries 换帧重试。
        """

        def read(frame: np.ndarray) -> int | None:
            roi = digit_roi(frame, GAME_SCORE_ROI)
            if roi is None:
                return None
            detail = context.run_recognition(GAME_SCORE_NODE, frame, {GAME_SCORE_NODE: {"roi": list(roi)}})
            return parse_first_int(ocr_text(detail))

        return _with_retries(
            context,
            img,
            read,
            "本局积分",
            attempts=SCORE_READ_ATTEMPTS,
            delay=SCORE_READ_DELAY,
        )

    def _wait_phase_gone(self, context: Context, node: str, timeout: float = 15.0) -> None:
        """等这一步的界面真的消失，避免「点了没生效」时对同一个界面重复下手。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not context.tasker.stopping:
            if not _hit(context, _frame(context), node):
                return
            time.sleep(POLL_INTERVAL)
        if not context.tasker.stopping:
            logger.debug(f"{node} 在 {timeout:.0f}s 内仍未消失，继续轮询")

    def _wait_confirm_stable(self, context: Context) -> None:
        """确认阶段有牌飞入、文案滑入、数字跳动 —— 读之前先等画面静止，否则会读空。"""
        try:
            ok = context.wait_freezes(
                wait_freezes_param=JWaitFreezes(time=FREEZE_TIME, target=CONFIRM_STABLE_ROI, timeout=3000)
            )
        except Exception as e:  # noqa: BLE001 - 等静止只是优化，失败了照样能读（后面还有重试）
            logger.debug(f"等待确认阶段画面静止失败：{e}")
            return
        if not ok:
            logger.debug("确认阶段画面 3s 内未静止，直接读（后面还有重试兜底）")

    def _read_claim_k(self, context: Context, img: np.ndarray) -> int | None:
        """声称文案里的 k（「这 N 张牌」）；动画期间会读空，靠 _with_retries 重试。"""
        return _with_retries(
            context,
            img,
            lambda frame: parse_claim_k(ocr_text(context.run_recognition(CLAIM_BAR_NODE, frame))),
            "声称文案 k",
        )

    def _act_confirm(self, context: Context, img: np.ndarray) -> None:
        """确认阶段：算 P(真)，落在 0.5 附近先用药水翻牌，再决定信任 / 质疑。"""
        self._wait_confirm_stable(context)
        img = _frame(context)
        counts = self._read_counts(context, img)
        target = self._read_target(context, img)
        k = self._read_claim_k(context, img)

        missing = [name for name, value in (("剩余", counts), ("目标花色", target), ("k", k)) if value is None]
        if counts is None or target is None or k is None:
            logger.debug(f"确认阶段读数不全，缺：{'、'.join(missing)} → 保守质疑")
            _click_node(context, _frame(context), DOUBT_NODE, POINT_DOUBT)
            time.sleep(SETTLE_DELAY)
            self._wait_phase_gone(context, CONFIRM_PHASE_NODE)
            return

        potions = parse_first_int(ocr_text(context.run_recognition(POTION_LEFT_NODE, img))) or 0
        # 血量每局都在变（扣血后立刻变），所以每次确认都重读，绝不缓存
        hp = self._read_my_hp(context, img)
        base = counts
        legal_before = base.legal(target)
        total_before = base.total()
        state = RevealState()
        probability = confirm_probability(base, target, k, type(self).hand, state)

        while not state.illegal and k - state.revealed > 0 and not context.tasker.stopping:
            decisive = potion_is_decisive(base, target, k, type(self).hand, state)
            if not wants_potion(probability, potions, hp, decisive=decisive):
                break
            _click_node(context, img, POTION_NODE, POINT_POTION)
            time.sleep(SETTLE_DELAY)
            fresh = self._read_counts(context)
            if fresh is None or not reveal_advanced(total_before, fresh):
                logger.debug("药水翻牌没生效（剩余未减少），当作没翻开")
                break
            potions -= 1
            total_before = fresh.total()
            legal_now = fresh.legal(target)
            state = apply_reveal(state, legal_before, legal_now)
            legal_before = legal_now
            probability = confirm_probability(base, target, k, type(self).hand, state)

        choice = confirm_choice(probability)
        logger.debug(
            f"确认阶段：剩余={base} 我方手牌={type(self).hand} 目标={SUIT_NAMES[target]} k={k} "
            f"血量={hp} 药水余={potions} 翻开={state.revealed}(非法={state.illegal}) "
            f"P(真)={probability:.3f} → {'信任' if choice == 'trust' else '质疑'}"
        )
        _click_node(
            context,
            img,
            TRUST_NODE if choice == "trust" else DOUBT_NODE,
            POINT_TRUST if choice == "trust" else POINT_DOUBT,
        )
        time.sleep(SETTLE_DELAY)
        self._wait_phase_gone(context, CONFIRM_PHASE_NODE)

    def _act_claim(self, context: Context, img: np.ndarray) -> None:
        """出牌阶段：按决策选 2~5 张，依次点手牌槽再点「确认出牌」。"""
        counts = self._read_counts(context, img)
        target = self._read_target(context, img)
        suits = self._read_hand(context, img)
        if counts is None or target is None:
            logger.debug(f"出牌阶段读数不全（剩余={counts} 目标={target}），兜底出前 2 张")
            plan = ClaimPlan("truth", (0, 1), 0.0)
        else:
            plan = claim_plan(suits, counts, target)

        slots = plan.slots or (0, 1)
        logger.debug(
            f"出牌阶段：剩余={counts} 手牌={suits} 目标={target} → {plan.kind} "
            f"出 {len(slots)} 张 {slots}（下家视角 P={plan.probability:.3f}）"
        )
        for slot in slots:
            _click(context, (HAND_SLOT_CENTERS[slot], HAND_SLOT_Y))
            time.sleep(CLICK_INTERVAL)
        _click_node(context, img, CONFIRM_PLAY_NODE, POINT_CONFIRM_PLAY)
        time.sleep(SETTLE_DELAY)

        played = set(slots)
        type(self).hand = counts_from_suits([suit for index, suit in enumerate(suits) if index not in played])
        self._wait_phase_gone(context, PICK_PROMPT_NODE)

    def _read_counts(self, context: Context, img: np.ndarray | None = None) -> Counts | None:
        """读右上「剩余」四项（棕 / 蓝 / 绿 / 万能）。

        计数随亮牌实时变化，每次决策前都要重读；四个框**各自重试**（动画期间个别框会读空），
        只有换新帧重试 READ_ATTEMPTS 次后仍缺才判失败。
        """
        frame = img if img is not None else _frame(context)
        values: list[int | None] = [None, None, None, None]
        for attempt in range(READ_ATTEMPTS):
            if attempt:
                time.sleep(READ_RETRY_DELAY)
                frame = _frame(context)
            for index, roi in enumerate(COUNT_ROIS):
                if values[index] is not None:
                    continue
                detail = context.run_recognition(COUNT_NODE, frame, {COUNT_NODE: {"roi": list(roi)}})
                values[index] = parse_first_int(ocr_text(detail))
            if all(value is not None for value in values):
                break

        brown, blue, green, wild = values
        if brown is None or blue is None or green is None or wild is None:
            logger.debug(f"「剩余」四项读不全：棕={brown} 蓝={blue} 绿={green} 万能={wild}")
            return None

        counts = Counts(brown, blue, green, wild)
        cls = type(self)
        if cls.previous_total > 0 and counts.total() > cls.previous_total:
            # 剩余回涨 = 新一圈重洗重发，上一圈记的手牌作废
            logger.debug(f"剩余回涨 {cls.previous_total}→{counts.total()}，清空手牌缓存")
            cls.hand = None
        cls.previous_total = counts.total()
        return counts

    @staticmethod
    def _count_matches(context: Context, img: np.ndarray, node: str) -> int:
        """数一个模板节点在一帧里命中了几个（同一模板重复出现的场景，如三颗心）。"""
        detail = context.run_recognition(node, img)
        if detail is None or not detail.hit:
            return 0
        return len(list(detail.filtered_results))

    def _read_my_hp(self, context: Context, img: np.ndarray) -> int | None:
        """我方血量：亮心数就是血量；亮心 + 暗心合计为 0 说明这一排不在画面上 → None。

        区分 0 血与「读不到」全靠暗心模板：已淘汰时三颗都是暗心（亮 0 + 暗 3 → 0），
        不在牌桌界面时两个模板都不命中（0 + 0 → None）。
        """
        full = self._count_matches(context, img, MY_HP_NODE)
        empty = self._count_matches(context, img, MY_HP_EMPTY_NODE)
        if full + empty <= 0:
            logger.debug("我方心数那一排不在画面上，血量按未知处理")
            return None
        return min(full, MY_HP_MAX)

    @staticmethod
    def _read_target(context: Context, img: np.ndarray) -> int | None:
        """顶部目标牌图标 → 花色下标：三个模板取分数最高的那个，低于下限视为没认出来。"""

        def read(frame: np.ndarray) -> int | None:
            best: tuple[float, int] | None = None
            for suit, node in enumerate(TARGET_NODES):
                for result in results_as(context.run_recognition(node, frame), BoxAndScoreResult):
                    score = float(result.score)
                    if best is None or score > best[0]:
                        best = (score, suit)
            if best is None or best[0] < TARGET_MIN_SCORE:
                logger.debug(f"目标牌图标没认出来（最高分 {best[0] if best else 0.0:.3f}）")
                return None
            return best[1]

        return _with_retries(context, img, read, "目标牌图标")

    @staticmethod
    def _read_hand(context: Context, img: np.ndarray) -> tuple[int | None, ...]:
        """6 个手牌槽的花色：每槽取分数最高的模板，低于下限就当没认出来。"""
        best: dict[int, tuple[float, int]] = {}
        for suit, node in enumerate(HAND_NODES):
            for result in results_as(context.run_recognition(node, img), BoxAndScoreResult):
                index = slot_index(int(result.box[0]))
                if index is None:
                    continue
                score = float(result.score)
                current = best.get(index)
                if current is None or score > current[0]:
                    best[index] = (score, suit)
        return tuple(
            best[i][1] if i in best and best[i][0] >= HAND_MIN_SCORE else None for i in range(len(HAND_SLOT_CENTERS))
        )
