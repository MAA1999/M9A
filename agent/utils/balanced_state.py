"""均衡刷材料：账号的「关卡不可用」记录与「跳过均衡任务」标记。

## 账号归属：只认游戏内真实 UID

记录按**游戏内真实 UID** 分桶（`RecordID` 在主界面 OCR 的结果，由
`BalancedTaskEntry` 连续采样确认后传进来）。本模块不做任何账号识别，
也不回落任何默认值：

- 没有「最近一次切换账号任务切到的账号」这种推断；
- 没有固定默认标识；
- 不读、也不写状态文件里的「当前账号」字段（该字段已随旧设计一起删除）。

`account_id` 为空（调用方没读到 UID）时，读写函数一律按「没有记录」处理：
`unavailable_stages` / `is_task_skipped` 返回空集 / `False`，
`record_unavailable` / `set_task_skipped` 不写盘并返回 `False`。
这样「读不到 UID」就只是本次运行不落盘，不会污染任何账号的桶。

## 记录内容

只存必要信息：不可用的主线关卡、是否跳过均衡任务。

```json
{
    "accounts": {
        "100123456": {
            "updated_at": "2026-11-07 10:00:00",
            "unavailable": {"7-26": "2026-11-07 10:00:00"},
            "skip_balanced": true
        }
    }
}
```

`skip_balanced` 是**持久**标记：该 UID 的所有候选关卡都试过并失败后写入，
之后该账号的均衡任务会直接跳过。玩家推进主线后到 GUI 勾「重置记录」即可解除
（`clear_all` 清空全部记录与标记）。

## 关卡不可用边界

某主线关卡 `c-s` **寻找目标关卡超时**后，记录它，并把它以及所有数字序号**大于**它的
主线关卡一并视为不可用（主线逐关解锁，比它更靠后的更不可能解锁）：

| 候选 | 记录的不可用关卡 | 结论 |
| --- | --- | --- |
| 章节号 > 记录的章节号 | 任意 | 不可用 |
| 章节号 == 且关卡号 >= 记录的关卡号 | 同一章更靠后 | 不可用 |
| 章节号 == 且关卡号 < 记录的关卡号 | 同一章更靠前 | 可用（继续尝试） |
| 章节号 < 记录的章节号 | 更早的章节 | 可用（继续尝试） |

资源族关卡（`LP-06` / `MA-06` / `ME-02` 等）没有主线章节概念，**不套**这条编号规则。

## 候选关卡来源

候选只从原版已有的掉落索引 `data/combat/drop_index.json` 反查（它是「关卡 → 可能掉落物」
的正向表，反查即得「材料 → 所有可掉落它的关卡」），**不新增任何自造关卡表**。

顺延顺序：先试原版给该材料登记的关卡；原版没有最优备选排序时，其余按数字
`(章节号, 关卡号)` **降序**回退（如 `13-4 > 12-10`、`9-8 > 8-7`），不按字符串或难度排序。
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.account_store import (
    DEFAULT_ACCOUNT_KEY,
    get_account_bucket,
    load_json_object,
    normalize_account_id,
)
from utils.logger import logger

# 均衡刷材料的状态文件（与仓库快照同目录）
BALANCED_STATE_PATH = Path("config/balanced_state.json")
# 账号桶在文件里的键名
STATE_KEY = "accounts"
# 时间戳格式（与 warehouse_snapshot.SNAPSHOT_TS_FORMAT 保持一致）
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# 掉落索引（关卡→材料），反查「材料→关卡」用
DROP_INDEX_PATH = Path("data/combat/drop_index.json")

# 难度后缀：E=厄险（对应材料的 level=Hard），G=故事（对应 level=Story）
LEVEL_SUFFIX = {"Hard": "E", "Story": "G", "None": ""}

# 关卡列表里「关卡序号」文字的扫描范围（1280x720 基准）。
#
# 「找目标关卡」（`TargetStageName_OCR`）与「判断已滑到最左」
# （`StageLookupFarLeft`）**必须用同一个范围** —— 两者看同一批像素才不会
# 互相矛盾。关卡项的纵向位置随列表长度/滚动位置变化，所以取整个下半屏；
# 上半屏有等级、体力、各种计数等别的数字，不能扩过去。
STAGE_TEXT_ROI: tuple[int, int, int, int] = (0, 360, 1280, 360)

# 资源族关卡没有主线章节号，用一个足够大的章节号排到主线之后
_RESOURCE_CHAPTER = 9999


@dataclass(frozen=True)
class StageCandidate:
    """一个可掉落某材料的关卡候选。"""

    stage: str
    """关卡代码，形如 `7-26`（主线）或 `MA-06`（资源族）。"""

    level: str
    """难度：`Hard` / `Story` / `None`。"""

    order: tuple[int, int]
    """顺延排序键（章节号, 关卡号）；资源族关卡没有数字章节，排在所有主线关卡之后。"""

    def __str__(self) -> str:
        return f"{self.stage} {self.level}"


def parse_stage_order(stage: str) -> tuple[int, int]:
    """把主线关卡代码解析成 (章节号, 关卡号)；资源族关卡返回 (大数, 关卡号)。

    资源族（`ME-02` / `LP-06` 等）没有主线章节号，用一个足够大的章节号排到主线之后，
    保证顺延时优先尝试主线关卡。
    """
    parts = stage.split("-")
    if len(parts) < 2:
        return (_RESOURCE_CHAPTER, 0)
    chapter, raw_no = parts[0], parts[1]
    if not chapter.isdigit():
        return (_RESOURCE_CHAPTER, int(raw_no) if raw_no.isdigit() else 0)
    return (int(chapter), int(raw_no) if raw_no.isdigit() else 0)


def load_drop_index(path: Path = DROP_INDEX_PATH) -> dict[str, list[int]]:
    """读取掉落索引（关卡→材料 id 列表）；文件缺失/损坏时返回空表。"""
    raw = load_json_object(path, {})
    index: dict[str, list[int]] = {}
    for key, items in raw.items():
        if not isinstance(items, list):
            continue
        ids: list[int] = []
        for item in items:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                ids.append(item)
            elif isinstance(item, str) and item.isdigit():
                ids.append(int(item))
        index[str(key)] = ids
    return index


def candidate_stages_for_item(
    item_id: str,
    *,
    level: str,
    drop_index: dict[str, list[int]] | None = None,
) -> list[StageCandidate]:
    """反查「材料 → 所有可掉落它的关卡」，按关卡编号降序（顺延顺序）。

    - `level` 是材料目录登记的难度；掉落索引里同一关卡有 `E`(厄险) / `G`(故事) 两条记录，
      只取与登记难度一致的那条（依据：`docs/zh_cn/protocol/combat.md` 明确 `E`=厄险、
      `G`=故事；实测材料目录里 12 个主线材料的登记关卡与该对应关系 100% 吻合）。
    - 只保留主线关卡（`章节-关卡` 形式）：资源族关卡不在掉落索引里。
    - 排序键 `(章节号, 关卡号)` 降序 —— 数字比较，不按字符串或难度。
    """
    index = drop_index if drop_index is not None else load_drop_index()
    suffix = LEVEL_SUFFIX.get(level, "")
    num = int(item_id)
    candidates: dict[str, StageCandidate] = {}
    for key, items in index.items():
        if num not in items:
            continue
        if suffix and not key.endswith(suffix):
            continue
        stage = key[: -len(suffix)] if suffix else key
        if "-" not in stage:
            continue
        chapter, _, raw_no = stage.partition("-")
        if not chapter.isdigit():
            continue
        candidates[stage] = StageCandidate(
            stage=stage,
            level=level,
            order=(int(chapter), int(raw_no) if raw_no.isdigit() else 0),
        )
    return sorted(candidates.values(), key=lambda c: c.order, reverse=True)


def candidates_for_material(
    item_id: str,
    *,
    level: str,
    registered_stage: str,
    drop_index: dict[str, list[int]] | None = None,
) -> list[StageCandidate]:
    """某材料的完整候选顺序：**原登记关卡优先**，其余按数字 `(章节, 关卡)` 降序。

    原登记关卡排在最前是因为材料目录（`data/combat/balanced_farming.json`）就是按
    「该材料推荐刷哪个关」维护的；原版没有给出备选之间的效率排序，因此其余候选
    按用户指定的数字编号降序回退（`13-4 > 12-10`、`9-8 > 8-7`）。

    掉落索引里查不到该材料时（资源族关卡不在索引里）只返回登记关卡本身。

    **登记关卡始终在候选里**，即使掉落索引漏了它（索引按关卡收录材料，理论上该有，
    但版本更新或个别关卡可能缺项）。不能因为「索引里有别的候选」就把登记关卡丢掉 ——
    否则其余候选都不可用时会把材料判成「无可用关卡」，而实际上登记关卡本来是能打的。
    """
    candidates = candidate_stages_for_item(item_id, level=level, drop_index=drop_index)
    head = [c for c in candidates if c.stage == registered_stage]
    rest = [c for c in candidates if c.stage != registered_stage]
    if not head:
        # 索引里没有登记关卡 → 补到最前面（它仍是首选）
        head = [StageCandidate(stage=registered_stage, level=level, order=parse_stage_order(registered_stage))]
    return head + rest


def is_stage_unavailable(unavailable: Iterable[str], stage: str) -> bool:
    """这个关卡是否已被记录为不可用（连同「编号更大的主线关卡」一起视为不可用）。

    规则（章节号优先，数字比较）：
    - 章节号 > 某条记录的章节号 → 不可用（序号更大，一定过不去）；
    - 章节号 == 且关卡号 >= 该记录 → 不可用；
    - 章节号 < → 可用（更靠前的关卡可能已解锁，继续尝试）。

    资源族关卡（`LP-06` / `MA-06` 等）没有主线章节概念，**不套**这条编号规则：
    只在记录了同一个关卡代码本身时才算不可用（原文边界：主线编号规则不要套到资源族）。
    """
    parts = stage.split("-")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        # 资源族：只按精确匹配
        return stage in set(unavailable)

    chapter = int(parts[0])
    stage_no = int(parts[1])
    recorded_set = set(unavailable)

    for recorded in recorded_set:
        rec_parts = str(recorded).split("-")
        if len(rec_parts) < 2 or not rec_parts[0].isdigit() or not rec_parts[1].isdigit():
            # 记录的是资源族关卡：与主线编号无关，只有精确相同才算
            if recorded == stage:
                return True
            continue
        rec_chapter = int(rec_parts[0])
        rec_no = int(rec_parts[1])
        if chapter > rec_chapter:
            return True
        if chapter == rec_chapter and stage_no >= rec_no:
            return True
    return False


# ------------------------------------------------------------------ 状态读写
def _path(path: Path | None = None) -> Path:
    """取状态文件路径。

    **在调用时读模块常量**（而不是用默认参数绑定）—— 默认参数在定义时就把值
    固定住了，之后改 `BALANCED_STATE_PATH` 不生效（测试要指向临时目录，
    运行时也要能改配置目录）。

    还要**按文件路径统一**：`agent.utils.*` 与 `utils.*` 是两张模块图
    （同一份源码、两个模块对象），测试改其中一个的常量时另一个不会跟着变。
    所以这里用**当前模块的常量**为准，不去读别的模块对象。
    """
    return path if path is not None else BALANCED_STATE_PATH


def load_state(path: Path | None = None) -> dict[str, Any]:
    """读取整个状态文件；文件缺失/损坏时返回空对象。"""
    return load_json_object(_path(path), {})


def save_state(data: dict[str, Any], path: Path | None = None) -> bool:
    """原子写入状态文件：先写同目录临时文件，成功后 os.replace 替换正式路径。

    返回是否真的落盘成功 —— 调用方据此决定能不能宣称「已持久化」。
    """
    target = _path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
            os.replace(tmp_path, target)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True


def account_bucket(data: dict[str, Any], account_id: str | None = None) -> dict[str, Any]:
    """取逻辑账号的状态桶，必要时就地建好。

    **复用 `account_store.get_account_bucket`** —— 与仓库快照（`warehouse_snapshot`）
    走同一份分桶实现，好处是两套文件的分桶行为保证一致。

    ⚠️ **旧格式的根级记录直接丢弃，不做迁移**。

    早期版本把 `unavailable` / `skip_balanced` 直接放在文件根上，那时**没有账号
    概念**，没人知道这些记录属于哪个 UID。把它们搬给「第一个调用本函数的账号」
    是一种推断 —— 而本模块的约定是「记录只按游戏内真实 UID 分桶，不做任何账号推断」
    （见模块头）。一旦搬错：`skip_balanced: true` 会让某个无辜账号被永久跳过，
    而它其实还有可用关卡。

    代价是升级后第一次运行会重新试一遍那些旧关卡（各等最多两分钟超时），
    换来的是不把记录记到错的人头上。记录本身会重新积累。
    """
    key = normalize_account_id(account_id) or DEFAULT_ACCOUNT_KEY
    if STATE_KEY not in data:
        # 旧格式：没有账号概念，无法归属 → 丢弃根级残留，只保留空结构
        data.clear()
        data[STATE_KEY] = {}
    return get_account_bucket(data, STATE_KEY, key)


def current_uid() -> str:
    """取 `RecordID` 缓存里的真实 UID；读不到返回空串。

    用 `sys.modules` 查已加载的那份模块，避免 `import agent.custom...` 触发
    第二次模块加载（会重复注册自定义动作并抛 `Custom name is already registered`）。

    本函数**只**返回真实 UID，不回落任何默认值 —— 调用方据此判断
    「要不要先回主页做一次 OCR」。没有回落到文件里旧账号的分支：
    那个回落正是「用上一个账号读写记录」这类问题的来源。
    """
    for name in (
        "agent.custom.action.record_id",
        "custom.action.record_id",
    ):
        module = sys.modules.get(name)
        if module is None:
            continue
        record_id = getattr(module, "RecordID", None)
        if record_id is None:
            continue
        uid = str(record_id.current_account_id() or "").strip()
        if uid:
            return uid
    return ""


def unavailable_stages(account_id: str | None = None, path: Path | None = None) -> set[str]:
    """当前逻辑账号已记录为不可用的主线关卡。

    账号未知（读不到 UID）时返回**空集** —— 当作没有任何历史记录。
    不再回落到 `__default__` 桶：那是早期版本的遗留，一个不存在的账号
    不应该共享别的账号的记录。
    """
    if not normalize_account_id(account_id):
        return set()
    bucket = account_bucket(load_state(_path(path)), account_id)
    raw = bucket.get("unavailable")
    if not isinstance(raw, dict):
        return set()
    return {str(key) for key in raw}


def record_unavailable(
    account_id: str | None,
    stage: str,
    path: Path | None = None,
    *,
    now: str | None = None,
) -> bool:
    """记录「这个关卡找不到，以后直接跳过」。

    返回是否真的落盘成功。**保存失败时调用方不得宣称已持久化。**

    账号未知（读不到 UID）时**不写**并返回 `False`：不知道属于哪个账号，
    写进任何一个桶都可能污染别人的记录。调用方应把这条只记在
    本次运行的内存里（`BalancedFallback.failed_stages`），顺延照常工作。
    """
    if not normalize_account_id(account_id):
        logger.debug(f"账号未知，不写入关卡记录 {stage}（只记在本次运行内存）")
        return False
    target = _path(path)

    data = load_state(target)
    bucket = account_bucket(data, account_id)
    raw = bucket.get("unavailable")
    if not isinstance(raw, dict):
        raw = {}
        bucket["unavailable"] = raw
    stamp = now or _now_str()
    raw[str(stage)] = stamp
    bucket["updated_at"] = stamp
    return save_state(data, target)


def is_task_skipped(account_id: str | None = None, path: Path | None = None) -> bool:
    """当前逻辑账号是否已被标记「跳过均衡刷材料任务」。

    账号未知时返回 `False`（当作从未停用）。
    """
    if not normalize_account_id(account_id):
        return False
    bucket = account_bucket(load_state(_path(path)), account_id)
    return bool(bucket.get("skip_balanced"))


def set_task_skipped(
    account_id: str | None,
    value: bool,
    path: Path | None = None,
    *,
    now: str | None = None,
) -> bool:
    """设置/清除「跳过均衡刷材料任务」标记。

    返回是否真的落盘成功。**保存失败时调用方不得宣称已持久化。**

    账号未知时**不写**并返回 `False`（同 `record_unavailable`）。
    """
    if not normalize_account_id(account_id):
        logger.debug("账号未知，不写入停用标记")
        return False
    target = _path(path)

    data = load_state(target)
    bucket = account_bucket(data, account_id)
    stamp = now or _now_str()
    bucket["skip_balanced"] = bool(value)
    bucket["updated_at"] = stamp
    return save_state(data, target)


def clear_all(path: Path | None = None) -> bool:
    """清除**所有账号**的关卡不可用记录与均衡跳过标记。

    GUI「重置全部记录」用：用户明确要求「删除所有记录」，所以清的是所有账号的
    不可用记录与跳过标记，不是只清当前账号。

    没有需要「保留」的字段了 —— 账号归属只认游戏内 UID，不再有「当前账号」记录。
    """
    target = _path(path)
    data = load_state(target)
    data[STATE_KEY] = {}
    # 复用原子写入（tmp + os.replace）：直接 write_text 若中途出错会留下半截文件，
    # 下次 load_state 读到损坏内容会退化成空状态。
    return save_state(data, target)


def format_unavailable_summary(stages: Iterable[str]) -> str:
    """把不可用关卡格式化成一行日志。"""
    items = sorted(stages)
    if not items:
        return "（尚无记录）"
    return "、".join(items)


def _now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime(TS_FORMAT)
