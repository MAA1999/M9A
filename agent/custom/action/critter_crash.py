import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import is_hit, ocr_text
from utils.params import parse_params

# 翻斗棋策略表：棋子白名单、棋盘 ROI、奖励优先级、选领队卡位都收敛到这一个数据文件，
# 换版本（3.5 鹿蜀成长流 → 4.0）只改 JSON，不动代码。
# 文件缺失/损坏时回落到内置 4.0 策略，保证数据文件问题不会改变 3.5 行为。
#
# 历史策略表（原以注释形式内联在本文件，现已迁出，留此备查）：
#   - 3.2 工厂流：Knight(8级) + Cat1-4/Robot1-4/Item1-3 占位
#   - 4.0 鹿蜀成长流：见 data/critter_crash/strategy-4.0.json（唯一策略表，运行时读盘）
STRATEGY_PATH = Path("data/critter_crash/strategy-4.0.json")


class StrategyError(ValueError):
    """翻斗棋策略表结构非法。"""


@dataclass(frozen=True)
class CardSpec:
    """一张棋子的放置规则。"""

    name: str
    max_level: int
    # 可放置格白名单；顺序即 find_empty_position 的优先级
    positions: tuple[tuple[int, int], ...]


# 满级角标（CritterCrash/Lv3.png）相对棋盘格的 ROI 偏移。
# 默认 = 3.5 的实测值；棋盘换版后角标相对格子的位置可能变，故外置以便只调数据。
DEFAULT_LEVEL_BADGE_OFFSET = (-52, -58, 45, 15)

# 选领队页「已被选中」角标（LeaderSelected.png）相对卡位点击点的 ROI 偏移。
# 默认 = 4.0 实测：卡位点 (215, 355) 时角标窗口为 [45, 460, 140, 70]。
DEFAULT_LEADER_BADGE_OFFSET = (-170, 105, 140, 70)

# 左上返回键的点击点（4.0 实测，对局页 / 选领队页 / 奇遇弹窗同一位置）。
# 需要「退出去重摇」时靠它离开当前这一步。
DEFAULT_BACK_BUTTON = (46, 43)

# 「每局只用一次」的节点：它们的 max_hit 是按**任务**计的，打几局就会耗尽，
# 之后再也认不出来 → 必然死端。所以每局开始（回到对局页）时把命中计数清零。
# 实测：第 3 局起 CCNext（奇遇「下一步」）不再命中 → CCStart 卡 20s 超时 → 任务报 4000。
MATCH_SCOPED_HIT_NODES = ("CCNext", "CCEnterBattle")


@dataclass(frozen=True)
class PeopleSpec:
    """选领队页的卡位与优先棋手。

    3.5 的选领队页是竖排列表，靠 pipeline 模板逐个匹配；4.0 变成全屏 3 卡布局，
    卡位固定，于是把「卡位点击中心 + 优先棋手 + 已选中角标」外置成数据。

    为什么必须有兜底：4.0 选领队页在没选领队时「进入战斗」是**禁用态**，点了不响应，
    任务会在该页终结（实测任务级 status 4000）；而退出去重开也刷不到别的领队
    （实测：退到主菜单再点「箱中对决」会回到同一局，且已消耗 1 次次数）。
    """

    # 卡位点击中心（按屏上从左到右）
    slots: tuple[tuple[int, int], ...]
    # 优先棋手 id，顺序即优先级；认不出任何优先棋手时点 slots[0]
    preferred: tuple[str, ...]
    # 刷新按钮 ROI；None 表示该版本没有刷新按钮，跳过刷新分支
    refresh: tuple[int, int, int, int] | None
    # 「已被选中」角标相对卡位点击点的 ROI 偏移；None 表示用 DEFAULT_LEADER_BADGE_OFFSET
    badge_offset: tuple[int, int, int, int] | None = None
    # 没有优先棋手时最多退出重摇几次；0 表示不重摇，直接兜底选第一个卡位
    max_reroll: int = 0
    # 左上返回键点击点；None 表示用 DEFAULT_BACK_BUTTON
    back_button: tuple[int, int] | None = None

    def back_point(self) -> tuple[int, int]:
        """退出重摇时点的返回键坐标。"""
        return self.back_button or DEFAULT_BACK_BUTTON

    def can_reroll(self, rerolls_used: int) -> bool:
        """本次任务在已用 rerolls_used 次重摇后，还能不能再摇一次。"""
        return rerolls_used < self.max_reroll

    def click_point(self, slot_index: int) -> tuple[int, int] | None:
        """第 slot_index 个卡位的点击中心；越界返回 None。"""
        if 0 <= slot_index < len(self.slots):
            return self.slots[slot_index]
        return None

    def pick_slot(self, slot_ids: Sequence[str | None]) -> int | None:
        """给定各卡位识别到的棋手 id，返回该点哪个卡位。

        `slot_ids` 与 `slots` 同序，认不出填 None。按 preferred 顺序取第一个
        「在某个卡位上出现过」的棋手；都不匹配或 preferred 为空则返回 None
        （交由调用方回落到兜底卡位）。
        """
        if not self.preferred:
            return None
        for leader_id in self.preferred:
            for index, slot_id in enumerate(slot_ids):
                if slot_id == leader_id and index < len(self.slots):
                    return index
        return None

    def has_refresh(self) -> bool:
        """该版本选领队页是否有刷新按钮。"""
        return self.refresh is not None

    def effective_badge_offset(self) -> tuple[int, int, int, int]:
        """「已被选中」角标的 ROI 偏移（相对卡位点击点）。"""
        return self.badge_offset or DEFAULT_LEADER_BADGE_OFFSET

    def badge_roi(self, slot_index: int) -> list[int] | None:
        """第 slot_index 个卡位的「已被选中」角标 ROI；卡位越界返回 None。"""
        point = self.click_point(slot_index)
        if point is None:
            return None
        dx, dy, width, height = self.effective_badge_offset()
        return [point[0] + dx, point[1] + dy, width, height]


@dataclass(frozen=True)
class EncounterSpec:
    """「本次奇遇」弹窗的白名单与重摇额度。

    为什么要按奇遇门控而不是按领队：**棋子池由「奇遇 → 卡包」决定**，领队只影响技能
    （`auto_chess_master_library` → `auto_chess_cardpack.chessPool`）。实机 20 分钟实测：
    按「领队=30027」重摇 15 次只命中 1 次（~7%），而非目标奇遇的对局是纯浪费
    （白名单卡一张都不出，机器人只能刷新+开战，4 分钟打空场）。
    奇遇名在弹窗上是**大号文字**，OCR 实测 3/3 命中、负对照正确 miss，判定是确定的。
    """

    # 可接受的奇遇名；空表示不门控（任何奇遇都开打）
    accept: tuple[str, ...] = ()
    # 名字不匹配时最多退出重摇几次；0 表示不重摇
    max_reroll: int = 0
    # 左上返回键点击点；None 表示用 DEFAULT_BACK_BUTTON
    back_button: tuple[int, int] | None = None

    def back_point(self) -> tuple[int, int]:
        """退出重摇时点的返回键坐标。"""
        return self.back_button or DEFAULT_BACK_BUTTON

    def accepts(self, name: str) -> bool:
        """OCR 到的奇遇名是否在名单里（容忍 OCR 多吐/少吐空格）。"""
        normalized = name.replace(" ", "")
        if not normalized:
            return False
        return any(candidate.replace(" ", "") in normalized for candidate in self.accept)


@dataclass(frozen=True)
class StrategySpec:
    """一套完整的翻斗棋策略。"""

    version: str
    board_rows: int
    board_cols: int
    board_rois: tuple[tuple[tuple[int, int, int, int], ...], ...]
    cards: tuple[CardSpec, ...]
    # 奖励区识别顺序；空表示沿用 cards 顺序
    award_priority: tuple[str, ...]
    # 选领队页卡位；None 表示沿用 pipeline 模板匹配（3.5 行为）
    people: PeopleSpec | None = None
    # 「本次奇遇」白名单；None 表示不门控
    encounters: EncounterSpec | None = None
    # 满级角标相对棋盘格的 ROI 偏移；None 表示用 DEFAULT_LEVEL_BADGE_OFFSET
    level_badge_offset: tuple[int, int, int, int] | None = None

    def badge_offset(self) -> tuple[int, int, int, int]:
        """满级角标的 ROI 偏移（相对棋盘格）。"""
        return self.level_badge_offset or DEFAULT_LEVEL_BADGE_OFFSET

    def card_names(self) -> tuple[str, ...]:
        """奖励区要尝试识别的卡名，顺序即优先级。"""
        return self.award_priority or tuple(card.name for card in self.cards)


# 内置 4.0 策略（鹿蜀成长流）。与策略表同构并走同一套校验，避免两套结构漂移。
def _parse_int(value: Any, label: str, problems: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{label}: 应为整数")
        return None
    return value


def _parse_slot(value: Any, label: str, problems: list[str]) -> tuple[int, int] | None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        problems.append(f"{label}: 应为长度 2 的 [row, col]")
        return None
    coords: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            problems.append(f"{label}: 坐标应为整数")
            return None
        coords.append(item)
    return (coords[0], coords[1])


def _parse_rect(value: Any, label: str, problems: list[str]) -> tuple[int, int, int, int] | None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 4:
        problems.append(f"{label}: ROI 应为长度 4 的 [x, y, w, h]")
        return None
    nums: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            problems.append(f"{label}: ROI 元素应为整数")
            return None
        nums.append(item)
    return (nums[0], nums[1], nums[2], nums[3])


def _parse_card(value: Any, label: str, problems: list[str]) -> CardSpec | None:
    if not isinstance(value, dict):
        problems.append(f"{label}: 应为对象，含 name/max_level/positions")
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name:
        problems.append(f"{label}: name 缺失或为空")
        return None
    card_label = f"{label} {name}"

    max_level = _parse_int(value.get("max_level"), f"{card_label} max_level", problems)
    if max_level is None:
        return None
    if max_level < 1:
        problems.append(f"{card_label}: max_level 应 >= 1")
        return None

    raw_positions = value.get("positions")
    if isinstance(raw_positions, (str, bytes)) or not isinstance(raw_positions, Sequence) or not raw_positions:
        problems.append(f"{card_label}: positions 应为非空数组")
        return None
    positions: list[tuple[int, int]] = []
    for index, item in enumerate(raw_positions):
        slot = _parse_slot(item, f"{card_label} positions[{index}]", problems)
        if slot is None:
            return None
        positions.append(slot)
    return CardSpec(name=name, max_level=max_level, positions=tuple(positions))


def _parse_cards(raw: Any, label: str, problems: list[str]) -> tuple[CardSpec, ...]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or not raw:
        problems.append(f"{label}: 应为非空数组")
        return ()
    cards: list[CardSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        card = _parse_card(item, f"{label}[{index}]", problems)
        if card is None:
            continue
        if card.name in seen:
            problems.append(f"{label}: 卡名重复 {card.name}")
            continue
        seen.add(card.name)
        cards.append(card)
    return tuple(cards)


def _parse_people(raw: Any, problems: list[str]) -> PeopleSpec | None:
    """解析可选 people 段；缺失返回 None（= 沿用 pipeline 模板匹配）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append("people: 应为对象")
        return None

    slots: list[tuple[int, int]] = []
    raw_slots = raw.get("slots")
    if isinstance(raw_slots, (str, bytes)) or not isinstance(raw_slots, Sequence) or not raw_slots:
        problems.append("people.slots: 应为非空数组")
        return None
    for index, item in enumerate(raw_slots):
        point = _parse_slot(item, f"people.slots[{index}]", problems)
        if point is not None:
            slots.append(point)
    if len(slots) != len(raw_slots):
        return None

    preferred: list[str] = []
    raw_preferred = raw.get("preferred")
    if raw_preferred is not None:
        if isinstance(raw_preferred, (str, bytes)) or not isinstance(raw_preferred, Sequence):
            problems.append("people.preferred: 应为字符串数组")
            return None
        for item in raw_preferred:
            if not isinstance(item, str) or not item:
                problems.append(f"people.preferred: {item!r} 不是非空字符串")
                return None
            preferred.append(item)

    refresh: tuple[int, int, int, int] | None = None
    raw_refresh = raw.get("refresh")
    if raw_refresh is not None:
        refresh = _parse_rect(raw_refresh, "people.refresh", problems)
        if refresh is None:
            return None

    badge_offset: tuple[int, int, int, int] | None = None
    raw_badge = raw.get("badge_offset")
    if raw_badge is not None:
        badge_offset = _parse_rect(raw_badge, "people.badge_offset", problems)
        if badge_offset is None:
            return None

    max_reroll = 0
    raw_reroll = raw.get("max_reroll")
    if raw_reroll is not None:
        parsed_reroll = _parse_int(raw_reroll, "people.max_reroll", problems)
        if parsed_reroll is None or parsed_reroll < 0:
            problems.append("people.max_reroll: 应 >= 0")
            return None
        max_reroll = parsed_reroll

    back_button: tuple[int, int] | None = None
    raw_back = raw.get("back_button")
    if raw_back is not None:
        back_button = _parse_slot(raw_back, "people.back_button", problems)
        if back_button is None:
            return None

    return PeopleSpec(
        slots=tuple(slots),
        preferred=tuple(preferred),
        refresh=refresh,
        badge_offset=badge_offset,
        max_reroll=max_reroll,
        back_button=back_button,
    )


def _parse_encounters(raw: Any, problems: list[str]) -> EncounterSpec | None:
    """解析可选 encounters 段；缺失返回 None（= 不按奇遇名门控）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append("encounters: 应为对象")
        return None

    accept: list[str] = []
    raw_accept = raw.get("accept")
    if raw_accept is not None:
        if isinstance(raw_accept, (str, bytes)) or not isinstance(raw_accept, Sequence):
            problems.append("encounters.accept: 应为字符串数组")
            return None
        for item in raw_accept:
            if not isinstance(item, str) or not item:
                problems.append(f"encounters.accept: {item!r} 不是非空字符串")
                return None
            accept.append(item)

    max_reroll = 0
    raw_reroll = raw.get("max_reroll")
    if raw_reroll is not None:
        parsed = _parse_int(raw_reroll, "encounters.max_reroll", problems)
        if parsed is None or parsed < 0:
            problems.append("encounters.max_reroll: 应 >= 0")
            return None
        max_reroll = parsed

    back_button: tuple[int, int] | None = None
    raw_back = raw.get("back_button")
    if raw_back is not None:
        back_button = _parse_slot(raw_back, "encounters.back_button", problems)
        if back_button is None:
            return None

    return EncounterSpec(accept=tuple(accept), max_reroll=max_reroll, back_button=back_button)


def parse_strategy(raw: Any, *, source: str = str(STRATEGY_PATH)) -> StrategySpec:
    """校验并构建策略表；一次性报出全部问题，便于维护时逐条修。"""
    if not isinstance(raw, dict):
        raise StrategyError(f"{source}: 顶层应为对象")

    problems: list[str] = []

    version = raw.get("version")
    if not isinstance(version, str) or not version:
        problems.append("version: 缺失或为空")

    board = raw.get("board")
    rows: int | None = None
    cols: int | None = None
    roi_rows: list[tuple[tuple[int, int, int, int], ...]] = []
    if not isinstance(board, dict):
        problems.append("board: 缺失或不是对象")
    else:
        rows = _parse_int(board.get("rows"), "board.rows", problems)
        cols = _parse_int(board.get("cols"), "board.cols", problems)
        if rows is not None and rows < 1:
            problems.append("board.rows: 应 >= 1")
            rows = None
        if cols is not None and cols < 1:
            problems.append("board.cols: 应 >= 1")
            cols = None

        raw_rois = board.get("rois")
        if isinstance(raw_rois, (str, bytes)) or not isinstance(raw_rois, Sequence) or not raw_rois:
            problems.append("board.rois: 应为非空二维数组")
        else:
            for row_index, raw_row in enumerate(raw_rois):
                if isinstance(raw_row, (str, bytes)) or not isinstance(raw_row, Sequence):
                    problems.append(f"board.rois[{row_index}]: 应为数组")
                    continue
                parsed_row: list[tuple[int, int, int, int]] = []
                for col_index, raw_rect in enumerate(raw_row):
                    rect = _parse_rect(raw_rect, f"board.rois[{row_index}][{col_index}]", problems)
                    if rect is not None:
                        parsed_row.append(rect)
                roi_rows.append(tuple(parsed_row))
        if rows is not None and cols is not None:
            if len(roi_rows) != rows or any(len(row) != cols for row in roi_rows):
                problems.append(f"board.rois: 应为 {rows} 行 × {cols} 列")

    cards = _parse_cards(raw.get("cards"), "cards", problems)

    award_priority: list[str] = []
    raw_priority = raw.get("award_priority")
    if raw_priority is not None:
        if isinstance(raw_priority, (str, bytes)) or not isinstance(raw_priority, Sequence):
            problems.append("award_priority: 应为字符串数组")
        else:
            known = {card.name for card in cards}
            for item in raw_priority:
                if not isinstance(item, str) or item not in known:
                    problems.append(f"award_priority: {item!r} 不是 cards 里的卡名")
                    continue
                award_priority.append(item)

    people = _parse_people(raw.get("people"), problems)
    encounters = _parse_encounters(raw.get("encounters"), problems)

    level_badge_offset: tuple[int, int, int, int] | None = None
    raw_badge = raw.get("level_badge_offset")
    if raw_badge is not None:
        level_badge_offset = _parse_rect(raw_badge, "level_badge_offset", problems)

    # 棋盘坐标校验：越界的 positions 会让 find_empty_position 去索引不存在的格子；
    # 那是在识别回调里跑的，表现为「识别报错」而不是「配置错了」。所以在这里一次性拦下。
    if rows is not None and cols is not None:

        def out_of_board(slot: tuple[int, int]) -> bool:
            return not 0 <= slot[0] < rows or not 0 <= slot[1] < cols

        for card in cards:
            for row, col in card.positions:
                if out_of_board((row, col)):
                    problems.append(f"cards: {card.name} 的位置 [{row}, {col}] 超出 {rows}×{cols} 棋盘")

    if problems:
        raise StrategyError(f"{source} 有 {len(problems)} 处问题: " + "；".join(problems))

    # 走到这里说明三处必填项都已解析成功（各自的问题分支已提前进 problems 并 raise）
    if not isinstance(version, str) or rows is None or cols is None:
        raise StrategyError(f"{source}: version/board.rows/board.cols 缺失")

    return StrategySpec(
        version=version,
        board_rows=rows,
        board_cols=cols,
        board_rois=tuple(roi_rows),
        cards=cards,
        award_priority=tuple(award_priority),
        people=people,
        encounters=encounters,
        level_badge_offset=level_badge_offset,
    )


# 类级初始状态用的空策略：策略表由 CCResetData 在任务开始时读盘
# （data/critter_crash/strategy-4.0.json）。这里不再内置数据副本 —— 读盘失败就让任务明确失败，
# 不做「静默换成另一份」的兜底（曾经内置 3.5 表兜底，文件一丢就按 3.5 的棋盘 ROI 乱放且不报错）。
EMPTY_STRATEGY = StrategySpec(
    version="",
    board_rows=1,
    board_cols=1,
    board_rois=(((0, 0, 0, 0),),),
    cards=(),
    award_priority=(),
)


def load_strategy(path: Path = STRATEGY_PATH) -> StrategySpec:
    """读取并校验策略表；失败直接抛（由调用方决定怎么报错，不静默兜底）。

    Raises:
        OSError: 文件不存在或读不了
        json.JSONDecodeError: 不是合法 JSON
        UnicodeDecodeError: 不是 UTF-8
        StrategyError: 结构/取值不合法
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    strategy = parse_strategy(raw, source=str(path))
    logger.debug(f"已加载翻斗棋策略表 {path}（version={strategy.version}）")
    return strategy


def _chess_types_from(strategy: StrategySpec) -> list[dict[str, Any]]:
    """策略表 → 既有 chess_types 结构（positions 保持 tuple，供 `(row, col) in positions` 判等）。"""
    return [
        {"name": card.name, "max_level": card.max_level, "positions": list(card.positions)} for card in strategy.cards
    ]


def _board_rois_from(strategy: StrategySpec) -> list[list[list[int]]]:
    return [[list(rect) for rect in row] for row in strategy.board_rois]


@AgentServer.custom_action("CCChessboard")
class CCChessboard(CustomAction):
    """
    翻斗棋：棋盘位置记录
    """

    strategy: StrategySpec = EMPTY_STRATEGY
    board_rois: list[list[list[int]]] = _board_rois_from(EMPTY_STRATEGY)
    chess_types: list[dict[str, Any]] = _chess_types_from(EMPTY_STRATEGY)

    # 棋盘状态：None表示空位置，{'name': str, 'level': int}表示有棋子
    board: list[list[dict[str, str | int] | None]] = [
        [None] * EMPTY_STRATEGY.board_cols for _ in range(EMPTY_STRATEGY.board_rows)
    ]

    board_chesses: list[dict[str, Any]] = []

    # 本次任务已用掉的重摇次数，按用途分组：{"encounter": n, "leader": m}
    # 每次开任务 / 每进入一局都由 reset_rerolls() 清零。
    rerolls_used: dict[str, int] = {}

    @classmethod
    def apply_strategy(cls, strategy: StrategySpec) -> None:
        """切换到指定策略，并清空棋盘（尺寸/ROI/棋子白名单一起换）。"""
        cls.strategy = strategy
        cls.board_rois = _board_rois_from(strategy)
        cls.chess_types = _chess_types_from(strategy)
        cls.board = [[None] * strategy.board_cols for _ in range(strategy.board_rows)]
        cls.board_chesses = []
        cls.reset_rerolls()

    @classmethod
    def reset_rerolls(cls) -> None:
        """清空重摇记账（开任务 / 进入新一局时调用）。"""
        cls.rerolls_used = {}

    @classmethod
    def consume_reroll(cls, group: str, budget: int) -> bool:
        """按用途记账地消耗一次重摇额度；用完返回 False。

        机制（实机实测）：在**奇遇弹窗 / 选领队页**（还没点「进入战斗」）点左上返回，
        再点「箱中对决」会**重新摇**奇遇与 3 张卡片；而点了「进入战斗」之后再退出会回到同一局。
        所以重摇必须发生在开局之前，且要有上限 —— 摇不到就继续走，绝不死端。
        """
        used = cls.rerolls_used.get(group, 0)
        if used >= budget:
            return False
        cls.rerolls_used[group] = used + 1
        logger.debug(f"{group} 重摇第 {used + 1}/{budget} 次")
        return True

    @classmethod
    def reload_strategy(cls, path: Path = STRATEGY_PATH) -> StrategySpec:
        """按策略表重载棋盘配置；数据文件不可用时沿用内置 4.0 策略。"""
        strategy = load_strategy(path)
        cls.apply_strategy(strategy)
        return strategy

    @classmethod
    def board_reset(cls) -> list[list[dict[str, str | int] | None]]:
        cls.board = [[None] * cls.strategy.board_cols for _ in range(cls.strategy.board_rows)]
        cls.board_chesses = []
        return cls.board

    @classmethod
    def get_chess_info(cls, name: str) -> dict[str, Any]:
        """获取指定棋子的信息"""
        for chess in cls.chess_types:
            if chess["name"] == name:
                return chess
        return {}

    @classmethod
    def place_chess(cls, row: int, col: int, name: str, level: int = 1) -> bool:
        """在指定位置放置棋子"""
        if not cls._is_valid_position(row, col):
            return False

        chess_info = cls.get_chess_info(name)
        if not chess_info:
            return False

        # 检查是否可以放置在此位置
        if (row, col) not in chess_info["positions"]:
            return False

        # 检查位置是否为空
        if cls.board[row][col] is not None:
            return False

        cls.board[row][col] = {"name": name, "level": level}
        cls.board_chesses.append({"row": row, "col": col, "name": name, "level": level})
        return True

    @classmethod
    def upgrade_chess(cls, row: int, col: int) -> bool:
        """升级指定位置的棋子"""
        if not cls._is_valid_position(row, col):
            return False

        chess = cls.board[row][col]
        if chess is None:
            return False

        name = chess["name"]
        if not isinstance(name, str):
            return False

        chess_info = cls.get_chess_info(name)
        if chess["level"] >= chess_info.get("max_level", 1):
            return False  # 已达最高等级

        chess["level"] += 1  # pyright: ignore[reportOperatorIssue]

        # 更新board_chesses中的记录
        for item in cls.board_chesses:
            if item["row"] == row and item["col"] == col:
                item["level"] = chess["level"]
                break

        return True

    @classmethod
    def remove_chess(cls, row: int, col: int) -> bool:
        """移除指定位置的棋子"""
        if not cls._is_valid_position(row, col):
            return False

        if cls.board[row][col] is None:
            return False

        cls.board[row][col] = None

        # 从board_chesses中移除
        cls.board_chesses = [item for item in cls.board_chesses if not (item["row"] == row and item["col"] == col)]

        return True

    @classmethod
    def find_empty_position(cls, name: str) -> tuple[int, int] | None:
        """为指定棋子找到一个空位置"""
        chess_info = cls.get_chess_info(name)
        if not chess_info:
            return None

        for row, col in chess_info["positions"]:
            # 策略表越界已在 parse_strategy 拦下；这里再兜一层，避免手工注入的
            # chess_types（测试/热改）把 IndexError 抛进识别回调。
            if not cls._is_valid_position(row, col):
                continue
            if cls.board[row][col] is None:
                return (row, col)
        return None

    @classmethod
    def _is_valid_position(cls, row: int, col: int) -> bool:
        """检查位置是否有效"""
        return 0 <= row < len(cls.board) and 0 <= col < len(cls.board[0])

    @classmethod
    def can_upgrade_existing(cls, card_name: str) -> bool:
        """检查是否有现有棋子可以升级"""
        chess_info = cls.get_chess_info(card_name)
        if not chess_info:
            return False

        max_level = chess_info["max_level"]
        for chess in cls.board_chesses:
            if chess["name"] == card_name and chess["level"] < max_level:
                return True
        return False

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 这个节点（CCFlagInCombatMain）就是「我在对局页」的锚点，每轮主循环命中一次。
        # 顺手做两件「按局」的状态维护：
        # 1) 选领队重摇额度清零 —— 额度按每一局算，而不是每个任务（一个任务会连打多局，
        #    实测打完 7 轮会自动开下一局，不复位的话第二局起就只能兜底）。
        #    重摇环走在 选领队/主菜单/奇遇，不会经过这里，所以额度不会被中途刷掉。
        # 2) 清 MATCH_SCOPED_HIT_NODES 的命中计数 —— 见上面常量注释。
        type(self).reset_rerolls()
        for node_name in MATCH_SCOPED_HIT_NODES:
            try:
                context.clear_hit_count(node_name)
            except Exception as e:  # noqa: BLE001 - 计数复位失败不该拖垮主循环
                logger.warning(f"清 {node_name} 命中计数失败: {e}")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CCBuyCard")
class CCBuyCard(CustomAction):
    """
    翻斗棋：购买卡牌
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        # 策略已经在reco中制定，直接从argv.reco_detail获取结果
        detail_str = argv.reco_detail.raw_detail["best"]["detail"]
        box = argv.box

        detail_data = self._parse_detail(detail_str)
        if not detail_data:
            logger.debug("无法解析detail")
            return CustomAction.RunResult(success=False)

        action = detail_data.get("action")
        card_name = detail_data.get("name")
        if not card_name:
            logger.debug("detail中没有name")
            return CustomAction.RunResult(success=False)

        if action == 0:  # 部署
            empty_pos = CCChessboard.find_empty_position(card_name)
            if not empty_pos:
                logger.debug(f"没有空位置放置 {card_name}")
                return CustomAction.RunResult(success=False)

            row, col = empty_pos
            target_roi = CCChessboard.board_rois[row][col]

            # 执行拖拽操作，先滑动再更新内部棋盘状态以避免状态不一致
            img = context.tasker.controller.cached_image
            # 用 np 截取目标区域图片
            roi_array = img[
                target_roi[1] : target_roi[1] + target_roi[3],
                target_roi[0] : target_roi[0] + target_roi[2],
            ]
            context.override_image("ccdeploy", roi_array)
            context.run_task(
                "CCDeploy",
                {
                    "CCDeploy": {
                        "begin": list(box),
                        "end": target_roi,
                    },
                    "CCDeployFinished": {"roi": target_roi},
                },
            )
            # 尝试更新内部棋盘状态
            if CCChessboard.place_chess(row, col, card_name):
                logger.debug(f"成功放置 {card_name} 到位置 ({row}, {col})")
                return CustomAction.RunResult(success=True)
            else:
                logger.debug(f"放置 {card_name} 失败（滑动已执行），请检查界面或识别结果")
                return CustomAction.RunResult(success=False)

        elif action == 1:  # 升级
            # 找到一个可以升级的位置
            for chess in CCChessboard.board_chesses:
                if chess["name"] == card_name and chess["level"] < CCChessboard.get_chess_info(card_name)["max_level"]:
                    row, col = chess["row"], chess["col"]
                    # 计算拖拽终点（棋盘位置中心）
                    target_roi = CCChessboard.board_rois[row][col]

                    # 执行拖拽操作，先滑动再更新内部棋盘状态以避免状态不一致
                    img = context.tasker.controller.cached_image
                    # 用 np 截取目标区域图片
                    roi_array = img[
                        box[1] : box[1] + box[3],
                        box[0] : box[0] + box[2],
                    ]
                    offset = list(CCChessboard.strategy.badge_offset())
                    roi_max = [
                        target_roi[0] + offset[0],
                        target_roi[1] + offset[1],
                        target_roi[2] + offset[2],
                        target_roi[3] + offset[3],
                    ]
                    level_max_reco = context.run_recognition(
                        "CCLevelMax",
                        img,
                        pipeline_override={"CCLevelMax": {"roi": roi_max}},
                    )
                    if is_hit(level_max_reco):
                        max_level = CCChessboard.get_chess_info(card_name).get("max_level", 1)
                        chess["level"] = max_level
                        if CCChessboard.board[row][col] is not None:
                            CCChessboard.board[row][col]["level"] = max_level
                        logger.debug(f"{card_name} 在位置 ({row}, {col}) 已满级，跳过升级")
                        return CustomAction.RunResult(success=True)
                    context.override_image("ccupdate", roi_array)
                    context.run_task(
                        "CCUpdate",
                        {
                            "CCUpdate": {
                                "begin": list(box),
                                "end": target_roi,
                            },
                            "CCUpdateFinished": {"roi": list(box)},
                        },
                    )
                    if CCChessboard.upgrade_chess(row, col):
                        logger.debug(f"成功升级 {card_name} 在位置 ({row}, {col})")
                        return CustomAction.RunResult(success=True)

            logger.debug(f"没有可以升级的 {card_name}")
            return CustomAction.RunResult(success=False)

        else:
            logger.debug(f"未知action: {action}")
            return CustomAction.RunResult(success=False)

    def _parse_detail(self, detail: Any) -> dict[str, Any] | None:
        """从detail中解析type和action"""
        try:
            # 如果是dict，直接使用
            if isinstance(detail, dict):
                return detail
            # 如果是其他，尝试json.loads
            return json.loads(str(detail))
        except Exception as e:
            logger.debug(f"解析detail失败: {e}")
            return None


@AgentServer.custom_action("CCLevelUp")
class CCLevelUp(CustomAction):
    """
    翻斗棋：粘贴处升级识别，如升级则等待
    """

    level = 1

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        max_retries = 5
        times = 0
        while times < max_retries:
            reco_detail = context.run_recognition("CCLevelRec", context.tasker.controller.cached_image)
            if is_hit(reco_detail):
                # 识别到文字，判断等级
                current_level = int(ocr_text(reco_detail))
                if current_level > self.level:
                    logger.debug(f"检测到升级，从 {self.level} 升级到 {current_level}，等待中...")
                    self.level = current_level
                    time.sleep(5)  # 等待升级动画
                    break
                elif current_level == self.level:
                    logger.debug(f"当前等级仍为 {self.level}，无需等待")
                    break
            times += 1
        return CustomAction.RunResult(success=True)

    @classmethod
    def reset_level(cls):
        cls.level = 1


@AgentServer.custom_action("CCResetData")
class CCResetData(CustomAction):
    """
    翻斗棋：重置数据
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 每次开任务按策略表重建棋盘配置；custom_action_param 可用 strategy_file 指定其它策略表
        strategy_file: str | None = None
        try:
            params = parse_params(argv.custom_action_param)
            raw_path = params.get("strategy_file")
            if isinstance(raw_path, str) and raw_path:
                strategy_file = raw_path
        except ValueError as e:
            logger.warning(f"CCResetData 参数非法（{e}），使用默认策略表")

        path = Path(strategy_file) if strategy_file else STRATEGY_PATH
        try:
            CCChessboard.reload_strategy(path)
        except (OSError, ValueError) as e:
            # 策略表是硬依赖：读不到就明确失败，不带着「空棋盘 / 旧版本 ROI」继续跑
            logger.error(f"翻斗棋策略表不可用: {path}: {e}")
            return CustomAction.RunResult(success=False)
        CCLevelUp.reset_level()

        return CustomAction.RunResult(success=True)
