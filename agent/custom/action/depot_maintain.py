"""库存保持：按目标库存把材料补到目标量。

决策链：材料目录（data/combat/balanced_farming.json）→ 目标库存（GUI 逐材料数字框）
→ 仓库快照（config/warehouse_inventory.json）→ 挑缺口最大的材料 → 交给 Combat 刷取。

- 所有目标库存都为 0（默认）时本动作不生效，任务退回原有「均衡取最少」流程，老配置行为不变；
- 快照缺失/过期/缺少参与材料的读数时，每次任务先触发一次 WarehouseInventory 全量扫描，
  仍不可用则退回实扫仓库的原有流程；
- 逐局按实际掉落累计（`DepotMaintainAccumulate`）：优先读 drop_core 的 `total_drops` 增量，
  没有 drop_core（dev 版 / 无法导入）时自读结算页掉落行；累计达标后当前批次收尾；
- 每局把已确认的掉落增量写回仓库快照，避免任务中断后重复刷取；
- 逐材料吃糖：每轮按本轮材料设置覆盖 `EatCandy.enabled` / `EatCandyStart.max_hit`
  （0 = 不吃糖、N = 限次），基线取自 GUI「吃糖」选项生效后的节点数据，下一轮自动还原；
- 掉落上报只覆盖原有材料：每轮按关卡是否在 drop_core 上报表内开关胜利链里的 `DropRecognition`，
  表内关卡（原目录材料）照旧上报，新加的（如洞悉本）一律不参与上报；
- 读数来源两种（材料目录的 `source` 字段）：仓库快照（默认）与角色升级页
  （微尘/利齿子儿等货币，不在仓库页；刷新时进角色页读右上角计数，数量为游戏显示的 K 缩写值）；
- 一次任务连续补多种材料：一轮作战（`TargetCountFinish.next → BF_Plan`）补齐一种，
  直到全部达标、或上一轮没打成（体力不足）、或达到轮数上限才收尾。
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import is_hit, ocr_text
from utils.material_catalog import (
    SOURCE_CHARACTER,
    SOURCE_WAREHOUSE,
    CatalogError,
    MaterialEntry,
    colorize_name,
    load_catalog,
)
from utils.params import parse_params
from utils.settlement_drops import read_battle_drops
from utils.warehouse_snapshot import (
    SNAPSHOT_PATH,
    load_snapshot_file,
    save_snapshot_file,
    snapshot_bucket,
)

# 相对导入：agent.custom.* 与 custom.* 是两张模块图，跨图导入会重复注册自定义动作
from .combat import battles_done, request_combat_stop
from .record_id import RecordID

# 掉落累计读取方式：drop_core 累计 / 结算页自读 / 固定掉落只按估算
READ_DROP_CORE = "drop_core"
READ_SETTLEMENT = "settlement"
READ_ESTIMATE = "estimate"
DROP_TEMPLATE_DIR = Path("resource/base/image/Items_processed")

DropRecognitionState: Any = None
_drop_core_available: bool = False
try:
    from libs.drop_core import DropRecognitionState  # pyright: ignore[reportMissingImports]

    _drop_core_available = True
except ImportError:
    logger.debug("掉落识别模块不可用，库存保持将自读结算页掉落行")

SNAPSHOT_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
SNAPSHOT_TTL_HOURS = 24
# 材料名称/品质表（与仓库扫描同源）：日志里显示「名称（品质色）」用
ITEMS_PATH = Path("data/combat/items.json")
_RARITY_ORDER = ("gold", "yellow", "purple", "blue", "green")

PLAN_NODE = "BF_Plan"
REFRESH_NODE = "BF_Refresh"
DONE_NODE = "BF_Done"
DROP_REPORT_NODE = "DropRecognition"
ACCUMULATE_NODE = "BF_DepotAccumulate"
# 由 combat.py 的 SelectCombatStage 在主线流程里注入，库存保持模式下才有意义
VICTORY_CLICK_NODE = "TargetCountVictoryClick"
EAT_CANDY_NODE = "EatCandy"
EAT_CANDY_START_NODE = "EatCandyStart"
# 与 tasks/Psychube.json「自定义吃糖次数」的“不限”约定一致
UNLIMITED_CANDY = 114514
# 一轮 = 补齐一种材料的一次作战；硬上限防异常打转
MAX_ROUNDS_PER_TASK = 50
LEGACY_ENTRY_NODE = "BF_EnterWarehouse"
WAREHOUSE_SCAN_ENTRY = "WarehouseInventory"
# 角色升级页读数（微尘/利齿子儿等不在仓库页的货币）
CURRENCY_SCAN_ENTRY = "DepotCurrencyInspect"
# 复用「信任奖励领取」的角色页入口链：沿用它的「先回主界面」守卫（[JumpBack]ReturnMain）
CURRENCY_NAV_ENTRY = "DepotCurrencyNav"
CURRENCY_NUMBER_NODES: Mapping[str, str] = {"205": "CI_DustNumber", "203": "CI_CoinNumber"}
# 升级面板就绪标志：读数前必须先确认它命中（见 DepotCurrencyRead）
CURRENCY_PANEL_NODE = "CI_PanelReady"
# 回主界面统一走共享的 ReturnMain（startup.json）；它到家后会用 DisableNode 把自己关掉，
# 所以二次使用必须经 ResetReturnMain 重新启用——与 warehouse_inventory.json 的 WI_AtMain 同一形状
HOME_ENTRY = "ResetReturnMain"
# 账号 id 的读取节点：自带主界面 HomeFlag 模板识别，只在主界面才触发
RECORD_ID_ENTRY = "RecordId"
# ReturnMain 在 startup.json 里 max_hit 只有 2，而命中计数在整个 task run 内按节点名累计、
# 只有 post_task 才清零；ResetReturnMain 又只重置 enabled、不管计数。库存保持整轮要多次回主界面
# （每换一种材料一次 + 收尾一次），不自己把上限抬起来就会被 run_next 静默跳过、空转到超时。
RETURN_MAIN_MAX_HIT = 114514
# 面板数字单位：K/M（游戏不用中文单位）。实测 3,969,000 显示为 3969K，切换阈值未知，按后缀换算即可
_CURRENCY_SUFFIX = {"K": 1_000, "M": 1_000_000}


class _PlanState:
    """单次任务内的规划与累计状态，供收尾节点输出总结。"""

    refreshed = False
    refresh_warehouse = False
    refresh_currency = False
    item_id: str | None = None
    item_name = ""
    stage = ""
    level = ""
    deficit = 0
    runs = 0
    read_mode = READ_SETTLEMENT
    observed = 0
    persisted = 0
    stopped = False
    rounds = 0
    completed: list[str] = []
    per_run: int | None = None
    # 估算模式（无掉落模板）本轮已回写的局数：按增量记账，重复调用不会重复计数。
    # 与 `battles_done()` 同为「本轮」口径（`TargetCountInit` 每轮把计数器清零）。
    estimate_committed_battles = 0
    # 本批（两次 `TargetCountProgress` 之间）已打完、还没并进 `battles_done()` 的局数
    estimate_batch_battles = 0
    # 上次观测到的 `battles_done()`：跳变即「本批局数已并入」，逐局计数随之作废
    estimate_folded_battles = 0
    baseline_captured = False
    candy_base_enabled = True
    candy_base_max_hit = UNLIMITED_CANDY
    report_base_enabled = True
    # 本轮参与库存保持、需要角色页读数的货币（决定读数齐全与否，见 write_snapshot_counts）
    required_currency: list[str] = []


_state = _PlanState()

_item_labels: dict[str, tuple[str, str]] | None = None


def _load_item_labels() -> dict[str, tuple[str, str]]:
    """读取材料名/品质表（id →（名称, 品质组））；失败时返回空表，日志回退目录名称。"""
    global _item_labels
    if _item_labels is not None:
        return _item_labels
    labels: dict[str, tuple[str, str]] = {}
    try:
        raw = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for rarity, items in raw.items():
                if not isinstance(items, dict):
                    continue
                for item_id, info in items.items():
                    name = info.get("name") if isinstance(info, dict) else None
                    if isinstance(name, str) and name:
                        labels[str(item_id)] = (name, str(rarity))
    except (OSError, json.JSONDecodeError):
        logger.debug(f"读取材料名称表失败({ITEMS_PATH})，日志退回材料目录名称")
    _item_labels = labels
    return labels


def material_label(item_id: str, catalog: Mapping[str, MaterialEntry] | None = None) -> str:
    """日志里的材料显示名：优先 items.json 的「按品质上色的名称」，回退材料目录名称，再回退物品 id。

    货币等不在 items.json 里的材料没有品质色，只显示名称。
    """
    labels = _load_item_labels()
    if item_id in labels:
        name, rarity = labels[item_id]
        return colorize_name(name, rarity)
    if catalog is not None and item_id in catalog:
        return catalog[item_id].name
    return item_id


def sort_items_by_rarity(item_ids: Iterable[str]) -> list[str]:
    """按品质等级（金→黄→紫→蓝→绿，无品质的最后）再按 id 排序，与仓库扫描的排列一致。"""
    labels = _load_item_labels()
    rank = {rarity: index for index, rarity in enumerate(_RARITY_ORDER)}
    return sorted(
        item_ids,
        key=lambda item_id: (rank.get(labels.get(item_id, ("", ""))[1], len(_RARITY_ORDER)), item_id),
    )


def parse_target(value: Any) -> int | None:
    """把配置值解析为非负整数目标库存；非法值返回 None。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number: float = value
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number < 0 or number != int(number):
        return None
    return int(number)


def current_account_id() -> str:
    """当前账号 id（`RecordID` 没跑过时为空，落盘时归入默认桶）。"""
    return RecordID.current_account_id()


def _ensure_account_id(context: Context) -> bool:
    """确保拿得到账号 id —— 快照按账号分桶，读不到就无法保证同一轮里读写落在同一个桶。

    账号 id 是 `RecordID` 的**进程内缓存**：agent 重启后为空，要等 `RecordId` 节点在主界面跑过才有值。
    为空时快照落 `__default__` 桶，等 `RecordId` 跑出账号后又切到真实账号桶 —— 同一轮里就会读写错位
    （实测：角色页读数写进 `__default__`，规划读真实账号桶拿到旧值，把缺口算成 160 万、白刷一整轮）。

    所以碰快照之前先回主界面把账号读出来。`ReturnMain` 本就是「任务开始前使用」的回家链，
    到家后 `HomeFlagCloseReturnMain → RecordId` 会顺带跑一次。
    """
    if current_account_id():
        return True

    detail = context.run_task(HOME_ENTRY)
    if detail is None or detail.status.failed:
        logger.warning("读取账号信息前未能回到主界面")
    if not current_account_id():
        context.run_task(RECORD_ID_ENTRY)
    if not current_account_id():
        logger.warning("未能读到账号信息")
        return False
    logger.debug(f"已读到账号信息: {current_account_id()}")
    return True


def read_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    """读取当前账号的仓库扫描快照（WarehouseInventory 任务落盘）。"""
    target = path or SNAPSHOT_PATH
    if not target.exists():
        logger.debug(f"尚未生成库存数据（{target}），本次将先刷新")
        return None
    return snapshot_bucket(load_snapshot_file(target), current_account_id()) or None


def save_snapshot(snapshot: Mapping[str, Any], path: Path | None = None) -> bool:
    """把整份快照写进当前账号的桶；其他账号的读数原样保留。"""
    target = path or SNAPSHOT_PATH
    data = load_snapshot_file(target)
    bucket = snapshot_bucket(data, current_account_id())
    bucket.clear()
    bucket.update(snapshot)
    try:
        save_snapshot_file(data, target)
    except OSError as exc:
        logger.warning(f"写入库存数据失败（{target}）: {exc}")
        return False
    return True


def snapshot_counts(snapshot: Mapping[str, Any] | None) -> dict[str, int]:
    """取出快照中的材料数量；非法条目跳过。"""
    raw = (snapshot or {}).get("counts")
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for item_id, value in raw.items():
        try:
            counts[str(item_id)] = int(value)
        except (TypeError, ValueError):
            continue
    return counts


def snapshot_is_fresh(
    snapshot: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    ttl_hours: int = SNAPSHOT_TTL_HOURS,
) -> bool:
    """仓库读数（updated_at）是否在有效期内；缺失或无法解析一律视为过期。"""
    stamp = (snapshot or {}).get("updated_at")
    if not isinstance(stamp, str):
        return False
    try:
        updated = datetime.strptime(stamp, SNAPSHOT_TS_FORMAT)
    except ValueError:
        return False
    return ((now or datetime.now()) - updated).total_seconds() <= ttl_hours * 3600


def snapshot_currency_is_fresh(
    snapshot: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    ttl_hours: int = SNAPSHOT_TTL_HOURS,
) -> bool:
    """角色页读数（currency_updated_at）是否在有效期内；两套读数各有自己的时间戳。"""
    stamp = (snapshot or {}).get("currency_updated_at")
    if not isinstance(stamp, str):
        return False
    try:
        updated = datetime.strptime(stamp, SNAPSHOT_TS_FORMAT)
    except ValueError:
        return False
    return ((now or datetime.now()) - updated).total_seconds() <= ttl_hours * 3600


def parse_abbreviated_number(text: str) -> int | None:
    """解析游戏缩写数字：纯数字原样，K/M 后缀按千/百万换算。

    单位切换阈值未知（实测 3,969,000 显示为 3969K），按后缀换算即可；
    缩写的显示精度是千位（K），换算结果存在 ≤1000 的误差。
    """
    raw = text.strip().upper().replace(",", "")
    if not raw:
        return None
    factor = 1
    if raw[-1] in _CURRENCY_SUFFIX:
        factor = _CURRENCY_SUFFIX[raw[-1]]
        raw = raw[:-1]
    if not raw or raw.count(".") > 1 or not raw.replace(".", "", 1).isdigit():
        return None
    return round(float(raw) * factor)


def write_snapshot_counts(updates: Mapping[str, int], path: Path | None = None, *, complete: bool = True) -> bool:
    """把角色页读数合并进仓库快照，并在读数齐全时盖自己的时间戳 currency_updated_at。

    仓库读数的 updated_at 保持不变（它表示上次全量扫描时间，两套读数各算各的有效期）；
    文件不存在时新建，缺失的 updated_at 一并补上当前时间。

    `complete=False`（本轮没读全参与材料的读数）时**保留原时间戳**：读到的那几个数照常合并，
    但时间戳不刷新，下次规划仍会判定角色页读数过期并重试，不会拿没读到的旧值当新鲜读数用。
    """
    target = path or SNAPSHOT_PATH
    snapshot = read_snapshot(target)
    if snapshot is None:
        snapshot = {"updated_at": datetime.now().strftime(SNAPSHOT_TS_FORMAT), "counts": {}}
    counts = snapshot.get("counts")
    if not isinstance(counts, dict):
        counts = {}
        snapshot["counts"] = counts
    for item_id, value in updates.items():
        counts[item_id] = value
    if complete:
        snapshot["currency_updated_at"] = datetime.now().strftime(SNAPSHOT_TS_FORMAT)
    return save_snapshot(snapshot, target)


def gui_material_params(context: Context, params: Mapping[str, Any]) -> dict[str, Any]:
    """合并逐材料数值的两条通道：GUI 旧参数（custom_action_param）与 BF_Plan.attach。

    多个材料的设置项各写一份 custom_action_param 时后者会整体替换前者（MaaFW 覆盖语义），
    因此逐材料数值走 attach（会叠加合并），这里把 attach 里的 target_*/candy_* 补进来（attach 优先）。
    """
    node = context.get_node_object(PLAN_NODE)
    attach = getattr(node, "attach", None)
    merged = dict(params)
    if isinstance(attach, dict):
        for key, value in attach.items():
            name = str(key)
            if name.startswith("target_") or name.startswith("candy_"):
                merged[name] = value
    return merged


def parse_gui_targets(params: Mapping[str, Any], catalog: Mapping[str, MaterialEntry]) -> dict[str, int]:
    """解析 GUI 的逐材料目标框：留空/缺失 = 未设置（不刷）；0 = 不刷；正整数 = 目标库存。

    不在仓库页的货币材料（source=character，数量级大）额外支持 K/M 缩写，如 5M = 5000000。
    """
    targets: dict[str, int] = {}
    for item_id, entry in catalog.items():
        raw = params.get(f"target_{item_id}")
        if raw is None or raw == "":
            continue
        value = parse_abbreviated_number(str(raw)) if entry.source == SOURCE_CHARACTER else parse_target(raw)
        if value is None:
            logger.warning(f"{material_label(item_id, catalog)} 的 GUI 目标值非法: {raw!r}，已忽略")
            continue
        targets[item_id] = value
    return targets


def parse_gui_candy(params: Mapping[str, Any], catalog: Mapping[str, MaterialEntry]) -> dict[str, int]:
    """解析 GUI 的逐材料吃糖次数：留空/缺失 = 不限（跟随全局吃糖设置）；0 = 不吃糖；N = 最多 N 个。"""
    caps: dict[str, int] = {}
    for item_id in catalog:
        raw = params.get(f"candy_{item_id}")
        if raw is None or raw == "":
            continue
        value = parse_target(raw)
        if value is None:
            logger.warning(f"{material_label(item_id, catalog)} 的 GUI 吃糖次数非法: {raw!r}，已忽略")
            continue
        caps[item_id] = value
    return caps


def selected_items(context: Context, catalog: Mapping[str, MaterialEntry]) -> set[str] | None:
    """读取 GUI「参与材料」勾选列表（挂在 BF_Plan.attach 的 mat_<id> 标记上）。

    返回 None 表示未勾选任何材料 = 不限制（由目标值决定参与与否）；
    返回集合表示只刷勾选的这些材料。
    """
    node = context.get_node_object(PLAN_NODE)
    attach = getattr(node, "attach", None)
    if not isinstance(attach, dict):
        return None
    chosen = {
        str(key)[4:]
        for key, value in attach.items()
        if str(key).startswith("mat_") and value and str(key)[4:] in catalog
    }
    return chosen or None


def resolve_targets(catalog: Mapping[str, MaterialEntry], gui_overrides: Mapping[str, int]) -> dict[str, int]:
    """把 GUI 逐材料目标展开成完整目标表；未设置的材料按 0（不刷）。"""
    return {item_id: gui_overrides.get(item_id, 0) for item_id in catalog}


def pick_target(
    catalog: Mapping[str, MaterialEntry],
    inventory: Mapping[str, int],
    targets: Mapping[str, int],
) -> tuple[MaterialEntry, int] | None:
    """挑缺口最大的材料；没有库存读数的材料不参与，全部达标返回 None。"""
    deficits: dict[str, int] = {}
    for item_id, entry in catalog.items():
        target = targets.get(item_id, 0)
        if target <= 0:
            continue
        count = inventory.get(item_id)
        if count is None:
            logger.warning(f"{material_label(entry.item_id, catalog)} 没有库存读数，本次不参与")
            continue
        deficit = target - count
        if deficit > 0:
            deficits[item_id] = deficit

    if not deficits:
        return None
    item_id = max(deficits, key=lambda key: deficits[key])
    return catalog[item_id], deficits[item_id]


def runs_for(deficit: int, entry: MaterialEntry) -> int:
    """把缺口折算成刷取次数；未登记 per_run 时按每局 1 个保守估算。"""
    per_run = entry.per_run
    if per_run is None:
        logger.debug(f"{entry.name}({entry.item_id}) 未登记 per_run，按每局 1 个保守估算")
        per_run = 1
    return max(1, math.ceil(deficit / per_run))


def _capture_baselines(context: Context) -> None:
    """记录任务开始时的全局开关（GUI 选项生效后的节点数据），逐材料/逐关卡设置在其上叠加。"""
    if _state.baseline_captured:
        return
    eat = context.get_node_data(EAT_CANDY_NODE) or {}
    start = context.get_node_data(EAT_CANDY_START_NODE) or {}
    report = context.get_node_data(DROP_REPORT_NODE) or {}
    _state.candy_base_enabled = bool(eat.get("enabled", True))
    try:
        _state.candy_base_max_hit = int(start.get("max_hit", UNLIMITED_CANDY))
    except (TypeError, ValueError):
        _state.candy_base_max_hit = UNLIMITED_CANDY
    _state.report_base_enabled = bool(report.get("enabled", True))
    _state.baseline_captured = True


def material_candy_override(context: Context, item_id: str, caps: Mapping[str, int]) -> dict[str, Any]:
    """本轮材料的吃糖覆盖：0 = 关闭吃糖；N = 覆盖次数上限；留空 = 还原全局设置。"""
    _capture_baselines(context)
    cap = caps.get(item_id)
    enabled = _state.candy_base_enabled and cap != 0
    max_hit = _state.candy_base_max_hit if cap is None or cap == 0 else cap
    return {"EatCandy": {"enabled": enabled}, "EatCandyStart": {"max_hit": max_hit}}


def report_enabled(context: Context, stage: str, level: str) -> bool:
    """本轮关卡的掉落上报开关：只有上报表内的关卡（原有材料）参与上报，新加的不参与。"""
    _capture_baselines(context)
    return _state.report_base_enabled and _stage_reportable(stage, level)


def candy_note(item_id: str, caps: Mapping[str, int]) -> str:
    """日志里简述本轮材料的吃糖设置。"""
    cap = caps.get(item_id)
    if cap is None:
        return ""
    return "、不吃糖" if cap == 0 else f"、最多吃 {cap} 个糖"


def _stage_reportable(stage: str, level: str) -> bool:
    """该关卡是否有 drop_core 掉落验证数据：只有上报表内的关卡（原有材料）才参与掉落上报。"""
    if not _drop_core_available:
        return False
    try:
        DropRecognitionState.load_data()
        level_key = DropRecognitionState.get_level_key(stage, level)
        return level_key in DropRecognitionState.drop_index
    except (AttributeError, ImportError) as exc:
        logger.warning(f"读取 drop_core 掉落索引失败，按不参与上报处理: {exc}")
        return False


def _pick_read_mode(item_id: str, label: str, *, reportable: bool) -> str:
    """选掉落累计来源：能读 drop_core 累计就用它，否则自读结算页。

    `reportable` 必须是调用方按**本轮**关卡算出来的上报开关（`report_enabled`）。
    不能读 `context.get_node_data()`：那是上一轮留下的值——上一轮刷表外关卡会把
    `DropRecognition` 关掉，本轮刷表内关卡时会被误判成"不上报"而退回自读。
    """
    if not _drop_core_available:
        return _settlement_or_estimate(item_id, label)

    if not reportable:
        logger.debug("本轮不参与掉落上报，库存保持改用结算页自读")
        return _settlement_or_estimate(item_id, label)

    return READ_DROP_CORE


def _settlement_or_estimate(item_id: str, label: str) -> str:
    """有掉落模板才自读结算页；否则该材料只按每局掉落量估算（固定掉落时估算即精确）。"""
    if (DROP_TEMPLATE_DIR / f"Item-{item_id}.png").is_file():
        return READ_SETTLEMENT
    logger.debug(f"{label} 没有掉落模板，按每局掉落量估算刷取次数")
    return READ_ESTIMATE


def _replay_ui_visible(context: Context) -> bool:
    """关卡页的「复现」按钮是否可见：可见说明上一批就地在关卡页结束，可直接重选次数续刷。"""
    img = context.tasker.controller.post_screencap().wait().get()
    return is_hit(context.run_recognition("TargetCountWaitReplay", img))


def _observed_drops(context: Context) -> int:
    """本任务已确认的掉落数：优先 drop_core 累计，其次结算页自读累计。

    drop_core 的 total_drops 由 TargetCountInit 在每次作战开始时清零，因此直接取绝对值；
    取历史最大值是为了防中途意外的清零把进度打回去。
    """
    item_id = _state.item_id
    if item_id is None:
        return _state.observed

    if _state.read_mode == READ_DROP_CORE:
        total = int(DropRecognitionState.total_drops.get(int(item_id), 0))
        _state.observed = max(_state.observed, total)
        return _state.observed

    count = read_battle_drops(context, item_id, _state.item_name)
    if count is None:
        logger.warning(f"{_state.item_name} 结算页未读到掉落，本局按 0 计")
        return _state.observed
    _state.observed += count
    return _state.observed


def _persist_snapshot(drops: int) -> None:
    """把已确认的掉落增量写回仓库快照，避免任务中断后重复刷取。"""
    item_id = _state.item_id
    increment = drops - _state.persisted
    if item_id is None or increment <= 0:
        return

    snapshot = read_snapshot()
    if snapshot is None:
        return
    raw_counts = snapshot.get("counts")
    if not isinstance(raw_counts, dict) or item_id not in raw_counts:
        return
    try:
        current = int(raw_counts[item_id])
    except (TypeError, ValueError):
        return
    raw_counts[item_id] = current + increment
    if not save_snapshot(snapshot):
        return
    _state.persisted = drops
    logger.debug(f"仓库快照已更新: {_state.item_name}({item_id}) +{increment} -> {raw_counts[item_id]}")


def _sync_estimate_folded() -> None:
    """`battles_done()` 一跳变就说明批次收尾把本批局数并进了计数器，逐局计数随之作废。

    不清零的话下一批会把这批局数再加一遍（跨批重复计数）。批次没走到 `TargetCountProgress`
    就中断时计数器不动，逐局计数会保留下来，正是我们想要的。
    """
    total = battles_done()
    if total != _state.estimate_folded_battles:
        _state.estimate_folded_battles = total
        _state.estimate_batch_battles = 0


def _note_estimate_battle() -> None:
    """估算模式每局结算页到达时调用：本局计入「本批逐局数」，随后立刻回写。

    必须先同步批次并入再自增 —— 否则批次收尾后的第一局会连带把已并入的局数一起冲掉。
    """
    _sync_estimate_folded()
    _state.estimate_batch_battles += 1
    _commit_estimate_progress()


def _commit_estimate_progress() -> None:
    """估算模式（无掉落模板）下按已打局数把进度写回快照。

    固定掉落的关卡每局必掉 per_run 个，局数就是真实产出，早停也不会多算；
    不写回的话快照永远停在旧值，多轮循环会一直重复刷同一种材料。

    「已完成局数」= `battles_done()`（本批之前的批次已并入的部分）+ 本批尚未并入的逐局数。
    结算页（每局打完）由 `DepotMaintainAccumulate` 立刻写一次；规划节点再调一次只作兜底
    （批次收尾没走到结算页时补写）。`estimate_committed_battles` 本轮累计，重复调用不会重复计数。
    """
    if _state.item_id is None or _state.read_mode != READ_ESTIMATE:
        return

    _sync_estimate_folded()
    battles = battles_done() + _state.estimate_batch_battles
    new_battles = battles - _state.estimate_committed_battles
    if new_battles <= 0:
        return
    _state.estimate_committed_battles = battles

    gained = new_battles * max(_state.per_run or 1, 1)
    _persist_snapshot(_state.persisted + gained)
    if _state.per_run:
        logger.info(f"按实际局数回写库存: {_state.item_name} +{gained}（{new_battles} 局 × 每局 {_state.per_run} 个）")
    else:
        logger.info(f"按实际局数回写库存: {_state.item_name} +{gained}（{new_battles} 局，按每局至少 1 个估算）")


@AgentServer.custom_action("DepotMaintainAccumulate")
class DepotMaintainAccumulate(CustomAction):
    """结算页累计本局掉落；累计达标后把当前批次设为最后一批。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        try:
            self._accumulate(context)
        except Exception as exc:
            # 显式失败而不是吞掉：本节点在 balanced_farming.json 里配了
            # `on_error: ["TargetCountVictoryClick"]`，引擎会接管把结算页点掉，
            # 失败同时对上可见（遥测 / focus）。少计一局只会多刷一点，方向安全。
            logger.error(f"库存保持累计失败: {exc}")
            return CustomAction.RunResult(success=False)

        # 继续点掉本局结算页，让当前批次正常推进（停止在批次边界生效）
        context.override_next(ACCUMULATE_NODE, [VICTORY_CLICK_NODE])
        return CustomAction.RunResult(success=True)

    def _accumulate(self, context: Context) -> None:
        """读本局掉落并写回快照；缺口填满时请求批次收尾。"""
        if _state.item_id is None:
            # 非库存保持模式：什么都不用做
            return

        if _state.read_mode == READ_ESTIMATE:
            # 没有掉落模板：结算页出现就是本局打完，按局数折算后**立刻**回写。
            # 不能等下一轮规划才结账 —— 中途失败/停止会让快照停在旧值，而快照 24h 内都算新鲜读数。
            _note_estimate_battle()
            return

        drops = _observed_drops(context)
        logger.info(f"库存保持进度: {_state.item_name} 已确认 {drops} / 缺口 {_state.deficit}")
        logger.debug(f"累计来源: {_state.read_mode}")
        _persist_snapshot(drops)

        if drops >= _state.deficit and not _state.stopped:
            _state.stopped = True
            _state.completed.append(_state.item_name)
            logger.info(f"缺口已满，当前批次结束后停止刷取（{_state.item_name} x{drops}）")
            request_combat_stop()


@AgentServer.custom_action("DepotMaintainInit")
class DepotMaintainInit(CustomAction):
    """任务入口重置规划状态，保证每次任务各自只触发一次仓库全量扫描。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        _state.refreshed = False
        _state.refresh_warehouse = False
        _state.refresh_currency = False
        _state.item_id = None
        _state.item_name = ""
        _state.stage = ""
        _state.level = ""
        _state.deficit = 0
        _state.runs = 0
        _state.read_mode = READ_SETTLEMENT
        _state.observed = 0
        _state.persisted = 0
        _state.stopped = False
        _state.rounds = 0
        _state.completed = []
        _state.per_run = None
        _state.estimate_committed_battles = 0
        _state.estimate_batch_battles = 0
        _state.estimate_folded_battles = 0
        _state.baseline_captured = False
        _state.candy_base_enabled = True
        _state.candy_base_max_hit = UNLIMITED_CANDY
        _state.report_base_enabled = True
        _state.required_currency = []
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DepotMaintainPlan")
class DepotMaintainPlan(CustomAction):
    """库存保持规划：决定刷哪种材料、刷新快照、退回原有流程或直接收尾。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        try:
            params = gui_material_params(context, parse_params(argv.custom_action_param))
        except ValueError as exc:
            logger.error(f"库存保持参数解析失败: {exc}")
            return CustomAction.RunResult(success=False)

        if params.get("depot_disabled"):
            logger.info("未开启「库存保持」，按原有均衡逻辑刷取")
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE, "[JumpBack]ReturnMain"])
            return CustomAction.RunResult(success=True)

        # 读不到账号就退回原有流程：否则快照会落默认桶，与后续按账号桶的读写错位
        if not _ensure_account_id(context):
            logger.error("未能读取账号信息，库存快照无法与账号对应，本轮按原有均衡逻辑刷取")
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE, "[JumpBack]ReturnMain"])
            return CustomAction.RunResult(success=True)

        try:
            catalog = load_catalog()
        except CatalogError as exc:
            logger.error(f"材料目录不可用: {exc}")
            return CustomAction.RunResult(success=False)

        targets = resolve_targets(catalog, parse_gui_targets(params, catalog))
        candy_caps = parse_gui_candy(params, catalog)
        chosen = selected_items(context, catalog)
        if chosen is not None:
            targets = {item_id: (value if item_id in chosen else 0) for item_id, value in targets.items()}
            names = "、".join(material_label(item_id, catalog) for item_id in sort_items_by_rarity(chosen))
            logger.info(f"只刷勾选的 {len(chosen)} 种材料: {names}")
        if not any(value > 0 for value in targets.values()):
            logger.info("未设置任何目标库存，按原有均衡逻辑刷取")
            logger.debug("逐材料目标均为空或 0")
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE, "[JumpBack]ReturnMain"])
            return CustomAction.RunResult(success=True)

        if _state.rounds > 0:
            _commit_estimate_progress()
            # 上一轮是空转（体力不足 / 无法复现）就打不动了，直接收尾
            if battles_done() == 0:
                logger.info("上一轮没有实际战斗（体力不足或无法复现），库存保持结束")
                context.override_next(PLAN_NODE, [DONE_NODE])
                return CustomAction.RunResult(success=True)
            if _state.rounds >= MAX_ROUNDS_PER_TASK:
                logger.warning(f"已达单次任务轮数上限 {MAX_ROUNDS_PER_TASK}，结束库存保持")
                context.override_next(PLAN_NODE, [DONE_NODE])
                return CustomAction.RunResult(success=True)

        snapshot = read_snapshot()
        inventory = snapshot_counts(snapshot)
        tracked = [item_id for item_id, value in targets.items() if value > 0]
        if not tracked:
            logger.warning("材料目录里没有任何材料被设为目标库存，请检查目标配置")
            context.override_next(PLAN_NODE, [DONE_NODE])
            return CustomAction.RunResult(success=True)

        missing = [item_id for item_id in tracked if item_id not in inventory]
        wh_ids = [item_id for item_id in tracked if catalog[item_id].source == SOURCE_WAREHOUSE]
        ch_ids = [item_id for item_id in tracked if catalog[item_id].source == SOURCE_CHARACTER]
        # 角色页读数只有在本轮参与的货币都读到时才算齐（见 write_snapshot_counts）
        _state.required_currency = ch_ids
        # 两套读数各有自己的时间戳：仓库读数看 updated_at，角色页读数看 currency_updated_at，
        # 各自只要求自己那一侧的读数齐全且没过期（刷新也只会清掉自己那一侧）。
        wh_stale = bool(wh_ids) and not snapshot_is_fresh(snapshot)
        ch_stale = bool(ch_ids) and not snapshot_currency_is_fresh(snapshot)
        needs_warehouse = any(item_id not in inventory for item_id in wh_ids) or wh_stale
        needs_currency = any(item_id not in inventory for item_id in ch_ids) or ch_stale
        if needs_warehouse or needs_currency:
            if not _state.refreshed:
                _state.refreshed = True
                reasons: list[str] = []
                if missing:
                    reasons.append(f"快照缺少 {len(missing)} 种参与材料的读数")
                if wh_stale:
                    reasons.append("仓库读数已过期")
                if ch_stale:
                    reasons.append("角色页读数已过期")
                _state.refresh_warehouse = needs_warehouse
                _state.refresh_currency = needs_currency
                logger.info("正在获取最新库存数据…")
                logger.debug(
                    f"刷新原因：{'、'.join(reasons) or '读数不完整'}；"
                    f"仓库扫描={'是' if _state.refresh_warehouse else '否'}，"
                    f"角色页读数={'是' if _state.refresh_currency else '否'}"
                )
                context.override_next(PLAN_NODE, [REFRESH_NODE])
                return CustomAction.RunResult(success=True)
            logger.warning("未能获取最新的库存数据，本次改用原有的均衡刷取流程")
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE, "[JumpBack]ReturnMain"])
            return CustomAction.RunResult(success=True)

        decision = pick_target(catalog, inventory, targets)
        if decision is None:
            # 上一轮刷的材料此时已达标（估算模式要在回写后才看到），补记进收尾总结，免得误报「未达标」
            if _state.item_name and _state.item_name not in _state.completed:
                _state.completed.append(_state.item_name)
            logger.info(f"参与库存保持的 {len(tracked)} 种材料均已达到目标库存，任务结束")
            context.override_next(PLAN_NODE, [DONE_NODE])
            return CustomAction.RunResult(success=True)

        entry, deficit = decision
        runs = runs_for(deficit, entry)
        label = material_label(entry.item_id, catalog)
        # 本轮的上报开关先算出来：读数模式依赖它，而节点数据里还是上一轮的残留值
        reportable = report_enabled(context, entry.stage.code, entry.level)
        _state.read_mode = _pick_read_mode(entry.item_id, label, reportable=reportable)
        # 未登记 per_run 的材料掉落量不确定，不向用户报「每局约 N 个」这种估算出来的确定数
        if entry.per_run:
            pace = f"每局约 {entry.per_run} 个，最多刷 {runs} 局（按实际掉落提前停止）"
        else:
            pace = "按实际掉落提前停止"
        logger.info(
            f"库存保持目标: {label} 当前 {inventory[entry.item_id]} / "
            f"目标 {targets.get(entry.item_id, 0)}，缺口 {deficit}，"
            f"{pace}{candy_note(entry.item_id, candy_caps)}，关卡 {entry.stage.code} {entry.level}"
        )

        # 同一关卡续刷且上一批就地在关卡页结束（复现按钮可见）→ 直接重选复现次数，
        # 省去回主界面再重新导航进关卡的往返
        previous_stage, previous_level = _state.stage, _state.level

        _state.rounds += 1
        _state.item_id = entry.item_id
        _state.item_name = label
        _state.stage = entry.stage.code
        _state.level = entry.level
        _state.deficit = deficit
        _state.runs = runs
        _state.observed = 0
        _state.persisted = 0
        _state.estimate_committed_battles = 0
        _state.estimate_batch_battles = 0
        _state.stopped = False
        _state.per_run = entry.per_run

        context.override_pipeline(
            {
                "SelectCombatStage": {
                    "action": {"param": {"custom_action_param": {"stage": entry.stage.code}}},
                    "attach": {"level": entry.level, "depot_accumulate": 1},
                },
                "AllIn": {
                    "action": {"param": {"custom_action_param": {"target_count": runs}}},
                },
                # 一轮结束后回到规划节点续补下一种材料；收尾由规划节点判断（全部达标 / 打不动）
                "TargetCountFinish": {"next": [PLAN_NODE]},
                # 库存保持整轮要多次回主界面，先抬 ReturnMain 的命中上限（见 RETURN_MAIN_MAX_HIT）
                "ReturnMain": {"max_hit": RETURN_MAIN_MAX_HIT},
                **material_candy_override(context, entry.item_id, candy_caps),
                DROP_REPORT_NODE: {"enabled": reportable},
            }
        )
        # 上一批就地结束时游戏停在关卡页（「复现」按钮可见）：同关卡就原地重选次数续刷；
        # 换关卡必须先回主界面 —— `Combat` 靠主界面的「进入」按钮（`EnterTheShow`）导航，
        # 停在关卡页时它那四个候选（EnterTheShowFlag / EnterTheShow / ShowClickStory / ReturnMain）
        # 一个都认不出，会一直空转到父节点超时。
        on_stage_page = _replay_ui_visible(context)
        same_stage = previous_stage == entry.stage.code and previous_level == entry.level
        if same_stage and on_stage_page:
            logger.debug("上一批就地在关卡页结束，直接重选复现次数续刷")
            context.override_next(PLAN_NODE, ["AllIn"])
        else:
            if on_stage_page:
                logger.info(f"目标换到 {entry.stage.code}，先回主界面再重新导航")
                detail = context.run_task(HOME_ENTRY)
                if detail is None or detail.status.failed:
                    logger.warning("换关卡前未能回到主界面")
                    return CustomAction.RunResult(success=False)
            context.override_next(PLAN_NODE, ["Combat"])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DepotMaintainRefresh")
class DepotMaintainRefresh(CustomAction):
    """按规划结果刷新快照：仓库全量扫描与/或角色升级页读数；成败都交回规划节点判断。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if _state.refresh_warehouse:
            logger.info("正在扫描仓库材料数量（约 1 分钟）")
            detail = context.run_task(WAREHOUSE_SCAN_ENTRY)
            if detail is None or detail.status.failed:
                logger.warning("仓库扫描未完成")
        if _state.refresh_currency:
            logger.info("正在读取微尘 / 利齿子儿数量")
            detail = context.run_task(CURRENCY_SCAN_ENTRY)
            if detail is None or detail.status.failed:
                logger.warning("微尘 / 利齿子儿 数量读取未完成")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DepotCurrencyRead")
class DepotCurrencyRead(CustomAction):
    """进角色升级面板读微尘/利齿子儿，合并进仓库快照后返回主界面。

    导航复用「信任奖励领取」的既有节点（character.json 的 EnterCharacter / FlagInCharacter /
    FirstCharacter / FlagInCharacterDetail）与它的「先回主界面」守卫（DepotCurrencyNav 的
    `[JumpBack]ReturnMain`，和 WarehouseInventory 入口同一形状）；只在运行时覆写 next，
    不改 character.json，信任奖励任务本身不受影响。
    返程复用共享的 ReturnMain（经 ResetReturnMain 重新启用，见 HOME_ENTRY）。
    面板数字是游戏显示的缩写值（如 9792K / 3.9M，单位切换阈值未知），按后缀换算，有千位误差。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        nav = context.run_task(
            CURRENCY_NAV_ENTRY,
            {
                "EnterCharacter": {"next": ["FlagInCharacter"]},
                "FlagInCharacter": {"next": ["FirstCharacter"]},
                "FirstCharacter": {"next": ["FlagInCharacterDetail"]},
                "FlagInCharacterDetail": {"next": ["CI_LevelPlus"]},
                "CI_LevelPlus": {"next": ["CI_PanelReady"]},
                "CI_PanelReady": {"next": []},
            },
        )
        if nav is None or nav.status.failed:
            logger.warning("进入角色升级面板失败，本次跳过微尘 / 利齿子儿")

        try:
            catalog = load_catalog()
        except CatalogError as exc:
            logger.debug(f"读取材料目录失败，读数日志退回物品 id: {exc}")
            catalog = {}

        updates: dict[str, int] = {}
        if nav is not None and not nav.status.failed:
            img = context.tasker.controller.post_screencap().wait().get()
            # `run_task` 的 status 不足以证明面板已经打开：导航链中途卡住时它照样报成功
            # （实测在征集页上 EnterCharacter 误命中、FlagInCharacter 连失败 8 次、
            # CI_LevelPlus / CI_PanelReady 从未执行，任务仍然成功）。不确认就会在别的界面上
            # 把顶栏那些无关数字当成货币数量写进快照。
            if not is_hit(context.run_recognition(CURRENCY_PANEL_NODE, img)):
                logger.warning("未进入角色升级面板，本次跳过微尘 / 利齿子儿")
            else:
                for item_id, node_name in CURRENCY_NUMBER_NODES.items():
                    detail = context.run_recognition(node_name, img)
                    text = ocr_text(detail)
                    value = parse_abbreviated_number(text)
                    if value is None:
                        logger.warning(f"未读到 {material_label(item_id, catalog)} 的数量")
                        logger.debug(f"{item_id} 面板识别结果: {text!r}")
                        continue
                    updates[item_id] = value

        if updates:
            summary = "、".join(
                f"{material_label(item_id, catalog)}x{updates[item_id]}" for item_id in sort_items_by_rarity(updates)
            )
            missing = [item_id for item_id in _state.required_currency if item_id not in updates]
            if missing:
                names = "、".join(material_label(item_id, catalog) for item_id in missing)
                logger.warning(f"{names} 本轮没读到，保留旧读数且不刷新时间戳（下次任务会重试）")
            if write_snapshot_counts(updates, complete=not missing):
                logger.info(f"已记录库存: {summary}")

        detail = context.run_task(HOME_ENTRY)
        if detail is None or detail.status.failed:
            logger.warning("从角色页返回主界面未完成")
        return CustomAction.RunResult(success=bool(updates))


@AgentServer.custom_action("DepotMaintainDone")
class DepotMaintainDone(CustomAction):
    """库存保持收尾：输出本次规划结果。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if _state.completed:
            logger.info(f"库存保持结束: 本次补齐 {'、'.join(_state.completed)}，共 {_state.rounds} 轮作战")
        elif _state.item_id:
            logger.info(f"库存保持结束: {_state.item_name} 未达标（缺口 {_state.deficit}）")
        else:
            logger.info("库存保持结束：本次无需刷取")

        # 续刷批次就地在关卡页结束时不会经过 TargetCountFinish，收尾在此补掉落总结与回主界面；
        # 复用共享的 ReturnMain（startup.json）——关卡页等界面需要多级返回，单击 HomeButton 可能落空；
        # 它到家后会 DisableNode 掉自己，所以经 ResetReturnMain 重新启用再走（见 HOME_ENTRY）
        if _drop_core_available:
            DropRecognitionState.print_total_summary(context)
            DropRecognitionState.reset_total()
        # 收尾没能回到主界面就如实报失败：游戏可能停在关卡页，后续任务不该按「已完成」继续
        detail = context.run_task(HOME_ENTRY)
        if detail is None or detail.status.failed:
            logger.warning("库存保持收尾未能回到主界面")
            return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=True)
