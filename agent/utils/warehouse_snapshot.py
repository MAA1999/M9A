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

SNAPSHOT_PATH = Path("config/warehouse_inventory.json")
# 账号桶在文件里的键名
SNAPSHOT_KEY = "snapshots"


def load_snapshot_file(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    """读取整个快照文件（含账号分桶容器）；文件缺失/损坏时返回空对象。"""
    return load_json_object(path, {})


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


def save_snapshot_file(data: dict[str, Any], path: Path = SNAPSHOT_PATH) -> None:
    """原子写入快照文件：先写同目录临时文件，成功后 os.replace 替换正式路径。

    避免中途失败（磁盘满/中断）在目标路径留下损坏的部分 JSON；失败时清理临时文件并原样抛出。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
