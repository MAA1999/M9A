import json
import types
from pathlib import Path

import pytest
from maa.custom_action import CustomAction

from agent.custom.action.warehouse_inventory import WarehouseInventoryScan, parse_count_from_text

# run() 未使用 argv，测试用最小构造
_FAKE_ARGV = CustomAction.RunArg(None, "", "", "", None, None)  # pyright: ignore[reportArgumentType]


class _FakeController:
    """最小 controller 桩：记录滑动、返回固定截图。"""

    def __init__(self) -> None:
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self._img: object = [[0]]

    def post_swipe(self, x: int, y1: int, x2: int, y2: int, duration: int) -> "_FakeController":
        self.swipes.append((x, y1, x2, y2, duration))
        return self

    def post_screencap(self) -> "_FakeController":
        return self

    def wait(self) -> "_FakeController":
        return self

    def get(self) -> object:
        return self._img


class _FakeContext:
    """最小 context 桩：仅提供 run() 依赖的 tasker.controller。"""

    def __init__(self) -> None:
        self.tasker = types.SimpleNamespace(controller=_FakeController())


def _make_scan(tmp_path: Path, items: dict[str, dict[str, dict[str, str]]]) -> WarehouseInventoryScan:
    """构造指向 tmp 路径的 scan 实例，并写入 items.json。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    scan._ITEMS_PATH = str(tmp_path / "items.json")
    scan._OUTPUT_PATH = str(tmp_path / "out.json")
    (tmp_path / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return scan


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
    """数量解析（parse_count_from_text）取最长数字组，忽略噪声。

    直接覆盖 _recognize_item 使用的同一实现。
    """
    cases = [
        ("123", 123),
        ("1,234", 1234),
        ("12 个噪声 3456", 3456),
        ("", None),
        ("x", None),
    ]
    for text, expected in cases:
        assert parse_count_from_text(text) == expected


def test_best_count_uses_mode_when_available() -> None:
    """多次读数有众数时取众数。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    assert scan._best_count([31, 3, 3]) == 3  # 装饰条误读 31 出现 1 次
    assert scan._best_count([231, 21, 231]) == 231  # 截断误读 21 出现 1 次
    assert scan._best_count([81, 81, 81]) == 81


def test_best_count_fallback_to_min() -> None:
    """无众数时取最小值（消除装饰条并入的读大误读）。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    assert scan._best_count([1, 11]) == 1  # 金羊毛：装饰条把 1 读成 11
    assert scan._best_count([3, 31]) == 3  # 双蛇权杖：装饰条把 3 读成 31
    assert scan._best_count([73, 3]) == 3  # 无众数一律取最小


def test_action_registered_in_action_modules() -> None:
    """warehouse_inventory 模块在 ACTION_MODULES 注册表中。"""
    from agent.custom.action import ACTION_MODULES

    assert "warehouse_inventory" in ACTION_MODULES


def test_default_output_path_is_outside_hot_update_data() -> None:
    """仓库快照默认写入 config，避免与可热更新的 data 资源混放。"""
    assert WarehouseInventoryScan._OUTPUT_PATH == "config/warehouse_inventory.json"


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
    """原子写入失败时：清理临时文件、不破坏已存在的正式文件、异常原样抛出。"""
    scan = WarehouseInventoryScan.__new__(WarehouseInventoryScan)
    scan._OUTPUT_PATH = str(tmp_path / "out" / "snapshot.json")
    target = tmp_path / "out" / "snapshot.json"
    # 预置一份旧快照：os.replace 失败时旧数据必须原样保留
    old_content = '{"updated_at": "old-snapshot", "counts": {"110101": 1}}'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(old_content, encoding="utf-8")

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("agent.custom.action.warehouse_inventory.os.replace", boom)

    with pytest.raises(OSError):
        scan._write_snapshot({"counts": {}})

    assert target.read_text(encoding="utf-8") == old_content
    assert list((tmp_path / "out").glob("*.tmp")) == []


def test_run_fails_when_items_json_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run() 在 items.json 无法解析时返回 success=False。"""
    scan = _make_scan(tmp_path, {})
    (tmp_path / "items.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("agent.custom.action.warehouse_inventory.time.sleep", lambda s: None)

    result = scan.run(_FakeContext(), _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    assert result.success is False


def test_run_fails_when_no_templates_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run() 在没有任何模板可用时返回 success=False。"""
    scan = _make_scan(tmp_path, {"gold": {"111004": {"name": "分别善恶之果"}}})
    monkeypatch.setattr("agent.custom.action.warehouse_inventory.time.sleep", lambda s: None)
    monkeypatch.setattr(scan, "_has_template", lambda item_id: False)

    result = scan.run(_FakeContext(), _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    assert result.success is False


def test_run_fails_when_no_counts_produced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run() 在没有任何材料读到数量时返回 success=False。"""
    scan = _make_scan(tmp_path, {"gold": {"111004": {"name": "分别善恶之果"}}})
    monkeypatch.setattr("agent.custom.action.warehouse_inventory.time.sleep", lambda s: None)
    monkeypatch.setattr(scan, "_has_template", lambda item_id: True)

    def icon_found_but_unreadable(context: _FakeContext, img: object, item_id: str) -> tuple[bool, int | None]:
        return True, None

    monkeypatch.setattr(scan, "_recognize_item", icon_found_but_unreadable)

    result = scan.run(_FakeContext(), _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    assert result.success is False


def test_run_separates_counts_skipped_and_writes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run() 正确划分 counts（读数/未找到=0）与 skipped（读到图标但数量失败），并写出快照。"""
    items = {
        "gold": {"111004": {"name": "分别善恶之果"}},
        "yellow": {"110104": {"name": "床下怪物"}},
        "blue": {"110102": {"name": "液化战栗"}},
    }
    scan = _make_scan(tmp_path, items)
    monkeypatch.setattr("agent.custom.action.warehouse_inventory.time.sleep", lambda s: None)
    monkeypatch.setattr(scan, "_has_template", lambda item_id: True)

    def fake_recognize(context: _FakeContext, img: object, item_id: str) -> tuple[bool, int | None]:
        if item_id == "111004":
            return True, 5  # 正常读到数量
        if item_id == "110104":
            return True, None  # 图标找到但数量识别失败 → skipped
        return False, None  # 110102 从未匹配到 → counts=0

    monkeypatch.setattr(scan, "_recognize_item", fake_recognize)

    result = scan.run(_FakeContext(), _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    assert result.success is True
    output = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert isinstance(output["updated_at"], str)
    # 顺序与 items.json 一致（按稀有度）
    assert list(output["counts"].keys()) == ["111004", "110102"]
    assert output["counts"] == {"111004": 5, "110102": 0}
    assert output["skipped"] == ["110104"]
    assert list(output["materials"].keys()) == ["111004", "110104", "110102"]
    assert output["materials"]["111004"] == {"name": "分别善恶之果", "rarity": "gold"}
