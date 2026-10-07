"""库存保持：按目标库存把材料补到目标量。

决策链：材料目录（data/combat/balanced_farming.json）→ 目标库存（GUI 逐材料数字框 +
config/depot_maintain_targets.json 覆盖）→ 仓库快照（config/warehouse_inventory.json）
→ 挑缺口最大的材料 → 交给 Combat 刷取。

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
import os
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import ocr_text
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

# 相对导入：agent.custom.* 与 custom.* 是两张模块图，跨图导入会重复注册自定义动作
from .combat import battles_done, request_combat_stop

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

SNAPSHOT_PATH = Path("config/warehouse_inventory.json")
TARGETS_OVERRIDE_PATH = Path("config/depot_maintain_targets.json")
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
CURRENCY_HOME_ENTRY = "CI_ReturnHome"
CURRENCY_NUMBER_NODES: Mapping[str, str] = {"205": "CI_DustNumber", "203": "CI_CoinNumber"}
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
    per_run = 1
    committed_round = 0
    baseline_captured = False
    candy_base_enabled = True
    candy_base_max_hit = UNLIMITED_CANDY
    report_base_enabled = True


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


def read_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any] | None:
    """读取仓库扫描快照（WarehouseInventory 任务落盘）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug(f"尚未生成库存数据（{path}），本次将先刷新")
        return None
    except OSError as exc:
        logger.warning(f"读取库存数据失败（{path}）: {exc}")
        return None
    except json.JSONDecodeError as exc:
        logger.warning(f"库存数据文件损坏（{path}）: {exc}")
        return None
    return raw if isinstance(raw, dict) else None


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


def write_snapshot_counts(updates: Mapping[str, int], path: Path | None = None) -> bool:
    """把角色页读数合并进仓库快照，并盖自己的时间戳 currency_updated_at。

    仓库读数的 updated_at 保持不变（它表示上次全量扫描时间，两套读数各算各的有效期）；
    文件不存在时新建，缺失的 updated_at 一并补上当前时间。
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
    snapshot["currency_updated_at"] = datetime.now().strftime(SNAPSHOT_TS_FORMAT)

    tmp_path = target.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp_path, target)
    except OSError as exc:
        logger.warning(f"写入库存数据失败（{target}）: {exc}")
        return False
    return True


def load_target_overrides(path: Path = TARGETS_OVERRIDE_PATH) -> dict[str, int]:
    """读取逐材料目标库存覆盖；文件缺失/损坏/值非法一律忽略并回退未设置（不刷）。"""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.warning(f"读取目标库存配置失败({path}): {exc}，全部按未设置处理")
        return {}
    except json.JSONDecodeError as exc:
        logger.warning(f"目标库存配置 JSON 损坏({path}): {exc}，全部按未设置处理")
        return {}
    if not isinstance(raw, dict):
        logger.warning(f"目标库存配置({path})应为对象，全部按未设置处理")
        return {}

    overrides: dict[str, int] = {}
    for item_id, value in raw.items():
        key = str(item_id)
        if key.startswith("_"):
            continue  # 注释字段（如 _说明）
        if value is None:
            continue  # null = 未设置（不刷）
        parsed = parse_target(value)
        if parsed is None:
            logger.warning(f"目标库存配置({path})中 {item_id} 的值非法: {value!r}，已忽略")
            continue
        overrides[key] = parsed
    return overrides


def ensure_targets_template(catalog: Mapping[str, MaterialEntry], path: Path = TARGETS_OVERRIDE_PATH) -> None:
    """覆盖文件不存在时生成模板：所有材料写 null（= 未设置，不刷），用户按需改成正整数。"""
    if path.exists():
        return
    body = {
        "_说明": (
            "逐材料目标库存：正整数 = 覆盖 GUI 逐材料目标；null = 未设置（不刷）。"
            "材料名见 docs/zh_cn/develop/depot-catalog.md"
        ),
        **{item_id: None for item_id in sorted(catalog)},
    }
    try:
        path.write_text(json.dumps(body, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.debug(f"生成目标库存模板失败({path}): {exc}")
        return
    logger.debug(f"已生成目标库存配置模板: {path}")


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


def resolve_targets(
    catalog: Mapping[str, MaterialEntry],
    gui_overrides: Mapping[str, int],
    file_overrides: Mapping[str, int],
) -> dict[str, int]:
    """合并目标库存：config 覆盖文件 > GUI 逐材料框；未设置按 0（不刷）。"""
    return {item_id: file_overrides.get(item_id, gui_overrides.get(item_id, 0)) for item_id in catalog}


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


def report_override(context: Context, stage: str, level: str) -> dict[str, Any]:
    """本轮关卡的掉落上报开关：只有上报表内的关卡（原有材料）参与上报，新加的不参与。"""
    _capture_baselines(context)
    enabled = _state.report_base_enabled and _stage_reportable(stage, level)
    return {DROP_REPORT_NODE: {"enabled": enabled}}


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


def _pick_read_mode(context: Context, item_id: str, label: str, stage: str, level: str) -> str:
    """选掉落累计来源：能读 drop_core 累计就用它，否则自读结算页。"""
    if not _drop_core_available:
        return _settlement_or_estimate(item_id, label)

    report_node = context.get_node_data(DROP_REPORT_NODE)
    if report_node is not None and not report_node.get("enabled", True):
        logger.debug("掉落统计上报已关闭，库存保持改用结算页自读")
        return _settlement_or_estimate(item_id, label)

    if not _stage_reportable(stage, level):
        logger.debug(f"{stage} {level} 不在掉落上报表内，库存保持改用结算页自读")
        return _settlement_or_estimate(item_id, label)

    return READ_DROP_CORE


def _settlement_or_estimate(item_id: str, label: str) -> str:
    """有掉落模板才自读结算页；否则该材料只按每局掉落量估算（固定掉落时估算即精确）。"""
    if (DROP_TEMPLATE_DIR / f"Item-{item_id}.png").is_file():
        return READ_SETTLEMENT
    logger.debug(f"{label} 没有掉落模板，按每局掉落量估算刷取次数")
    return READ_ESTIMATE


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

    tmp_path = SNAPSHOT_PATH.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp_path, SNAPSHOT_PATH)
    except OSError as exc:
        logger.warning(f"写入库存数据失败（{SNAPSHOT_PATH}）: {exc}")
        tmp_path.unlink(missing_ok=True)
        return
    _state.persisted = drops
    logger.debug(f"仓库快照已更新: {_state.item_name}({item_id}) +{increment} -> {raw_counts[item_id]}")


def _commit_estimate_progress() -> None:
    """估算模式（无掉落模板）下按本轮实际局数把进度写回快照。

    固定掉落的关卡每局必掉 per_run 个，`battles_done()` 就是真实产出，早停也不会多算；
    不写回的话快照永远停在旧值，多轮循环会一直重复刷同一种材料。
    """
    if _state.item_id is None or _state.read_mode != READ_ESTIMATE:
        return
    # 一轮只结一次账：同一个轮号重复进入规划（如快照回扫后重跑）不重复写
    if _state.rounds <= _state.committed_round:
        return

    battles = battles_done()
    _state.committed_round = _state.rounds
    gained = battles * max(_state.per_run, 1)
    if gained <= 0:
        return

    _persist_snapshot(_state.persisted + gained)
    logger.info(f"按实际局数回写库存: {_state.item_name} +{gained}（{battles} 局 × {_state.per_run}）")


@AgentServer.custom_action("DepotMaintainAccumulate")
class DepotMaintainAccumulate(CustomAction):
    """结算页累计本局掉落；累计达标后把当前批次设为最后一批。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if _state.item_id is None or _state.read_mode == READ_ESTIMATE:
            # 非库存保持模式，或固定掉落只按估算刷取：让胜利链继续即可
            context.override_next(ACCUMULATE_NODE, [VICTORY_CLICK_NODE])
            return CustomAction.RunResult(success=True)

        drops = _observed_drops(context)
        logger.info(f"库存保持进度: {_state.item_name} 已确认 {drops} / 缺口 {_state.deficit}")
        logger.debug(f"累计来源: {_state.read_mode}")
        _persist_snapshot(drops)

        if drops >= _state.deficit and not _state.stopped:
            _state.stopped = True
            _state.completed.append(_state.item_name)
            logger.info(f"缺口已满，当前批次结束后停止刷取（{_state.item_name} x{drops}）")
            request_combat_stop()

        # 继续点掉本局结算页，让当前批次正常推进（停止在批次边界生效）
        context.override_next(ACCUMULATE_NODE, [VICTORY_CLICK_NODE])
        return CustomAction.RunResult(success=True)


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
        _state.per_run = 1
        _state.committed_round = 0
        _state.baseline_captured = False
        _state.candy_base_enabled = True
        _state.candy_base_max_hit = UNLIMITED_CANDY
        _state.report_base_enabled = True
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
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE])
            return CustomAction.RunResult(success=True)

        try:
            catalog = load_catalog()
        except CatalogError as exc:
            logger.error(f"材料目录不可用: {exc}")
            return CustomAction.RunResult(success=False)

        file_overrides = load_target_overrides()
        gui_overrides = parse_gui_targets(params, catalog)
        ensure_targets_template(catalog)
        targets = resolve_targets(catalog, gui_overrides, file_overrides)
        candy_caps = parse_gui_candy(params, catalog)
        chosen = selected_items(context, catalog)
        if chosen is not None:
            targets = {item_id: (value if item_id in chosen else 0) for item_id, value in targets.items()}
            names = "、".join(material_label(item_id, catalog) for item_id in sort_items_by_rarity(chosen))
            logger.info(f"只刷勾选的 {len(chosen)} 种材料: {names}")
        if not any(value > 0 for value in targets.values()):
            logger.info("未设置任何目标库存，按原有均衡逻辑刷取")
            logger.debug("逐材料目标与 config 覆盖均为空或 0")
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE])
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
            context.override_next(PLAN_NODE, [LEGACY_ENTRY_NODE])
            return CustomAction.RunResult(success=True)

        decision = pick_target(catalog, inventory, targets)
        if decision is None:
            # 上一轮刷的材料此时已达标（估算模式要在回写后才看到），补记进收尾总结，免得误报「未达标」
            if _state.item_id and _state.item_id not in _state.completed:
                _state.completed.append(_state.item_id)
            logger.info(f"参与库存保持的 {len(tracked)} 种材料均已达到目标库存，任务结束")
            context.override_next(PLAN_NODE, [DONE_NODE])
            return CustomAction.RunResult(success=True)

        entry, deficit = decision
        runs = runs_for(deficit, entry)
        label = material_label(entry.item_id, catalog)
        _state.read_mode = _pick_read_mode(context, entry.item_id, label, entry.stage.code, entry.level)
        logger.info(
            f"库存保持目标: {label} 当前 {inventory[entry.item_id]} / "
            f"目标 {targets.get(entry.item_id, 0)}，缺口 {deficit}，"
            f"每局约 {entry.per_run or 1} 个，最多刷 {runs} 局（按实际掉落提前停止）"
            f"{candy_note(entry.item_id, candy_caps)}，关卡 {entry.stage.code} {entry.level}"
        )

        _state.rounds += 1
        _state.item_id = entry.item_id
        _state.item_name = label
        _state.stage = entry.stage.code
        _state.level = entry.level
        _state.deficit = deficit
        _state.runs = runs
        _state.observed = 0
        _state.persisted = 0
        _state.stopped = False
        _state.per_run = entry.per_run or 1

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
                **material_candy_override(context, entry.item_id, candy_caps),
                **report_override(context, entry.stage.code, entry.level),
            }
        )
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
            if write_snapshot_counts(updates):
                logger.info(f"已记录库存: {summary}")

        detail = context.run_task(CURRENCY_HOME_ENTRY)
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
        return CustomAction.RunResult(success=True)
