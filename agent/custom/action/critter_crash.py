import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
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
    # 棋盘上最多只放 1 个（辅助卡）。之后每次购买都只用于合成升级，不再占新格。
    #
    # positions 仍然要给多个备选：唯一的位置可能被贴纸/别的棋子占着，
    # 那时如果只写一格就彻底买不进来（实测 22:29 (1,1) 被贴纸占着，
    # 商店里 32124 识别分数 0.998 却一直买不了）。
    single_slot: bool = False


# 满级角标（CritterCrash/Lv3.png）相对棋盘格的 ROI 偏移。
# 默认 = 3.5 的实测值；棋盘换版后角标相对格子的位置可能变，故外置以便只调数据。
DEFAULT_LEVEL_BADGE_OFFSET = (-52, -58, 45, 15)

# 选领队页「已被选中」角标（LeaderSelected.png）相对卡位点击点的 ROI 偏移。
# 默认 = 4.0 实测：卡位点 (215, 355) 时角标窗口为 [45, 460, 140, 70]。
DEFAULT_LEADER_BADGE_OFFSET = (-170, 105, 140, 70)

# 左上返回键的点击点（4.0 实测，对局页 / 选领队页 / 奇遇弹窗同一位置）。
# 需要「退出去重摇」时靠它离开当前这一步。
DEFAULT_BACK_BUTTON = (46, 43)

# 专属贴纸箱的点击点（4.0 实测：左列上格，即棋盘 (0,0)）。
# 盒子只在每局开局存在；点一下弹道具面板，面板写明还需几回合才能开。
DEFAULT_STICKER_BOX_POINT = (354, 201)

# 奖励区**只有一格**（4.0 实测，1280x720）：roi 42,580,128,124，中心 (106, 642)。
# 底部那条 4-5 张卡是「待购物区」（商店），roi 214,520,1066,200 —— 两者不是一回事。
# 贴纸开箱后落在这唯一的一格里。
AWARD_SLOT_CENTER = (106, 642)

# 关掉道具面板的点击点（4.0 实测：面板外的空白处）。
DEFAULT_PANEL_CLOSE_POINT = (1150, 650)

# 「每局只用一次」的节点：它们的 max_hit 是按**任务**计的，打几局就会耗尽，
# 之后再也认不出来 → 必然死端。所以每局开始（回到对局页）时把命中计数清零。
# 实测：第 3 局起 CCNext（奇遇「下一步」）不再命中 → CCStart 卡 20s 超时 → 任务报 4000。
# CCSelectPeople4p0 的 max_hit 是**环路限次**（CCFlagInSelectPeople ↔ 本节点每轮都有命中，
# timeout 永不触发），同样必须按局清零，否则第二局起选领队会直接失败。
MATCH_SCOPED_HIT_NODES = ("CCNext", "CCEnterBattle", "CCSelectPeople4p0")


@dataclass(frozen=True)
class PeopleSpec:
    """选领队页的卡位与优先棋手。

    3.5 的选领队页是竖排列表，靠 pipeline 模板逐个匹配；4.0 变成全屏 3 卡布局，
    卡位固定，于是把「卡位点击中心 + 优先棋手 + 已选中角标」外置成数据。

    为什么必须有兜底：4.0 选领队页在没选领队时「进入战斗」是**禁用态**，点了不响应，
    任务会在该页终结（实测任务级 status 4000）；而重摇（`max_reroll > 0` 时点返回）
    必须先「放弃」这一局才会换牌：只按返回回主菜单、再点「箱中对决」会回到同一局
    （同名奇遇、同样的 3 张卡）。放弃那步由 pipeline 的 CCStop 承担，见文件头第 3 条。
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
class StickerSpec:
    """专属贴纸箱（4.0 每局一个，位置固定在左列上格）。

    实测（.live/acc/STICKER-FINDINGS.md）：
    - 盒子在第 (0,0)，点一下弹道具面板，面板写明「N 回合后可开箱」，N = open_round - 当前回合；
    - 开箱后贴纸进奖励区最左槽，拖到空位即上场；
    - 贴纸按角色独有：小叶尼塞 = 第 open_round 回合可用。
    """

    # 开箱所需回合数（**按角色固定**：赠送的贴纸与角色绑定，不同角色回合数不同）。
    # 小叶尼塞 = 第 2 回合。仅作日志提示，不作硬门控 —— 真正的门控是
    # 「盒子模板是否还在画面上」+ 下面的 leader 匹配：回合没到就点，只会弹道具面板。
    open_round: int | None = None
    # 贴纸归属的领队 id。贴纸按角色独有，只有选到这位领队才该开箱；
    # None 表示不门控（任何领队都开）。
    leader: str | None = None
    # 盒子点击点（控制器坐标）；None 表示用 DEFAULT_STICKER_BOX_POINT
    box_point: tuple[int, int] | None = None
    # 贴纸优先落点（棋盘 row/col）；None 表示只用 positions
    positions: tuple[tuple[int, int], ...] = ()

    def point(self) -> tuple[int, int]:
        """盒子的点击点。"""
        return self.box_point or DEFAULT_STICKER_BOX_POINT


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
    # 专属贴纸箱；None 表示该策略不处理贴纸
    sticker: StickerSpec | None = None

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
    return CardSpec(
        name=name,
        max_level=max_level,
        positions=tuple(positions),
        single_slot=bool(value.get("single_slot", False)),
    )


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


def _parse_sticker(raw: Any, label: str, problems: list[str]) -> StickerSpec | None:
    """解析专属贴纸箱配置；字段全缺时返回 None（该策略不处理贴纸）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append(f"{label}: 应为对象")
        return None

    parsed_round: int | None = None
    open_round = raw.get("open_round")
    if open_round is not None:
        parsed_round = _parse_int(open_round, f"{label}.open_round", problems)
        if parsed_round is None or parsed_round < 1:
            problems.append(f"{label}.open_round: 应 >= 1")
            return None

    box_point = None
    raw_point = raw.get("box_point")
    if raw_point is not None:
        box_point = _parse_slot(raw_point, f"{label}.box_point", problems)

    positions: list[tuple[int, int]] = []
    raw_positions = raw.get("positions")
    if raw_positions is not None:
        if isinstance(raw_positions, (str, bytes)) or not isinstance(raw_positions, Sequence):
            problems.append(f"{label}.positions: 应为数组")
        else:
            for index, item in enumerate(raw_positions):
                slot = _parse_slot(item, f"{label}.positions[{index}]", problems)
                if slot is not None:
                    positions.append(slot)

    leader: str | None = None
    raw_leader = raw.get("leader")
    if raw_leader is not None:
        if not isinstance(raw_leader, str) or not raw_leader:
            problems.append(f'{label}.leader: 应为非空字符串（领队 id，如 "30027"）')
        else:
            leader = raw_leader

    return StickerSpec(open_round=parsed_round, leader=leader, box_point=box_point, positions=tuple(positions))


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
    sticker = _parse_sticker(raw.get("sticker"), "sticker", problems)

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
        if sticker is not None:
            for row, col in sticker.positions:
                if out_of_board((row, col)):
                    problems.append(f"sticker: 位置 [{row}, {col}] 超出 {rows}×{cols} 棋盘")

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
        sticker=sticker,
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
        {
            "name": card.name,
            "max_level": card.max_level,
            "positions": list(card.positions),
            # 辅助卡只留 1 个（见 CardSpec.single_slot）
            "single_slot": card.single_slot,
        }
        for card in strategy.cards
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

    # 本局选中的领队 id；None = 未知或兜底选了一位非优先棋手。
    # 贴纸是角色专属的（小叶尼塞 = 30027），兜底选了别人就不该开箱 ——
    # 否则会把「别人的贴纸」塞进按小叶尼塞配置的贴纸位。
    leader_id: str | None = None

    # 占用格的像素标准差下限（实测空格 ≈29、有棋子 ≈68）。
    # 判空不许用另一个阈值 —— 曾经写成 _EMPTY_CELL_STD=18，而实机空格 std≈29，
    # 「std < 18」永远不成立，drop_cells_if_now_empty 变成调了但永远不命中。
    _OCCUPIED_STD = 45.0
    # 拖拽后目标格的最小画面变化（低于此值视为拖拽没生效）
    _CELL_CHANGE_MIN = 6.0

    # 上一轮看到的回合数。回合数变小 = 开了新一局，据此清空内部棋盘。
    # 不清的话一局打完棋盘状态还留着：第二局起 find_empty_position 对所有卡都返回 None，
    # 买卡全部 miss，只剩刷新把好卡一张张刷掉（实测第 13 回合起买卡/部署/升级全为 0）。
    _last_round: int | None = None

    @classmethod
    def apply_strategy(cls, strategy: StrategySpec) -> None:
        """切换到指定策略，并清空棋盘（尺寸/ROI/棋子白名单一起换）。"""
        cls.strategy = strategy
        cls.board_rois = _board_rois_from(strategy)
        cls.chess_types = _chess_types_from(strategy)
        # 棋盘 + 全部按局状态（board_full / merge_streak / card_dead / _buy_fails）一起清
        cls.board_reset()
        cls._last_round = None
        cls._buy_skip = {}
        cls.reset_rerolls()

    @classmethod
    def reset_rerolls(cls) -> None:
        """清空重摇记账（开任务 / 进入新一局时调用）。

        注意：**不要**在这里清 leader_id —— CCChessboard.run 每轮主循环都会调本方法，
        清掉会让「本局领队」每轮归零，贴纸永远等不到匹配（实测 21:41 那次）。
        领队只在真正开新局时由 reset_leader() 复位。
        """
        cls.rerolls_used = {}

    # 暂时买不动的卡 → 卡名: 剩余跳过次数
    #
    # **不能按回合整段拉黑**：原来是 card_name -> 回合号，同回合内永久生效。
    # 而一个回合能持续好几分钟，于是「一次偶发拖拽失败」会把这张卡拉黑整个回合 ——
    # 实测 21:03:15 拖 32123 失败后 skip 生效，直到 21:03:39 的 6 次识别里
    # 鹿蜀的模板根本没被调用（框架日志里 CCBuyCardRec_Template 只跑了 4 次，
    # 独缺 96x60 那张），reco 一直返回「没有找到合适的卡牌」，
    # pipeline 据此刷新商店，把鹿蜀刷掉了。
    #
    # 改成有限次数：跳过 _SKIP_TIMES 次后自动重试，既防空转也不会误杀。
    _buy_skip: dict[str, int] = {}
    # 一次失败后连续跳过多少次（每次 CCBuyCardRec 调用算一次）
    _SKIP_TIMES: int = 3

    # 棋盘已满 → 本局不再尝试买卡（新局复位）。
    #
    # 判据不靠内部棋盘的空格数：内部棋盘是从「买到什么」推出来的，与实际画面会分叉 ——
    # 实测 13:22 那轮内部一直显示「落子到 (0,4)/(0,5)」，而画面上 18 格早满了，
    # 于是每轮都买一次、每次点开详情面板又关不掉，卡到 4000。
    # 改用**连续无新增落子**的计数：只要连着 N 次买卡都是「合到已有棋子」而没有新格，
    # 就说明真实棋盘已满，置 board_full。
    board_full: bool = False
    # 连续「合到已有棋子（无新格）」的次数
    merge_streak: int = 0

    # 本局已确认「买不动」的卡（连续拖拽失败太多次）→ 卡名: True，新局复位。
    #
    # 这是死循环的保底：拖拽失败只会 skip_buy（安静 3 轮），之后又回来重试 →
    # 再失败 → 再 skip，永远转圈。实测 11:06 卡在「32126 → (1,3)」上无限循环，
    # 每 4 秒一次、持续几分钟。连续失败达到阈值就必须整局放弃这张卡。
    card_dead: dict[str, bool] = {}
    # 每张卡连续失败次数（成功一次即清零）
    _buy_fails: dict[str, int] = {}
    # 连续拖拽失败达到几次就整局拉黑这张卡
    _CARD_DEAD_AFTER: int = 3

    # 连续合成多少次判定棋盘已满（实测满盘后每轮都是合成）
    _MERGE_STREAK_FULL: int = 4
    # 升 1 级要累计几次合成 = **2**（用户 2026-10-25 确认；日志也印证：
    # (0,1) 石骑士「累计 1 次 → 1/3 级」「累计 2 次 → 2/3 级」，图上正好 LV.2）。
    _MERGES_PER_LEVEL: int = 2

    @classmethod
    def skip_buy(cls, card_name: str) -> None:
        """这张卡暂时别再试；连续失败太多次就**整局拉黑**。

        短期跳过用 _buy_skip（安静几轮后重试），避免一次偶发失败把好卡刷掉；
        但同一张卡反复失败说明状态确实对不上（典型：目标格已经 LV.3 而内部以为还能升），
        这时再重试只会无限循环 —— 实测 11:06 卡在「32126 → (1,3)」上每 4 秒一次、
        持续好几分钟。连续失败到 _CARD_DEAD_AFTER 就整局放弃它，新局复位。
        """
        fails = cls._buy_fails.get(card_name, 0) + 1
        cls._buy_fails[card_name] = fails
        if fails >= cls._CARD_DEAD_AFTER:
            if not cls.card_dead.get(card_name):
                logger.warning(f"{card_name} 连续 {fails} 次买/升失败，本局不再尝试（防止死循环）")
            cls.card_dead[card_name] = True
        cls._buy_skip[card_name] = cls._SKIP_TIMES

    @classmethod
    def clear_buy_fails(cls, card_name: str) -> None:
        """这张卡成功了一次 → 失败计数与拉黑状态一起清掉。"""
        cls._buy_fails.pop(card_name, None)
        cls.card_dead.pop(card_name, None)

    @classmethod
    def is_card_dead(cls, card_name: str) -> bool:
        """只读判断：这张卡本局是否已被拉黑（不消耗跳过额度）。

        奖励区分支要用它 —— 那边如果调 is_buy_skipped()（扣减式），
        会和商店分支各扣一次，额度消耗翻倍。
        """
        return bool(cls.card_dead.get(card_name))

    @classmethod
    def is_buy_skipped(cls, card_name: str) -> bool:
        """是否还要跳过这张卡；返回 True 时消耗一次额度。"""
        if cls.card_dead.get(card_name):
            return True
        left = cls._buy_skip.get(card_name)
        if left is None or left <= 0:
            return False
        cls._buy_skip[card_name] = left - 1
        return True

    @classmethod
    def reset_leader(cls) -> None:
        """进入新一局时复位领队（由 CCResetData / 开局流程调用）。"""
        cls.leader_id = None

    @classmethod
    def set_leader(cls, leader_id: str | None) -> None:
        """记录本局选中的领队（None = 兜底选了非优先棋手或未知）。

        只在**还没确定**时才写：一旦记到具体的领队 id，就不再被后续的
        「兜底 / 已选中」判定覆盖 —— 那些分支每轮都会重新问一次，
        反复覆写会让 leader_id 在同一秒内横跳（实测 21:12:55 连写 11 次）。
        """
        if leader_id is None and cls.leader_id is not None:
            return
        if cls.leader_id == leader_id:
            return
        cls.leader_id = leader_id
        logger.debug(f"本局领队记为 {leader_id or '未知（兜底/非优先棋手）'}")

    @classmethod
    def clear_leader(cls) -> None:
        """无条件清空领队记录（兜底选了别人时必须走这里）。

        set_leader(None) 有粘性保护（防止每轮重复判定把已知领队冲掉），
        所以「这一局真的兜底选了非优先棋手」需要显式清空 —— 否则会沿用上一局的
        30027 去开箱，把别人的贴纸塞进按小叶尼塞配置的贴纸位。
        """
        if cls.leader_id is not None:
            logger.debug(f"清空领队记录（原为 {cls.leader_id}）")
        cls.leader_id = None

    @classmethod
    def consume_reroll(cls, group: str, budget: int) -> bool:
        """按用途记账地消耗一次重摇额度；用完返回 False。

        机制（实机实测 2026-10-17，**推翻 4.0 改写时的旧结论**）：在**奇遇弹窗 / 选领队页**
        （还没点「进入战斗」）点左上返回，只是回到主菜单 —— 这一局还压着，再点「箱中对决」
        原样回到同一局（连摇 4 次都是同名奇遇「大鱼吃小鱼」，额度全白烧）。
        真正重摇要两步：**返回** 回主菜单 → 点「箱中对决」招牌右上角的 ✕（= 放弃当前这局，
        只在有未完成对局时出现）→ 清掉「此时放弃对战评分不变，是否确认？」→ 再点「箱中对决」，
        这时才是新奇遇（实测：大鱼吃小鱼 → 天外飞箱）。
        pipeline 侧由 `CCStop` + `CCRerollConfirm` 承担这两步；这里的额度仍然必须有 ——
        摇不到就继续走，绝不死端。
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
        """清空棋盘与**所有按局状态**（新对局时调用）。

        盘点过一次就漏一次，所以按局状态统一在这里复位：
        board_full / merge_streak / card_dead / _buy_fails。
        """
        cls.board = [[None] * cls.strategy.board_cols for _ in range(cls.strategy.board_rows)]
        cls.board_chesses = []
        cls.board_full = False
        cls.merge_streak = 0
        cls.card_dead = {}
        cls._buy_fails = {}
        return cls.board

    @classmethod
    def get_chess_info(cls, name: str) -> dict[str, Any]:
        """获取指定棋子的信息"""
        for chess in cls.chess_types:
            if chess["name"] == name:
                return chess
        return {}

    @classmethod
    def drop_cells_if_now_empty(cls, context: Context, img: Any, cells: list[tuple[int, int]]) -> int:
        """把「模型里有棋子、实际已经空了」的格清掉，返回清掉的格数。

        合成/升级时棋子会离开原来的格子：差分只能看到「这些格变了」，
        但分不清是「变空」还是「换了个棋子」。这里用「格子里是否还有非背景像素」
        做一次廉价判定 —— 空格是统一的爪印底纹，占用格会明显更亮/更杂。
        判不准时保留原状（宁可多留一条错误记录，也不要把真棋子删掉）。
        """
        removed = 0
        for row, col in cells:
            if not CCChessboard._is_valid_position(row, col):
                continue
            if cls.board[row][col] is None:
                continue
            roi = cls.board_rois[row][col]
            try:
                patch = img[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]]
            except Exception:  # noqa: BLE001 - 帧异常时保留原记录
                continue
            if patch.size == 0:
                continue
            # 复用「该格有没有棋子」的同一判据，不再维护第二个阈值。
            if not cls.is_cell_occupied(context, img, row, col):
                cls.board[row][col] = None
                cls.board_chesses = [
                    item for item in cls.board_chesses if not (item["row"] == row and item["col"] == col)
                ]
                removed += 1
        return removed

    @classmethod
    def record_chess(cls, row: int, col: int, name: str, level: int = 1) -> bool:
        """按实机看到的落点记账（不校验 positions）。

        4.0 买卡是「点开详情 → 点购买」，棋子由**游戏自己**落到第一个空位，
        落点不受策略表的 positions 约束（实测 32124 直接落到 row1，而 positions 里只有 row0/2）。
        所以这里只校验格子合法性，不做白名单校验。
        """
        if not cls._is_valid_position(row, col) or cls.board[row][col] is not None:
            return False
        entry: dict[str, Any] = {"name": name, "level": level, "row": row, "col": col}
        cls.board[row][col] = entry
        cls.board_chesses.append(entry)
        return True

    @classmethod
    def cell_diff(cls, before: Any, after: Any, row: int, col: int) -> float:
        """两帧之间某一格的平均像素差（用于判断拖拽是否真的生效）。"""
        roi = cls.board_rois[row][col]
        try:
            a = before[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]]
            b = after[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]]
        except Exception:  # noqa: BLE001 - 帧异常按无变化处理
            return 0.0
        if a.shape != b.shape or a.size == 0:
            return 0.0
        return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())

    @classmethod
    def _recognize_cell_card(cls, context: Context, img: Any, row: int, col: int) -> str | None:
        """识别某格里的棋子是哪张卡。

        **用 FeatureMatch 而不是 TemplateMatch**：棋盘上的棋子渲染尺寸与商店卡图不同
        （商店 83x65、棋盘约 1.6 倍），模板匹配对尺度敏感，调阈值救不了 ——
        实测所有 Cards/ 模板在棋盘格上最高只有 0.34 分。
        FeatureMatch 对尺度/旋转不敏感，正是这种场景该用的。

        都认不出就返回 None，调用方沿用内部记录。
        """
        roi = cls.board_rois[row][col]
        best: tuple[float, str] | None = None
        for name in cls.strategy.card_names():
            try:
                detail = context.run_recognition(
                    "CCCellCardFeature",
                    img,
                    {
                        "CCCellCardFeature": {
                            "template": f"CritterCrash/Cards/{name}.png",
                            "roi": roi,
                            "count": 1,
                            "ratio": 0.6,
                        }
                    },
                )
            except Exception:  # noqa: BLE001 - 识别异常按认不出处理
                continue
            if is_hit(detail) and detail.best_result is not None:
                # FeatureMatch 返回 BoxAndCountResult（只有 box / count），
                # TemplateMatch 返回带 score 的类型 —— 两者字段不同，
                # 直接取 .score 会 AttributeError（实测线上崩在 this line）。
                # 统一取「可比较的强度」：有 score 用 score，否则用 count。
                br = detail.best_result
                raw = getattr(br, "score", None)
                if raw is None:
                    raw = getattr(br, "count", 0)
                strength = float(raw)
                if best is None or strength > best[0]:
                    best = (strength, name)
        return best[1] if best is not None else None

    @classmethod
    def is_cell_occupied(cls, context: Context, img: Any, row: int, col: int) -> bool:
        """目标格里有没有棋子：用像素标准差判定。

        空格是统一的爪印底纹（实测 std≈29），放了棋子后明显更杂（std≈68）。
        阈值 45 取在两者中间，留足余量。
        """
        roi = cls.board_rois[row][col]
        try:
            patch = img[roi[1] : roi[1] + roi[3], roi[0] : roi[0] + roi[2]]
        except Exception:  # noqa: BLE001 - 帧异常时保守判为空
            return False
        if patch.size == 0:
            return False
        return float(patch.std()) >= cls._OCCUPIED_STD

    @classmethod
    def has_no_empty_cell(cls) -> bool:
        """内部棋盘是否一格空位都没有。

        棋盘满时继续买卡会让详情面板反复弹出又关不掉，挡住后续所有识别
        （实测 2026-10-24 多次卡到 4000）。买卡识别用它提前短路。
        """
        return all(cell is not None for row in cls.board for cell in row)

    @classmethod
    def find_card_on_board(cls, name: str) -> tuple[int, int] | None:
        """内部棋盘里找该卡的位置（用于升级目标）。"""
        for row in range(len(cls.board)):
            for col in range(len(cls.board[row])):
                cell = cls.board[row][col]
                if cell is not None and cell.get("name") == name:
                    return (row, col)
        return None

    @classmethod
    def place_chess(cls, row: int, col: int, name: str, level: int = 1) -> bool:
        """在指定位置放置棋子"""
        if not CCChessboard._is_valid_position(row, col):
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

        # board 与 board_chesses 必须共享同一个 dict：两处各造一个会让 level 分叉，
        # 表现为「升级成功后 can_upgrade_existing 仍为真」→ 反复升级同一格（实测连升 11 次）。
        entry: dict[str, Any] = {"name": name, "level": level, "row": row, "col": col}
        cls.board[row][col] = entry
        cls.board_chesses.append(entry)
        return True

    @classmethod
    def upgrade_chess(cls, row: int, col: int) -> bool:
        """升级指定位置的棋子"""
        if not CCChessboard._is_valid_position(row, col):
            return False

        chess = cls.board[row][col]
        if chess is None:
            return False

        name = chess["name"]
        if not isinstance(name, str):
            return False

        chess_info = cls.get_chess_info(name)
        cap = int(chess_info.get("max_level", 1))
        if int(chess["level"]) >= cap:
            return False  # 已达最高等级

        cls.apply_merge(chess)
        # board_chesses 与 board 共享同一 dict（见 place_chess），无需再同步
        return True

    @classmethod
    def apply_merge(cls, chess: dict[str, Any]) -> int:
        """记一次合成，返回合成后的等级。

        **两次合成升一级**（见 _MERGES_PER_LEVEL 注释）。merges 存在棋子 dict 里，
        跨回合保留；level 由 merges 推出来，不单独累加，避免两者分叉。
        """
        cap = int(cls.get_chess_info(str(chess["name"])).get("max_level", 1))
        merges = int(chess.get("merges", 0)) + 1
        chess["merges"] = merges
        chess["level"] = min(1 + merges // cls._MERGES_PER_LEVEL, cap)
        return int(chess["level"])

    @classmethod
    def remove_chess(cls, row: int, col: int) -> bool:
        """移除指定位置的棋子"""
        if not CCChessboard._is_valid_position(row, col):
            return False

        if cls.board[row][col] is None:
            return False

        cls.board[row][col] = None

        # 从board_chesses中移除
        cls.board_chesses = [item for item in cls.board_chesses if not (item["row"] == row and item["col"] == col)]

        return True

    @classmethod
    def find_empty_position_on_image(cls, context: Context, img: Any, name: str) -> tuple[int, int] | None:
        """按**实际画面**为指定棋子找一个空位置。

        为什么不复用 find_empty_position：那个只看内部棋盘，一次拖拽假成功就永久分叉 ——
        实测棋盘已满（所有格 std≈78）时它仍返回「有空位」，导致 CCBuyCardRec 每轮都命中、
        300s 内空转 173 次「买入 32123：没有可放置格」。
        """
        chess_info = cls.get_chess_info(name)
        if not chess_info:
            return None
        for row, col in chess_info.get("positions", []):
            if not cls._is_valid_position(row, col):
                continue
            if not cls.is_cell_occupied(context, img, row, col):
                return (row, col)
        return None

    @classmethod
    def find_empty_position(cls, name: str) -> tuple[int, int] | None:
        """为指定棋子找到一个空位置（**只看内部棋盘**，供单测/纯逻辑使用）"""
        chess_info = cls.get_chess_info(name)
        if not chess_info:
            return None

        for row, col in chess_info["positions"]:
            # 策略表越界已在 parse_strategy 拦下；这里再兜一层，避免手工注入的
            # chess_types（测试/热改）把 IndexError 抛进识别回调。
            if not CCChessboard._is_valid_position(row, col):
                continue
            if cls.board[row][col] is None:
                return (row, col)
        return None

    @classmethod
    def _is_valid_position(cls, row: int, col: int) -> bool:
        """检查位置是否有效"""
        return 0 <= row < len(cls.board) and 0 <= col < len(cls.board[0])

    @classmethod
    def find_sticker_position(cls) -> tuple[int, int] | None:
        """贴纸的空位：先按策略表给的优先位，再按行优先扫全盘。

        贴纸不走 find_empty_position —— 它的落点与具体卡名无关，
        而且优先位是「(1,1) 这种棋盘中部」，不是卡牌白名单的顺序。
        """
        strategy = cls.strategy
        sticker = strategy.sticker
        preferred: tuple[tuple[int, int], ...] = sticker.positions if sticker is not None else ()
        for row, col in preferred:
            if cls._is_valid_position(row, col) and cls.board[row][col] is None:
                return (row, col)
        for row in range(len(cls.board)):
            for col in range(len(cls.board[0])):
                if cls.board[row][col] is None:
                    return (row, col)
        return None

    @classmethod
    def can_upgrade_existing(cls, card_name: str) -> bool:
        """检查是否有现有棋子可以升级"""
        chess_info = cls.get_chess_info(card_name)
        if not chess_info:
            return False

        max_level = chess_info["max_level"]
        for chess in cls.board_chesses:
            if chess["name"] != card_name:
                continue
            # **用 level 字段判断，和 _pick_target_cell 保持同一口径**。
            # 之前这里用 merges 反推、那边用 level，一旦某个分支只更新了其中一个
            # （比如满级检测只写 level），两边就会打架：reco 一直推这张卡、
            # action 每次都说没位置 → 每秒一次的死循环。
            if int(chess.get("level", 1)) < max_level:
                return True
        return False

    def _reset_if_new_game(self, context: Context) -> None:
        """检测新对局并清空所有**按局状态**。

        **不用回合数**：CCRoundRec 的 OCR 实测读不到（框架日志里 hit 恒 false），
        改 expected、改 roi 都没救回来 —— 全天日志里「检测到新对局」0 次，
        于是 board_full / merge_streak / card_dead 这些按局状态全部跨局残留。

        **改用棋盘状态**：新一局开始时棋盘必定是空的，而内部棋盘还记着上一局的棋子。
        「内部有棋子 + 画面全空」就是换局了，这个信号不依赖任何 OCR。
        """
        try:
            img = context.tasker.controller.post_screencap().wait().get()
        except Exception as e:  # noqa: BLE001 - 取帧失败不该拖垮主循环
            logger.warning(f"新局检测取帧失败: {e}")
            return

        board = type(self).board
        internal_has_piece = any(cell is not None for row in board for cell in row)
        if not internal_has_piece:
            # 内部本来就是空的，没有可清的
            return

        actual_occupied = 0
        for row in range(len(board)):
            for col in range(len(board[row])):
                if row >= len(type(self).board_rois) or col >= len(type(self).board_rois[row]):
                    continue
                if type(self).is_cell_occupied(context, img, row, col):
                    actual_occupied += 1
                    break
            if actual_occupied:
                break

        if actual_occupied == 0:
            logger.debug("内部棋盘有棋子但画面全空 → 检测到新对局，清空按局状态")
            type(self).board_reset()
            type(self)._buy_skip = {}
            type(self).reset_rerolls()
            # 不要清领队：领队是玩家账号级的选择，新开一局通常沿用同一位，
            # 而「选领队」页不一定每次都出现（实测连续几局都没有该页 → leader_id 恒 None
            # → 贴纸被门控挡住，日志刷「本局领队是 未知/兜底」）。
            # 只有任务入口（CCResetData）才复位，跨局沿用上一次确认到的领队。
            CCSticker.reset()

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
        # 3) 检测新对局：回合数变小就清空内部棋盘（详见 _last_round 注释）。
        self._reset_if_new_game(context)

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

    # 点开卡片到详情面板出现的等待（秒）
    _BUY_PANEL_WAIT = 0.9
    # 点「购买」后落子动画/结算的等待（秒）
    _BUY_SETTLE = 1.2
    # 详情面板里「购买」按钮的位置（实测 940,568；面板居中、布局固定）
    _BUY_BUTTON_POINT = (940, 568)
    # 买卡前后「落子格」的最小平均像素差；空位底纹会有轻微抖动，取 6 足够区分
    _PIECE_DIFF_MIN = 6.0

    @staticmethod
    def _close_card_panel(context: Context) -> None:
        """关掉卡牌详情面板（ESC 优先，失败回退点击）。

        Python binding 只有 post_click_key（没有 post_key）；写错会抛 AttributeError
        被吞掉，然后静默回退到无效的点击 —— 面板关不掉，后续识别全被遮挡。
        """
        # post_click_key(111) 实测无效：发了 40 次、面板 40 次都还在（13:11 那轮日志）。
        # 改用 key_down + key_up 的显式按下/抬起（Android 上更接近物理键）。
        try:
            context.tasker.controller.post_key_down(111).wait()
            time.sleep(0.05)
            context.tasker.controller.post_key_up(111).wait()
            logger.debug("已发 ESC(111) 关面板")
        except Exception as e:  # noqa: BLE001 - 关面板失败不该中断买卡流程
            logger.warning(f"发 ESC 关面板失败（{e}），改用点击兜底")
            context.tasker.controller.post_click(*DEFAULT_PANEL_CLOSE_POINT).wait()
        time.sleep(0.6)
        # 关完复查：面板还在就说明 ESC 没生效，记录下来便于定位
        try:
            img = context.tasker.controller.post_screencap().wait().get()
            still = context.run_recognition(
                "CCPanelArrowRec",
                img,
                {"CCPanelArrowRec": {"template": "CritterCrash/PanelArrow.png", "roi": [980, 250, 120, 100]}},
            )
            if is_hit(still):
                logger.warning("ESC 后卡牌详情面板仍在（PanelArrow 仍命中）")
        except Exception:  # noqa: BLE001 - 复查失败不影响主流程
            pass

    @classmethod
    def _pick_target_cell(
        cls,
        card_name: str,
        context: Context,
        img: Any,
        *,
        upgrade: bool = False,
    ) -> tuple[int, int]:
        """选落点。策略（用户 2026-10-24 明确）：

        **优先占地盘，占满对应可占的格之后才升级。**

        - 巡城兵与鹿蜀位置一致（row0 → row2 交替）；石骑士专属位 (0,1)/(2,1) 不在其它卡的
          positions 里，所以不会被占。
        - upgrade=True 时**先试空格**：只要这张卡还有可占的空格，就继续铺新棋子。
        - 只有空格全占完，才找「已有同名棋子且未满级」的格去合成升级。

        **空格判定必须看实际画面，不能只信内部棋盘。**
        内部记录是从「买到什么」推出来的，一次假成功就永久分叉 ——
        实测 (0,2) 明明有鹿蜀、内部却记成空，于是巡城兵连续十几次都拖到 (0,2)，
        游戏弹「棋子放置到错误区域」（巡城兵不能放到鹿蜀上）。

        为什么不能直接点购买：游戏会自动落到第一个空位，不看这张卡该占哪，
        会把石骑士的专属位也占掉；而且满盘后无法再点购买升级。拖拽能精确控制落点。
        """
        info = CCChessboard.get_chess_info(card_name)
        cap = int(info.get("max_level", 3))

        # 辅助卡（single_slot）：棋盘上只留 1 个，之后一律拖到它身上合成升级。
        # 必须**先判已有同名棋子**再找空格，否则会把第二张放到新格上、
        # 变成占两格（用户明确「没必要占俩位置」）。
        if info.get("single_slot"):
            # 在**整个棋盘**上找同名棋子，不能只看 positions ——
            # 棋子可能在 positions 之外（贴纸位、拖错位等），只看 positions 会找不到、
            # 返回 (-1,-1)；而 reco 侧的 can_upgrade_existing 遍历的是 board_chesses，
            # 于是两边判断打架：reco 一直推这张卡、action 每次都说没位置 →
            # 每秒一次死循环（实测 11:53 连刷十几秒，日志只有两行反复出现）。
            for row in range(len(CCChessboard.board)):
                for col in range(len(CCChessboard.board[row])):
                    if not CCChessboard._is_valid_position(row, col):
                        continue
                    cell = CCChessboard.board[row][col]
                    if cell is None or cell.get("name") != card_name:
                        continue
                    # 找到同名棋子：没满级就拖上去合成，满了就**不再买**。
                    # 不能落到下面的「找空格」—— 那样棋盘上会出现第二个同名辅助卡。
                    # （两个 review bot 独立指出了这一点。）
                    if int(cell.get("level", 1)) < cap:
                        return (row, col)
                    logger.debug(f"{card_name} 已满级（{cap}），single_slot 只留 1 个，本次不买")
                    return (-1, -1)

        # 1) 先占地盘：positions 里第一个**实际为空**的格
        for row, col in info.get("positions", []):
            if not CCChessboard._is_valid_position(row, col):
                continue
            if CCChessboard.is_cell_occupied(context, img, row, col):
                # 实际有棋子（可能是别的卡）→ 跳过，别往上面拖
                continue
            return (row, col)

        # 2) 地盘占满了才升级：找已有同名且未满级的格
        if upgrade:
            for row, col in info.get("positions", []):
                if not CCChessboard._is_valid_position(row, col):
                    continue
                cell = CCChessboard.board[row][col]
                if cell is not None and cell.get("name") == card_name and int(cell.get("level", 1)) < cap:
                    return (row, col)
        return (-1, -1)

    @staticmethod
    def _diff_changed_cells(pre: Any, post: Any) -> list[tuple[float, int, int]]:
        """买卡前后两帧里所有发生变化的棋盘格，按变化量降序。

        为什么用差分而不是模板匹配：商店卡图和棋盘上的棋子渲染尺寸、叠加的 LV 角标
        都不一样，Cards/<id>.png 在棋盘格 ROI 上命中率极低（实测三格全 miss）。
        差分只要求「那一格变了」，与渲染差异无关。

        返回**全部**变化格而不是只取最大的一格：合成/升级会把棋子从一格挪走并抬高另一格，
        一次购买可能同时改动 2~3 格，只看一格会让内部棋盘越走越偏
        （实测出现「买入 32123 落到 (0,2)，但该格记的是 32122」这种分叉）。
        """
        board = CCChessboard.board
        rois = CCChessboard.board_rois
        changed: list[tuple[float, int, int]] = []
        for row in range(len(board)):
            for col in range(len(board[row])):
                if row >= len(rois) or col >= len(rois[row]):
                    continue
                x, y, w, h = rois[row][col]
                try:
                    a = pre[y : y + h, x : x + w]
                    b = post[y : y + h, x : x + w]
                except Exception:  # noqa: BLE001 - 帧尺寸异常时跳过该格
                    continue
                if a.shape != b.shape or a.size == 0:
                    continue
                diff = float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())
                if diff >= CCBuyCard._PIECE_DIFF_MIN:
                    changed.append((diff, row, col))
        changed.sort(reverse=True)
        return changed

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

        if action in (0, 1):
            # 4.0 买卡：**从商店拖到目标格**（不是点购买）。
            #
            # 直接点「购买」也能买到，但棋子由游戏自动落到第一个空位 ——
            # 那会把棋盘从左到右填满、占掉石骑士该占的位置，且满盘后无法再点购买升级。
            # 拖拽可以精确控制落点：实测从商店卡 (430,640) 拖到棋盘 (0,1) 中心 (496,197)，
            # 卡精确落在 (0,1)、金币 3→0、商店那张消失。
            #
            # 手势要点：必须带中途路径点（--via 等价物）。纯两点 swipe 不会触发拖拽
            # （之前「拖拽无效」的结论就是漏了这一步）。
            pick_img = context.tasker.controller.post_screencap().wait().get()
            row, col = self._pick_target_cell(card_name, context, pick_img, upgrade=(action == 1))
            if (row, col) == (-1, -1):
                logger.debug(f"买入 {card_name}：没有可放置格，本局跳过")
                # **整局拉黑**，不能只 skip 几轮：reco 侧的判断如果和这里不一致，
                # skip 恢复后又会把同一张卡推回来，变成每秒一次的死循环
                # （实测 11:53 日志只有「已满级」+「没有可放置格」两行反复刷）。
                CCChessboard.card_dead[card_name] = True
                CCChessboard.skip_buy(card_name)
                return CustomAction.RunResult(success=True)

            target_roi = CCChessboard.board_rois[row][col]
            tx = target_roi[0] + target_roi[2] // 2
            ty = target_roi[1] + target_roi[3] // 2
            sx = box[0] + box[2] // 2
            sy = box[1] + box[3] // 2

            logger.debug(f"拖拽 {card_name} 从 ({sx},{sy}) 到 ({row},{col}) 中心 ({tx},{ty})")

            # 拖拽**前**先记下目标格是否已有棋子：
            # 只判「拖完该格有棋子」是不够的 —— 那格本来就有别的棋子（比如鹿蜀）时，
            # 会误判成「拖入成功」，把内部棋盘记成新卡、实际画面完全没变
            # （实测 32124 拖了 8 次全报成功，画面里一次都没上去）。
            pre_img = context.tasker.controller.post_screencap().wait().get()
            was_occupied = CCChessboard.is_cell_occupied(context, pre_img, row, col)

            # 必须用 touch_down → 多次 touch_move → touch_up：
            # Controller.post_swipe 只支持两点，纯两点手势不会触发游戏里的拖拽
            # （实测卡一动不动）。带中途点的按下-移动-抬起才有效。
            # 手势时序要足够慢、插值要足够密：
            #
            # 原来只有 4 步、每步 80ms。从商店 (600,620) 拖到 (496,197) 时，
            # step3 = (522,302) 距 (1,1) 中心 (482,308) 只有 40px ——
            # 一旦这一步的 touch_move 没被游戏采样到、或者提前松手，
            # 卡就落到 (1,1) 而不是目标格（实测出现过「第一轮拖 (0,1) 落到 (1,1)」）。
            #
            # 现在：16 步 × 25ms ≈ 400ms 连续移动 + 到点后停留 200ms 再抬手。
            ctrl = context.tasker.controller
            ctrl.post_touch_down(sx, sy).wait()
            time.sleep(0.20)

            steps = 16
            for step in range(1, steps + 1):
                mx = sx + (tx - sx) * step // steps
                my = sy + (ty - sy) * step // steps
                ctrl.post_touch_move(mx, my).wait()
                time.sleep(0.025)

            # 到点后**停留一下再抬手**：让游戏确认落点，
            # 否则最后一帧还没渲染完就松手，会判定成上一步的位置。
            time.sleep(0.20)
            ctrl.post_touch_up().wait()
            time.sleep(self._BUY_SETTLE)

            img = context.tasker.controller.post_screencap().wait().get()

            # 落点判据：**只看我们拖向的那一格**，不用「变化最大格」猜。
            # 差分在这张界面上不可靠：贴纸箱 (0,0) 有开箱动画、拖拽路径也会扫过棋盘，
            # 变化最大的常常是 (0,0) 而不是真正的落点 ——
            # 实测拖到 (0,1)、棋子确实落在 (0,1)（ROI 叠加核对过），
            # 但差分包报「拖入到 (0,0)」，导致内部棋盘与实际分叉。
            # 拖拽后棋子可能还在落位动画里：连判两次（间隔 0.6s），两次都占用才算真的落下。
            # 只判一次会把「拖拽失败但棋子短暂悬停」误判成成功 ——
            # 实测日志说拖入 (0,3)/(0,4)/(0,5)，实际那三格全空，内部棋盘与实际分叉。
            occupied = CCChessboard.is_cell_occupied(context, img, row, col)
            img2 = img
            if occupied:
                time.sleep(0.6)
                img2 = context.tasker.controller.post_screencap().wait().get()
                occupied = CCChessboard.is_cell_occupied(context, img2, row, col)

            # 目标格原本就有棋子时，拖拽成功必须体现为**画面变化**（卡种/等级变了）。
            # 只判「有棋子」会把「拖拽完全没生效」也算成功 —— 这是 32124 连续 8 次
            # 假成功、内部棋盘与画面彻底分叉的直接原因。
            # **先查「棋子等级已满」弹窗** —— 这是判满级最可靠的信号。
            #
            # 不能用格子 roi 内的像素差：弹窗在右上角、不在 roi 里，合成被拒时
            # roi 内 diff 恒为 0.0（实测就是精确的 0）。也不能靠 Lv3.png 模板：
            # 全屏搜一帧 NCC=1.0 只有 1 处，棋盘上其它 LV.3 全部匹配不上。
            # 而这个弹窗 OCR 稳定命中（text="棋子等级已满"）。
            if is_hit(context.run_recognition("CCLevelMaxPopup", img2)):
                target = CCChessboard.board[row][col]
                if target is not None and target.get("name") == card_name:
                    cap = int(CCChessboard.get_chess_info(card_name).get("max_level", 3))
                    target["level"] = cap
                    target["merges"] = cap * CCChessboard._MERGES_PER_LEVEL
                logger.debug(f"{card_name} 在 ({row}, {col}) 合成被拒：游戏弹「棋子等级已满」→ 记该格满级")
                # 关掉提示，免得挡住后续识别（点棋盘外空白处）
                context.tasker.controller.post_click(*DEFAULT_PANEL_CLOSE_POINT).wait()
                time.sleep(0.4)
                CCChessboard.skip_buy(card_name)
                return CustomAction.RunResult(success=True)

            if was_occupied and occupied:
                diff = CCChessboard.cell_diff(pre_img, img2, row, col)
                if diff < CCChessboard._CELL_CHANGE_MIN:
                    # **这里绝不能推断「已满级」**：满级只由上面的 CCLevelMaxPopup 判定。
                    # 能走到这里说明弹窗没命中；而「拖拽完全没生效」本身非常常见
                    # （本函数上面就记着 32124 连续 8 次假成功）。真要是在这里把目标格
                    # 写成 level=cap，一次失败拖拽就会让一颗没满级的棋子本局再也升不上去
                    # —— 对 single_slot 卡还会直接变成 (-1,-1) 然后被 skip/拉黑。
                    logger.debug(
                        f"拖拽 {card_name} 到 ({row}, {col}) 后该格画面无变化（diff={diff:.1f}），判定拖拽未生效"
                    )
                    CCChessboard.skip_buy(card_name)
                    return CustomAction.RunResult(success=True)

            if not occupied:
                logger.debug(f"拖拽 {card_name} 到 ({row}, {col}) 后该格仍为空，本回合跳过该卡")
                CCChessboard.skip_buy(card_name)
                return CustomAction.RunResult(success=True)

            got_row, got_col = row, col
            # 拖拽后**必须确认这一格里的卡种就是拖进去的那张**。
            #
            # 只判「画面变了」不够：拖巡城兵到已有鹿蜀的格上时，游戏可能合成/拒绝，
            # 画面确实变了、但那格里不是巡城兵 —— 实测 32122 连续 4 次拖到 (0,2)
            # 都报成功，而画面里 (0,2) 一直是鹿蜀 LV.2。
            actual = CCChessboard._recognize_cell_card(context, img2, got_row, got_col)
            if actual is not None and actual != card_name:
                # 允许「合到同名棋子」：目标是同名卡时，拖进去本来就该是它
                logger.debug(
                    f"拖拽 {card_name} 到 ({got_row}, {got_col}) 后该格实际是 {actual}，不是目标卡，判定拖拽未生效"
                )
                CCChessboard.skip_buy(card_name)
                return CustomAction.RunResult(success=True)
            existing = CCChessboard.board[got_row][got_col]

            # 认出来了就**一律按实际校正**内部记录（不管认出的卡是不是我们要拖的那张）。
            # 之前只在「认出的 ≠ 内部记的」时才校正，于是 actual == card_name 时不动内部记录 ——
            # 而内部记录可能是错的（记着别的卡），后面 existing.get("name") == card_name 就不成立，
            # 走「落到但该格记的是 X，跳过」，既没记成功也没记失败，日志里看不出发生了什么
            # （实测 6 次拖拽只有 1 次有后续日志）。
            # **同名同格时绝对不要重建 dict**：重建会把 merges 一起丢掉，
            # 于是 apply_merge 每次都从 0 开始算 → 永远停在「累计 1 次合成 → 1/3 级」，
            # 实测 10:37 连续 6 次合到 (0,2) 全部报「累计 1 次 → 1/3 级」，永远升不到 2 级。
            if actual is not None and (existing is None or existing.get("name") != actual):
                logger.debug(
                    f"({got_row}, {got_col}) 内部记的是 {existing.get('name') if existing else '空'}"
                    f"，实际识别为 {actual}，按实际校正"
                )
                entry: dict[str, Any] = {
                    "name": actual,
                    "level": 1,  # 不认识原来的等级，从 1 起算
                    "merges": 0,  # 合成次数也跟着归零，避免拿别的卡的进度
                    "row": got_row,
                    "col": got_col,
                }
                CCChessboard.board[got_row][got_col] = entry
                CCChessboard.board_chesses = [
                    x for x in CCChessboard.board_chesses if not (x["row"] == got_row and x["col"] == got_col)
                ]
                CCChessboard.board_chesses.append(entry)
                existing = entry

            if existing is not None:
                if existing.get("name") == card_name:
                    cap = int(CCChessboard.get_chess_info(card_name).get("max_level", 3))
                    new_level = CCChessboard.apply_merge(existing)
                    merges = int(existing.get("merges", 0))
                    CCChessboard.clear_buy_fails(card_name)
                    logger.debug(
                        f"{card_name} 合到 ({got_row}, {got_col})，累计 {merges} 次合成 → {new_level}/{cap} 级"
                    )
                    # 合成会同时改动别的格（被吃掉的那颗消失、或整行重排）。
                    # 只记目标格会让模型里留下幻影棋子，之后 find_empty_position
                    # 一直说没空位、实际还有。这里把其它变化格里已经变空的清掉。
                    others = [
                        (r, c) for _, r, c in self._diff_changed_cells(pre_img, img2) if (r, c) != (got_row, got_col)
                    ]
                    if others:
                        removed = CCChessboard.drop_cells_if_now_empty(context, img2, others)
                        if removed:
                            logger.debug(f"{card_name} 合成带走了 {removed} 个格，已从模型清掉")
                    return CustomAction.RunResult(success=True)
                logger.debug(f"{card_name} 落到 ({got_row}, {got_col})，但该格记的是 {existing.get('name')}，跳过")
                CCChessboard.skip_buy(card_name)
                return CustomAction.RunResult(success=True)

            if CCChessboard.record_chess(got_row, got_col, card_name):
                CCChessboard.clear_buy_fails(card_name)
                logger.debug(f"拖入 {card_name} 到 ({got_row}, {got_col})")
                return CustomAction.RunResult(success=True)
            # 以前这里是静默 return，导致「拖拽了但什么都没发生」在日志里查不到 ——
            # 实测 5 次拖拽有 4 次完全没有后续日志。
            logger.warning(
                f"拖拽 {card_name} 到 ({got_row}, {got_col})：画面已占用但内部记录为空/非法，"
                f"record_chess 失败（actual={actual}, existing={existing}）"
            )
            CCChessboard.skip_buy(card_name)
            return CustomAction.RunResult(success=True)

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
        CCSticker.reset()
        CCChessboard.reset_leader()

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CCSticker")
class CCSticker(CustomAction):
    """
    翻斗棋：专属贴纸箱（4.0 每局一个，位置固定在左列上格）。

    实测规则（.live/acc/STICKER-FINDINGS.md）：
    - 盒子在棋盘 (0,0)，点一下弹道具面板；面板写「N 回合后可开箱」，
      实测 N = open_round - 当前回合，即当前回合 >= open_round 才点得开；
    - 开箱后贴纸进奖励区最左槽，拖到空位即上场；
    - 贴纸按角色独有，小叶尼塞第 open_round 回合可用。

    本 action 只做「开箱 + 拖到空位」，不判断回合——回合门槛由 pipeline 的
    识别节点（CCStickerReady）保证；这里再兜一层：点开后若弹的是道具面板
    （说明还没到回合），关掉面板并如实返回 False，不假装成功。
    """

    # 开箱后轮询盒子是否消失：面板动画期间单帧仍会命中，必须多等几帧。
    # 实测 3.2s 不够（12:08:55 判成「未开」，但当时箱子其实已开、画面里 (0,0) 已是三角格），
    # 放宽到 12 × 0.5s = 6s。
    _OPEN_POLL_TIMES = 12
    _OPEN_POLL_INTERVAL = 0.5

    # 本局是否已经开过箱（开过就不再重复点，避免每回合空转）
    _opened = False
    # 上次确认"开不了"的回合号；同一回合内不再重复点盒子
    _failed_round: int | None = None

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        strategy = CCChessboard.strategy
        sticker = strategy.sticker
        if sticker is None:
            logger.debug("策略表未启用贴纸流程，跳过")
            return CustomAction.RunResult(success=True)

        if CCSticker._opened:
            # 必须返回 True。框架语义（PipelineTask.cpp:68-75）是：
            #   动作成功 → 轮询 node.next；动作失败 → 走 node.on_error（**不**回溯父列表）。
            # 本节点以 [JumpBack] 挂载且没有 on_error，返回 False 会让 next 为空、
            # 任务直接以 4000 收场（实测：贴纸跳过那一步就成了最后一个节点）。
            # 防空转靠识别层：盒子开掉后模板不再命中，本节点自然 miss。
            logger.debug("本局贴纸箱已开过，跳过")
            return CustomAction.RunResult(success=True)

        # 贴纸按角色独有：只有本局领队就是配置的那位才开。兜底选了别人时
        # CCChessboard.leader_id 为 None，这里直接跳过。
        if sticker.leader and CCChessboard.leader_id != sticker.leader:
            logger.debug(
                f"本局领队是 {CCChessboard.leader_id or '未知/兜底'}，不是贴纸归属的小叶尼塞 {sticker.leader}，不开箱"
            )
            # 置 _opened：本局不再检查。
            #
            # 之前不置位是想「领队后来变对了还能开」，但领队一旦在本局定了就不会变，
            # 而不置位的后果是 —— 箱子还在画面上，识别每轮都命中，主循环反复选中本节点，
            # 实测 300s 内空转 312 次，把买卡/开战全挤掉了（14:03 那轮买入 0 次）。
            # 新局由 _reset_if_new_game 复位，不影响下一局。
            CCSticker._opened = True
            return CustomAction.RunResult(success=True)  # 失败会终结任务，见上方注释

        # 门控：盒子还在才处理。盒子开掉后该格变成三角格，模板不再命中——
        # 这条比「第 N 回合」可靠：面板自己写着「品质越高，开启所需回合越长」，
        # 实测同一角色不同局有 2 回合与 5 回合两种，写死回合数必错。
        img_now = context.tasker.controller.post_screencap().wait().get()
        box_reco = context.run_recognition(
            "CCStickerBoxTemplate",
            img_now,
            {"CCStickerBoxTemplate": {"template": "CritterCrash/StickerBox.png", "roi": [280, 120, 200, 200]}},
        )
        if not is_hit(box_reco):
            logger.debug("贴纸箱不在（本局已开过或尚未出现），跳过")
            CCSticker._opened = True
            return CustomAction.RunResult(success=True)

        # 同一个回合里只尝试一次：还没到可开回合时点盒子只会弹道具面板，
        # 而主循环每轮都会走到这里 —— 不设防就会每回合点一遍，把买卡挤掉（实测 CCDeploy=0）。
        current_round = self._read_round(context, img_now)
        if current_round is not None and CCSticker._failed_round == current_round:
            logger.debug(f"第 {current_round} 回合已确认开不了贴纸箱，本回合不再尝试")
            return CustomAction.RunResult(success=True)

        # 回合门控：open_round 是**已知下限**（小叶尼塞固定第 2 回合），
        # 回合没到就别点 —— 点了只会弹「N 回合后可开箱」面板，然后白轮询 6 秒确认没开，
        # 实测第 1 回合那次点了箱子后卡 8.2 秒（17:44:43 → 17:44:51）。
        # 领队换人时 open_round 会变（实测另一角色是 5），但配置里写的就是当前领队的值。
        if sticker.open_round and current_round is not None and current_round < sticker.open_round:
            logger.debug(f"第 {current_round} 回合，贴纸箱要第 {sticker.open_round} 回合才开，本回合不点")
            CCSticker._failed_round = current_round
            return CustomAction.RunResult(success=True)

        # 点盒子中心，但**必须用点击前那一刻的识别框**：
        # 上面的 box_reco 是几秒前（读回合数、算 ROI 期间）识别的，界面在这期间会轻微位移，
        # 拿旧框中心点下去会落到箱子外（实测旧框中心 (380,220) vs 实际中心 (360,202)，
        # 偏 20px 正好在边缘外，点了等于没点 —— 这就是「贴纸箱未开」反复出现的真因）。
        img_click = context.tasker.controller.post_screencap().wait().get()
        box_now = context.run_recognition(
            "CCStickerBoxTemplate",
            img_click,
            {"CCStickerBoxTemplate": {"template": "CritterCrash/StickerBox.png", "roi": [280, 120, 200, 200]}},
        )
        box = box_now.box if is_hit(box_now) else box_reco.box
        if box is not None:
            point = (int(box.x + box.w // 2), int(box.y + box.h // 2))
        else:
            point = sticker.point()
        logger.debug(f"点贴纸箱 {point}（识别框 {box}）")
        context.tasker.controller.post_click(point[0], point[1]).wait()
        time.sleep(0.9)

        # 点完必须重新截图再判：cached_image 是上一轮的缓存，
        # 不等 post_* 完成就取会拿到点之前的画面（实测踩过：误判成"没开箱"）。
        # 判据只看**盒子模板是否消失** —— 不能用「奖励区是否为空」：
        # 开箱前奖励区本来就可能有别的卡（实测有两张黑猫），那条判据会误判成已开。
        #
        # 但**不能只看一帧**：开箱后面板弹出有动画，单帧截图里盒子模板仍会命中，
        # 于是误判成「回合没到」→ 关面板走人，而盒子其实已经开了、贴纸留在奖励区
        # （实测 01:25:54 就是这样：日志说没开，两分钟后画面里 (0,0) 早变成三角格、
        #  奖励区躺着一张鸟形贴纸）。改成轮询等它消失。
        opened = False
        for _ in range(self._OPEN_POLL_TIMES):
            img = context.tasker.controller.post_screencap().wait().get()
            box_after = context.run_recognition(
                "CCStickerBoxTemplate",
                img,
                {"CCStickerBoxTemplate": {"template": "CritterCrash/StickerBox.png", "roi": [280, 120, 200, 200]}},
            )
            if not is_hit(box_after):
                opened = True
                break
            time.sleep(self._OPEN_POLL_INTERVAL)
        if not opened:
            # 盒子还在：还没到可开回合，弹的是道具面板——关掉它。
            # 只记「本回合」已确认开不了，**下一回合还要再试**：open_round 是下限，
            # 不是精确值（实测同一领队不同局有 2 与 5 两种）。
            logger.debug(f"贴纸箱未开（第 {current_round} 回合 / 该领队需第 {sticker.open_round} 回合），关闭面板")
            context.tasker.controller.post_click(*DEFAULT_PANEL_CLOSE_POINT).wait()
            time.sleep(0.5)
            CCSticker._failed_round = current_round
            return CustomAction.RunResult(success=True)

        CCSticker._opened = True
        logger.debug("贴纸箱已开，贴纸进入奖励区")

        # 贴纸的上场方式与买卡一致：**点奖励区里的贴纸 → 弹详情面板 → 点右下角按钮**
        # （贴纸显示「免费」）→ 游戏自动落到棋盘空位。
        # 拖拽（post_swipe / 带 --via 的按住拖）实测都无效：奖励区那张卡纹丝不动，
        # 只有点开面板再点按钮才会真的上场（实测 2026-10-23 04:2x）。
        src = self._sticker_source_point(context)
        context.tasker.controller.post_click(src[0], src[1]).wait()
        time.sleep(CCBuyCard._BUY_PANEL_WAIT)
        context.tasker.controller.post_click(*CCBuyCard._BUY_BUTTON_POINT).wait()
        time.sleep(CCBuyCard._BUY_SETTLE)

        # 判据：奖励区变空 = 贴纸上场。
        #
        # 注意 CCBuyCardAwardEmptyRec 的语义是 **NOT 空模板 AND 在对局页**，
        # 即「命中 = 奖励区**有卡**」（CCBuyCardRec.analyze 也是这么用的）。
        # 所以上场成功对应的是 **not is_hit**，写成 is_hit 会把成功当失败。
        img_after = context.tasker.controller.post_screencap().wait().get()
        has_award = context.run_recognition("CCBuyCardAwardEmptyRec", img_after)
        if not is_hit(has_award):
            logger.debug("贴纸已上场（奖励区已空）")
            return CustomAction.RunResult(success=True)

        # 面板可能没点中：关掉它，贴纸留给下一轮
        context.tasker.controller.post_click(*DEFAULT_PANEL_CLOSE_POINT).wait()
        time.sleep(0.4)
        logger.debug("贴纸点击后仍在奖励区，关闭面板，下一轮再试")
        return CustomAction.RunResult(success=True)

    @staticmethod
    def _read_round(context: Context, img: Any) -> int | None:
        """读对局页右侧的回合数「n/12」（roi 实测 1160,415,120,50），返回 n。

        之前用 CCRemainMoney_rec_refresh 是错的 —— 那读的是**金币**（roi 669,29 左上角），
        拿它当回合数会让守卫恒为 None，于是每轮都重点一次盒子（实测空转 122 次）。
        """
        # 一律走 CCRoundPre。它的 roi 2026-10-25 已从 1172,419,77,30 改成
        # 1160,415,120,50：实测旧 roi（更窄）完全读不到，新 roi 能读到 "8"。
        # 注意 OCR 有时只回 "8"、有时回 "8/12"，所以 CCnRound 的 expected 两种都要认 ——
        # 之前只写 ^[0-9]{1,2}\/12$，导致币/回合两个条件轮流失败，
        # 全天日志「检测到新对局」出现 0 次、按局状态跨局残留。
        #
        # 另外：_reset_if_new_game 现在**不再依赖回合数**（改用棋盘状态判断），
        # 这个函数只用于贴纸箱的「同回合去重」。
        try:
            detail = context.run_recognition("CCRoundPre", img)
        except Exception:  # noqa: BLE001 - 回合数只用于去重，读不到不算失败
            return None
        if not is_hit(detail):
            return None
        text = ocr_text(detail)
        # OCR 结果形如 "1/12"：取斜杠前的第一个连续数字
        head = text.split("/")[0]
        digits = "".join(ch for ch in head if ch.isdigit())
        return int(digits) if digits else None

    @staticmethod
    def _sticker_source_point(context: Context) -> tuple[int, int]:
        """奖励区里贴纸卡的点击点。

        奖励区只有一格（roi 42,580,128,124），贴纸就落在那里 —— 直接取格中心。
        """
        return AWARD_SLOT_CENTER

    @staticmethod
    def _award_slots(context: Context) -> int:
        """数奖励区当前有几张卡（用于区分「开箱前就有卡」与「开箱后多了一张」）。

        做法：按策略表的卡名逐个模板匹配奖励区 ROI，命中即算一张。
        只用于「开箱是否生效」的相对判断，不作为业务状态来源。
        """
        try:
            img = context.tasker.controller.post_screencap().wait().get()
        except Exception as e:  # noqa: BLE001 - 截图失败不该让 action 抛出去
            logger.debug(f"贴纸：取奖励区截图失败（{e}），按 0 张处理")
            return 0
        count = 0
        for name in CCChessboard.strategy.card_names():
            try:
                detail = context.run_recognition(
                    "CCBuyCardAwardRec_Template",
                    img,
                    {"CCBuyCardAwardRec_Template": {"template": f"CritterCrash/Cards/{name}.png"}},
                )
            except Exception:  # noqa: BLE001 - 识别异常不阻断贴纸流程
                continue
            if is_hit(detail):
                count += 1
        return count

    @classmethod
    def reset(cls) -> None:
        """每局开始重置「已开箱」标记。"""
        cls._opened = False
        cls._failed_round = None
