"""仓库库存快照（config/warehouse_inventory.json）的读写。

快照按账号分桶存放（与 config/m9a_data.json 的 "bank" 同一范式，见 utils.account_store）：
多账号下 A 号的库存不会被拿去给 B 号做规划。未分桶的旧文件在首次读取时整体搬进当前账号桶，
既有读数不丢。

落盘结构：

```json
{
    "snapshots": {
        "<账号 id>": {
            "updated_at": "2026-10-08 00:00:00",
            "counts": { "110103": 12 },
            "currency_updated_at": "2026-10-08 00:00:00"
        }
    }
}
```
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from utils.account_store import DEFAULT_ACCOUNT_KEY, get_account_bucket, load_json_object, normalize_account_id
from utils.runtime_paths import get_runtime_paths

SNAPSHOT_REL_PATH = "config/warehouse_inventory.json"
# 账号桶在文件里的键名
SNAPSHOT_KEY = "snapshots"


def snapshot_read_path(path: Path | str | None = None) -> Path:
    """快照读路径：用户数据固定落数据目录；显式相对路径同样按数据目录解析，
    绝对路径（测试临时目录）原样使用。"""
    paths = get_runtime_paths()
    if path is None:
        return paths.user_path(SNAPSHOT_REL_PATH)
    candidate = Path(path)
    return candidate if candidate.is_absolute() else paths.user_path(candidate)


def snapshot_write_path(path: Path | str | None = None) -> Path:
    """快照写路径：固定落数据目录（包内只读）；显式绝对路径原样使用。"""
    paths = get_runtime_paths()
    if path is None:
        return paths.config_dir / "warehouse_inventory.json"
    candidate = Path(path)
    return candidate if candidate.is_absolute() else paths.work_root / candidate


def load_snapshot_file(path: Path | str | None = None) -> dict[str, Any]:
    """读取整个快照文件（含账号分桶容器）；文件缺失/损坏时返回空对象。"""
    return load_json_object(snapshot_read_path(path), {})


def snapshot_bucket(data: dict[str, Any], account_id: str | None = None) -> dict[str, Any]:
    """取当前账号的快照桶，必要时就地建好。

    账号 id 未知（未跑过 `RecordID`）时落到 `__default__` 桶；旧版文件把快照字段直接放在
    根上，这里整体搬进当前账号桶，避免升级后既有读数被当成别的账号的数据。
    """
    key = normalize_account_id(account_id) or DEFAULT_ACCOUNT_KEY
    if SNAPSHOT_KEY not in data:
        legacy = dict(data)
        data.clear()
        data[SNAPSHOT_KEY] = {key: legacy} if legacy else {}
    return get_account_bucket(data, SNAPSHOT_KEY, key)


def save_snapshot_file(data: dict[str, Any], path: Path | str | None = None) -> None:
    """原子写入快照文件：先写同目录临时文件，成功后 os.replace 替换正式路径。

    避免中途失败（磁盘满/中断）在目标路径留下损坏的部分 JSON；失败时清理临时文件并原样抛出。
    """
    path = snapshot_write_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
