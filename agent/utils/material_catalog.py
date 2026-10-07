"""材料目录与关卡导航族注册表。

「智能均衡刷材料」任务（库存保持模式与原有均衡逻辑共用）的单一数据入口，新增材料与新增关卡族都在这里收敛：

- 新增材料：在 data/combat/balanced_farming.json 增加一条，并补
  resource/base/image/Warehouse/Item-<id>.png 图标模板；不在仓库页的材料（微尘/利齿子儿等
  货币）写 "source": "character"，改从角色升级页读取，不需要仓库图标。
- 新增关卡族：先按 combat pipeline 既有结构补 ResourceChapter_<族> 入口节点与识别模板，
  再登记到本模块 STAGE_FAMILIES。

维护清单见 docs/zh_cn/develop/depot-catalog.md；tests/test_depot_maintain.py 会核对本目录
登记的材料图标、章节模板与入口节点是否齐全。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_PATH = Path("data/combat/balanced_farming.json")


@dataclass(frozen=True)
class FamilySpec:
    """一个资源关卡族的导航约定。"""

    entry_node: str
    label: str
    templates: tuple[str, ...] = ()


# 资源关卡族：族代码 → 关卡入口节点与识别模板（templates 为空表示该族用 OCR 识别章节标签）。
# 入口节点名取自 resource/base/pipeline/combat.json，改动前先确认 pipeline 里仍存在。
STAGE_FAMILIES: Mapping[str, FamilySpec] = {
    "LP": FamilySpec("ResourceChapter_LP", "尘埃运动", ("Combat/ResourceChapter_LPEnter.png",)),
    "MA": FamilySpec("ResourceChapter_MA", "铸币美学"),
    "ME": FamilySpec("ResourceChapter_ME", "群山之声", ("Combat/Insight/MEEnter.png",)),
    "SL": FamilySpec("ResourceChapter_SL", "星陨之所", ("Combat/Insight/SLEnter.png",)),
    "SS": FamilySpec("ResourceChapter_SS", "深林之形", ("Combat/Insight/SSEnter.png",)),
    "BW": FamilySpec("ResourceChapter_BW", "荒兽之野", ("Combat/Insight/BWEnter.png",)),
    "Psychube": FamilySpec("ResourceChapter_Psychube", "意志解析", ("Psychube/FreePsychubeStages.png",)),
}

MAIN_STORY_ENTRY_NODE = "MainChapter_X"
MAIN_STORY_ENTRY_TEMPLATE = "Combat/MainChapter_{chapter}Enter.png"
WAREHOUSE_ICON_TEMPLATE = "resource/base/image/Warehouse/Item-{item_id}.png"
PIPELINE_PATH = Path("resource/base/pipeline/combat.json")
SUPPORTED_LEVELS = ("Hard", "Story", "None")

# 品质 → 日志显示色（金/黄/紫/蓝/绿，兼顾明暗主题的深浅都够用）
RARITY_COLORS: Mapping[str, str] = {
    "gold": "#E5A32A",
    "yellow": "#D4B106",
    "purple": "#9B4FBF",
    "blue": "#3E8ED0",
    "green": "#3FA45B",
}


def colorize_name(name: str, rarity: str | None) -> str:
    """按品质给材料名上色：<font color> 由 MFAAvalonia 的 Markdown 渲染成彩色文字；品质未知原样返回。

    日志行会被客户端按 Markdown 渲染（Agent 输出走 AddLog(useMarkdown: true)），ANSI 转义会被剥掉。
    """
    color = RARITY_COLORS.get(rarity or "")
    if not color:
        return name
    return f'<font color="{color}">{name}</font>'


# 读数来源：warehouse = 仓库快照扫描；character = 角色升级页右上角（微尘/利齿子儿等货币，不在仓库页）
SOURCE_WAREHOUSE = "warehouse"
SOURCE_CHARACTER = "character"
SUPPORTED_SOURCES = (SOURCE_WAREHOUSE, SOURCE_CHARACTER)


class CatalogError(ValueError):
    """材料目录结构非法。"""


@dataclass(frozen=True)
class MaterialStage:
    """一条材料对应的刷取关卡。"""

    code: str
    chapter: str
    stage_no: str
    family: str | None = None

    @property
    def entry_node(self) -> str:
        if self.family is None:
            return MAIN_STORY_ENTRY_NODE
        return STAGE_FAMILIES[self.family].entry_node

    @property
    def templates(self) -> tuple[str, ...]:
        if self.family is None:
            return (MAIN_STORY_ENTRY_TEMPLATE.format(chapter=self.chapter),)
        return STAGE_FAMILIES[self.family].templates


@dataclass(frozen=True)
class MaterialEntry:
    """材料目录中的一条记录。"""

    item_id: str
    name: str
    stage: MaterialStage
    level: str
    # 每局掉落量（保守下界）；未登记时按每局 1 个估算刷取次数
    per_run: int | None = None
    # 读数来源：仓库扫描或角色升级页（见 SOURCE_* 常量）
    source: str = SOURCE_WAREHOUSE

    @property
    def icon_template(self) -> str:
        return WAREHOUSE_ICON_TEMPLATE.format(item_id=self.item_id)


def parse_stage_code(code: str) -> MaterialStage:
    """把关卡代码解析为章节 + 关卡序号；数字章节视为主线，其余查关卡族注册表。"""
    parts = code.split("-")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise CatalogError(f"关卡代码无法解析: {code!r}（应形如 7-26 或 MA-06）")

    chapter, raw_no = parts[0], parts[1]
    stage_no = f"{int(raw_no):02d}" if raw_no.isdigit() else raw_no

    if chapter.isdigit():
        return MaterialStage(code=code, chapter=chapter, stage_no=stage_no)

    if chapter not in STAGE_FAMILIES:
        known = "、".join(sorted(STAGE_FAMILIES))
        raise CatalogError(
            f"关卡族 {chapter!r} 未登记（{code}）；已登记: {known}。新增族见 docs/zh_cn/develop/depot-catalog.md"
        )
    return MaterialStage(code=code, chapter=chapter, stage_no=stage_no, family=chapter)


def build_catalog(raw: Any, *, source: str = str(CATALOG_PATH)) -> dict[str, MaterialEntry]:
    """校验并构建目录；一次性报出全部问题，便于维护时逐条修。"""
    if not isinstance(raw, dict):
        raise CatalogError(f"{source}: 顶层应为 {{item_id: 条目}} 对象")

    catalog: dict[str, MaterialEntry] = {}
    problems: list[str] = []
    for item_id, entry in raw.items():
        try:
            catalog[str(item_id)] = _build_entry(str(item_id), entry)
        except CatalogError as exc:
            problems.append(str(exc))

    if problems:
        raise CatalogError(f"{source} 有 {len(problems)} 处问题: " + "；".join(problems))
    return catalog


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, MaterialEntry]:
    """读取材料目录；文件缺失或内容非法时抛 CatalogError。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogError(f"读取材料目录失败: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"材料目录 JSON 损坏: {path}: {exc}") from exc
    return build_catalog(raw, source=str(path))


def catalog_problems(catalog: Mapping[str, MaterialEntry], repo_root: Path = Path(".")) -> list[str]:
    """静态校验：材料图标、章节模板、关卡入口节点是否齐全（供测试与维护检查使用）。"""
    problems: list[str] = []
    pipeline_text: str | None = None

    for item_id, entry in catalog.items():
        if entry.source == SOURCE_WAREHOUSE and not (repo_root / entry.icon_template).exists():
            problems.append(f"{item_id} {entry.name}: 缺少仓库图标模板 {entry.icon_template}")
        for template in entry.stage.templates:
            template_path = repo_root / "resource/base/image" / template
            if not template_path.exists():
                problems.append(f"{item_id} {entry.name}: 缺少章节模板 {template_path.as_posix()}")

        node = entry.stage.entry_node
        if pipeline_text is None:
            try:
                pipeline_text = (repo_root / PIPELINE_PATH).read_text(encoding="utf-8")
            except OSError as exc:
                problems.append(f"读取 {PIPELINE_PATH} 失败: {exc}")
                pipeline_text = ""
        if f'"{node}"' not in pipeline_text:
            problems.append(f"{item_id} {entry.name}: {PIPELINE_PATH} 中找不到关卡入口节点 {node}")

    return problems


def _build_entry(item_id: str, entry: Any) -> MaterialEntry:
    if not item_id.isdigit():
        raise CatalogError(f"材料 id {item_id!r} 应为纯数字（图标模板名为 Item-<id>.png）")
    if not isinstance(entry, dict):
        raise CatalogError(f"{item_id}: 条目应为对象，含 name/stage/level")

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CatalogError(f"{item_id}: name 缺失或为空")

    stage_code = entry.get("stage")
    if not isinstance(stage_code, str) or not stage_code.strip():
        raise CatalogError(f"{item_id} {name}: stage 缺失或为空")
    try:
        stage = parse_stage_code(stage_code)
    except CatalogError as exc:
        raise CatalogError(f"{item_id} {name}: {exc}") from exc

    level = entry.get("level")
    if level not in SUPPORTED_LEVELS:
        raise CatalogError(f"{item_id} {name}: level {level!r} 非法，应为 {'/'.join(SUPPORTED_LEVELS)}")

    per_run = entry.get("per_run")
    if per_run is not None and (not isinstance(per_run, int) or isinstance(per_run, bool) or per_run <= 0):
        raise CatalogError(f"{item_id} {name}: per_run 应为正整数或省略，收到 {per_run!r}")

    source = entry.get("source", SOURCE_WAREHOUSE)
    if source not in SUPPORTED_SOURCES:
        raise CatalogError(f"{item_id} {name}: source {source!r} 非法，应为 {'/'.join(SUPPORTED_SOURCES)} 或省略")

    return MaterialEntry(item_id=item_id, name=name, stage=stage, level=level, per_run=per_run, source=source)
