import json
import re
from pathlib import Path

import pytest

from agent.custom.action.warehouse_inventory import WarehouseInventoryScan


def test_items_json_contains_all_rarity_groups() -> None:
    """items.json 材料表包含金/黄/紫/蓝/绿五档稀有度。"""
    with open("data/combat/items.json", encoding="utf-8") as f:
        items = json.load(f)
    assert set(items.keys()) == {"gold", "yellow", "purple", "blue", "green"}
    total = sum(len(v) for v in items.values())
    assert total >= 46


def test_all_balanced_farming_items_have_templates() -> None:
    """智能均衡刷材料的 12 种材料都应存在仓库模板。"""
    with open("data/combat/balanced_farming.json", encoding="utf-8") as f:
        materials = json.load(f)
    for item_id in materials:
        template = Path(f"resource/base/image/Warehouse/Item-{item_id}.png")
        assert template.exists(), f"缺少模板 {template}"


def test_has_template_detects_existing_and_missing() -> None:
    """_has_template 对存在的模板返回 True，对缺失模板返回 False。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    assert scan._has_template("110103")
    assert not scan._has_template("999999")


def test_all_items_json_materials_have_templates() -> None:
    """items.json 全部材料都应存在仓库模板（识别任务可覆盖全量）。"""
    with open("data/combat/items.json", encoding="utf-8") as f:
        items = json.load(f)
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    missing = [item_id for group in items.values() for item_id in group if not scan._has_template(item_id)]
    assert not missing, f"缺少模板的材料: {missing}"


def test_count_parsing_takes_longest_digit_group() -> None:
    """数量解析取最长数字组，忽略噪声。"""
    # 模拟 ocr_text 返回值（带噪声的情况）
    cases = [
        ("123", 123),
        ("1,234", 1234),
        ("12 个噪声 3456", 3456),
        ("", None),
        ("x", None),
    ]
    for text, expected in cases:
        groups = re.findall(r"\d+", text.replace(",", ""))
        if not groups:
            assert expected is None
        else:
            assert int(max(groups, key=len)) == expected


def test_best_count_uses_mode_when_available() -> None:
    """多次读数有众数时取众数。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    assert scan._best_count([31, 3, 3]) == 3  # 装饰条误读 31 出现 1 次
    assert scan._best_count([231, 21, 231]) == 231  # 截断误读 21 出现 1 次
    assert scan._best_count([81, 81, 81]) == 81


def test_best_count_fallback_to_longest() -> None:
    """无众数时取最长位数（截断误读比真值短）。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    assert scan._best_count([231, 21]) == 231
    assert scan._best_count([73, 3]) == 73


def test_action_registered_in_action_modules() -> None:
    """warehouse_inventory 模块在 ACTION_MODULES 注册表中。"""
    from agent.custom.action import ACTION_MODULES

    assert "warehouse_inventory" in ACTION_MODULES


def test_write_snapshot_atomic(tmp_path: Path) -> None:
    """快照原子写入：正式文件内容正确且无 .tmp 残留。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    scan._OUTPUT_PATH = str(tmp_path / "out" / "snapshot.json")
    output = {"updated_at": "2026-08-06 16:00:00", "counts": {"110101": 81}}

    scan._write_snapshot(output)

    target = tmp_path / "out" / "snapshot.json"
    assert json.loads(target.read_text(encoding="utf-8")) == output
    assert list((tmp_path / "out").glob("*.tmp")) == []


def test_write_snapshot_failure_cleans_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """原子写入失败时：清理临时文件、不留下损坏的正式文件、异常原样抛出。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    scan._OUTPUT_PATH = str(tmp_path / "out" / "snapshot.json")

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("agent.custom.action.warehouse_inventory.os.replace", boom)

    with pytest.raises(OSError):
        scan._write_snapshot({"counts": {}})

    assert not (tmp_path / "out" / "snapshot.json").exists()
    assert list((tmp_path / "out").glob("*.tmp")) == []
