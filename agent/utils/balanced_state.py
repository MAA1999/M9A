"""均衡刷材料：逻辑账号的「关卡不可用」记录与「跳过均衡任务」停用标记。

## 为什么按「逻辑账号」而不是真实 UID

本模块**不做任何账号识别**：不 OCR UID、不逐章探测、不为确认账号额外回主页。
账号归属按任务执行上下文确定（用户明确指定的简化假设）：

- 最近一次**执行成功**的「切换账号」任务切到的账号，就是当前逻辑账号；
- 没有切换账号任务时，默认始终是同一个账号（固定默认标识 `default`）；
- 切换任务尚未执行或执行失败时，**不**提前改变归属；
- 在游戏里手工换号不自动识别 —— 手工换号后的旧状态由用户在 GUI 里显式重置。

因此不同切换目标各自保留一套记录与停用标记，切回之前的账号继续沿用它那份。

## 记录内容

只存必要信息：逻辑账号标识、不可用的主线关卡、是否跳过均衡任务。

```json
{
    "current_account": "189****6002",
    "accounts": {
        "189****6002": {
            "updated_at": "2026-11-07 10:00:00",
            "unavailable": {"7-26": "2026-11-07 10:00:00"},
            "skip_balanced": true
        }
    }
}
```

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
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.account_store import DEFAULT_ACCOUNT_KEY, load_json_object, normalize_account_id

# 均衡刷材料的状态文件（与仓库快照同目录）
BALANCED_STATE_PATH = Path("config/balanced_state.json")
# 账号桶在文件里的键名
STATE_KEY = "accounts"
# 时间戳格式（与 warehouse_snapshot.SNAPSHOT_TS_FORMAT 保持一致）
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# 掉落索引（关卡→材料），反查「材料→关卡」用
DROP_INDEX_PATH = Path("data/combat/drop_index.json")

# 切换账号任务没配目标账号时使用的固定标识（表示「账号列表里选中的那个」）
DEFAULT_SWITCH_TARGET = "default"

# 难度后缀：E=厄险（对应材料的 level=Hard），G=故事（对应 level=Story）
LEVEL_SUFFIX = {"Hard": "E", "Story": "G", "None": ""}

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
    """取逻辑账号的状态桶，必要时就地建好。"""
    key = normalize_account_id(account_id) or DEFAULT_ACCOUNT_KEY
    store = data.get(STATE_KEY)
    if not isinstance(store, dict):
        store = {}
        data[STATE_KEY] = store
    bucket = store.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        store[key] = bucket
    return bucket


def current_account(path: Path | None = None) -> str:
    """当前逻辑账号：最近一次**执行成功**的切换账号任务切到的目标。

    从未切换过（没有切换任务，或切换任务尚未成功执行）时用固定默认标识。
    """
    data = load_state(_path(path))
    value = data.get("current_account")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_ACCOUNT_KEY


def set_current_account(account_id: str, path: Path | None = None) -> bool:
    """记录当前逻辑账号（只在切换账号任务**成功**后调用）。

    切换失败或尚未执行不调用本函数，归属就不会提前改变。
    """
    key = normalize_account_id(account_id)
    if not key:
        return False
    data = load_state(_path(path))
    data["current_account"] = key
    return save_state(data, _path(path))


# 切换账号任务「这一次要切到哪个」的暂存。
# 「切换任务是否成功」只有框架知道（tasker sink 的任务级 Succeeded），
# 而「目标是哪个」由切换动作自己读到 —— 两者分开存，成功时才合成归属。
_pending_switch_target: str = ""


def remember_switch_target(account: str) -> str:
    """记下这次切换的目标账号标识（空值用固定默认标识）。

    由「切换账号」动作在选中账号时调用；**不代表切换已经成功** ——
    归属要等任务真的成功后才写（见 `set_current_account`）。
    """
    global _pending_switch_target
    _pending_switch_target = (account or "").strip() or DEFAULT_SWITCH_TARGET
    return _pending_switch_target


def pending_switch_target() -> str:
    """取出（并清空）暂存的切换目标。"""
    global _pending_switch_target
    target = _pending_switch_target
    _pending_switch_target = ""
    return target


def unavailable_stages(account_id: str | None = None, path: Path | None = None) -> set[str]:
    """当前逻辑账号已记录为不可用的主线关卡。"""
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
    """
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
    """当前逻辑账号是否已被标记「跳过均衡刷材料任务」。"""
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
    """
    target = _path(path)
    data = load_state(target)
    bucket = account_bucket(data, account_id)
    stamp = now or _now_str()
    bucket["skip_balanced"] = bool(value)
    bucket["updated_at"] = stamp
    return save_state(data, target)


def clear_all(path: Path | None = None) -> bool:
    """清除**所有逻辑账号**的关卡不可用记录与均衡停用标记。

    GUI「重置全部记录」用：用户明确要求「删除所有记录」，所以清的是所有账号的
    不可用记录与停用标记，不是只清当前账号。

    **当前逻辑账号标识保留** —— 它不是「记录」，只是「现在该用哪一份状态」的归属；
    清掉它会让重置后的运行改用默认桶，而不是玩家实际在用的那个账号。
    """
    target = _path(path)
    data = load_state(target)
    data[STATE_KEY] = {}
    # 复用原子写入（tmp + os.replace）：直接 write_text 若中途出错会留下半截文件，
    # 下次 load_state 读到损坏内容会退化成空状态，连 current_account 都一起丢。
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
