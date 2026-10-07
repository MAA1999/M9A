import json
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from maa.custom_action import CustomAction
from maa.define import OCRResult

from agent.custom.action import depot_maintain
from agent.custom.action.depot_maintain import (
    DepotCurrencyRead,
    DepotMaintainAccumulate,
    DepotMaintainDone,
    DepotMaintainInit,
    DepotMaintainPlan,
    DepotMaintainRefresh,
    load_target_overrides,
    parse_abbreviated_number,
    parse_gui_candy,
    parse_gui_targets,
    parse_target,
    pick_target,
    resolve_targets,
    runs_for,
    snapshot_counts,
    snapshot_is_fresh,
    write_snapshot_counts,
)
from agent.utils.material_catalog import (
    CatalogError,
    MaterialEntry,
    build_catalog,
    catalog_problems,
    load_catalog,
    parse_stage_code,
)

_FAKE_ARGV = CustomAction.RunArg(None, "", "", "", None, None)  # pyright: ignore[reportArgumentType]

_SAMPLE_RAW: dict[str, Any] = {
    "110103": {"name": "啮咬盒", "stage": "7-26", "level": "Hard"},
    "110203": {"name": "盐封曼德拉", "stage": "3-13", "level": "Hard", "per_run": 2},
}


class _FakeController:
    def post_screencap(self) -> Any:
        return types.SimpleNamespace(wait=lambda: types.SimpleNamespace(get=lambda: "IMG"))


class _FakeContext:
    """最小 context 桩：记录 override_next / override_pipeline / run_task 调用。"""

    def __init__(
        self,
        *,
        dry_run: bool = False,
        drop_report_disabled: bool = False,
        attach: dict[str, Any] | None = None,
        eat_candy: bool = True,
        candy_max_hit: int | None = None,
        ocr_texts: dict[str, str] | None = None,
    ) -> None:
        self.next_overrides: list[list[str]] = []
        self.pipeline_overrides: list[dict[str, Any]] = []
        self.run_tasks: list[str] = []
        self.dry_run = dry_run
        self.drop_report_disabled = drop_report_disabled
        self.attach = attach or {}
        self.eat_candy = eat_candy
        self.candy_max_hit = candy_max_hit
        self.ocr_texts = ocr_texts or {}
        self.tasker = types.SimpleNamespace(controller=_FakeController())

    def get_node_object(self, name: str) -> Any:
        return types.SimpleNamespace(attach=self.attach) if name == depot_maintain.PLAN_NODE else None

    def override_next(self, node_name: str, next_list: list[str]) -> None:
        self.next_overrides.append(next_list)

    def override_pipeline(self, pipeline: dict[str, Any]) -> None:
        self.pipeline_overrides.append(pipeline)

    def run_task(self, entry: str, *args: Any, **kwargs: Any) -> Any:
        self.run_tasks.append(entry)
        return types.SimpleNamespace(status=types.SimpleNamespace(failed=False))

    def run_recognition(self, name: str, image: Any, *args: Any, **kwargs: Any) -> Any:
        text = self.ocr_texts.get(name)
        if text is None:
            return None
        best = OCRResult(box=None, score=0.9, text=text)  # pyright: ignore[reportArgumentType]
        return types.SimpleNamespace(hit=True, box=(0, 0, 1, 1), best_result=best)

    def get_node_data(self, name: str) -> dict[str, Any] | None:
        if name == depot_maintain.DRY_RUN_FLAG_NODE:
            return {"enabled": self.dry_run}
        if name == depot_maintain.DROP_REPORT_NODE:
            return {"enabled": not self.drop_report_disabled}
        if name == depot_maintain.EAT_CANDY_NODE:
            return {"enabled": self.eat_candy}
        if name == depot_maintain.EAT_CANDY_START_NODE:
            node: dict[str, Any] = {}
            if self.candy_max_hit is not None:
                node["max_hit"] = self.candy_max_hit
            return node
        return None


def _argv(param: str) -> CustomAction.RunArg:
    return CustomAction.RunArg(None, "", "", param, None, None)  # pyright: ignore[reportArgumentType]


def _snapshot(
    counts: dict[str, int],
    *,
    age_hours: float = 0.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    stamp = (now or datetime.now()) - timedelta(hours=age_hours)
    return {"updated_at": stamp.strftime(depot_maintain.SNAPSHOT_TS_FORMAT), "counts": counts}


class _FakeDropCore:
    """drop_core 的 `DropRecognitionState` 替身。"""

    drop_index = {"3-13E": [110203], "7-26E": [110103]}

    def __init__(self) -> None:
        self.total_drops: dict[int, int] = {}

    def load_data(self) -> None:
        return None

    def get_level_key(self, stage: str, level: str) -> str:
        return f"{stage}{'E' if level == 'Hard' else 'G'}"


class _PlanHarness:
    """按任务入口 → 规划 → 结算累计的顺序驱动动作，隔离模块级状态。"""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        snapshot: dict[str, Any] | None,
        overrides: dict[str, int] | None = None,
        dry_run: bool = False,
        drop_report_disabled: bool = False,
        attach: dict[str, Any] | None = None,
        eat_candy: bool = True,
        candy_max_hit: int | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.context = _FakeContext(
            dry_run=dry_run,
            drop_report_disabled=drop_report_disabled,
            attach=attach,
            eat_candy=eat_candy,
            candy_max_hit=candy_max_hit,
        )
        self.stops = 0
        sample = raw or _SAMPLE_RAW
        monkeypatch.setattr(depot_maintain, "read_snapshot", lambda path=None: snapshot)
        monkeypatch.setattr(depot_maintain, "load_target_overrides", lambda path=None: overrides or {})
        monkeypatch.setattr(
            depot_maintain, "load_catalog", lambda path=None: build_catalog(sample, source="unit-test")
        )
        monkeypatch.setattr(depot_maintain, "request_combat_stop", self._record_stop)
        monkeypatch.setattr(depot_maintain, "battles_done", lambda: 4)
        DepotMaintainInit().run(self.context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    def _record_stop(self) -> None:
        self.stops += 1

    def install_drop_core(self, monkeypatch: pytest.MonkeyPatch) -> _FakeDropCore:
        fake = _FakeDropCore()
        monkeypatch.setattr(depot_maintain, "_drop_core_available", True)
        monkeypatch.setattr(depot_maintain, "DropRecognitionState", fake)
        return fake

    def plan(self, target: str = '{"target_110103": "100", "target_110203": "100"}') -> CustomAction.RunResult:
        return DepotMaintainPlan().run(self.context, _argv(target))  # pyright: ignore[reportArgumentType]

    def refresh(self) -> CustomAction.RunResult:
        return DepotMaintainRefresh().run(self.context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    def accumulate(self) -> CustomAction.RunResult:
        return DepotMaintainAccumulate().run(self.context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]


# ---------- 关卡代码与材料目录 ----------


def test_parse_stage_code_main_story_pads_stage_number() -> None:
    """主线关卡：章节保留，序号补零到两位。"""
    stage = parse_stage_code("7-6")
    assert (stage.chapter, stage.stage_no, stage.family) == ("7", "06", None)
    assert stage.entry_node == "MainChapter_X"
    assert stage.templates == ("Combat/MainChapter_7Enter.png",)


def test_parse_stage_code_resource_family_from_registry() -> None:
    """资源关卡族：入口节点与识别模板来自注册表。"""
    stage = parse_stage_code("MA-6")
    assert (stage.chapter, stage.stage_no, stage.family) == ("MA", "06", "MA")
    assert stage.entry_node == "ResourceChapter_MA"


def test_parse_stage_code_unknown_family_lists_known() -> None:
    """未登记的关卡族报错并列出已登记族，便于维护时补注册。"""
    with pytest.raises(CatalogError) as excinfo:
        parse_stage_code("ZZ-06")
    message = str(excinfo.value)
    assert "ZZ" in message and "MA" in message


def test_build_catalog_reports_all_problems() -> None:
    """目录问题一次性报出：非法 id、缺 name、非法 level、非法 per_run。"""
    raw = {
        "abc": {"name": "非法 id", "stage": "1-1", "level": "Hard"},
        "110103": {"stage": "1-1", "level": "Hard"},
        "110203": {"name": "非法难度", "stage": "1-1", "level": "Nightmare"},
        "110303": {"name": "非法 per_run", "stage": "1-1", "level": "Hard", "per_run": 0},
    }
    with pytest.raises(CatalogError) as excinfo:
        build_catalog(raw, source="unit-test")
    message = str(excinfo.value)
    assert "unit-test 有 4 处问题" in message
    assert "110303" in message


def test_build_catalog_per_run_is_optional() -> None:
    catalog = build_catalog(_SAMPLE_RAW, source="unit-test")
    assert catalog["110103"].per_run is None
    assert catalog["110203"].per_run == 2


def test_shipped_catalog_matches_resources() -> None:
    """随仓库发布的材料目录必须与图标模板、章节模板、关卡入口节点一致。"""
    problems = catalog_problems(load_catalog())
    assert not problems, problems


# ---------- 目标库存解析与逐材料覆盖 ----------


def test_parse_target_accepts_int_float_and_numeric_string() -> None:
    assert parse_target(30) == 30
    assert parse_target(30.0) == 30
    assert parse_target(" 30 ") == 30


def test_parse_target_rejects_invalid_values() -> None:
    for value in (-1, "-5", "abc", None, True, 30.5, [], {}):
        assert parse_target(value) is None, value


def test_parse_abbreviated_number_handles_suffixes() -> None:
    """升级面板数字是缩写值（K/M），按后缀换算、不假设单位切换阈值，纯数字原样。"""
    assert parse_abbreviated_number("9792K") == 9_792_000
    assert parse_abbreviated_number("3969k") == 3_969_000
    assert parse_abbreviated_number("11588") == 11588
    assert parse_abbreviated_number(" 12,345 ") == 12345
    assert parse_abbreviated_number("9.5M") == 9_500_000


def test_parse_abbreviated_number_rejects_garbage() -> None:
    for text in ("", "abc", "K", "9K9", "1.2.3K"):
        assert parse_abbreviated_number(text) is None, text


def test_write_snapshot_counts_merges_and_keeps_timestamp(tmp_path: Path) -> None:
    """角色页读数合并进快照：只改 counts，不动 updated_at（它表示上次全量扫描时间）。"""
    path = tmp_path / "warehouse_inventory.json"
    path.write_text(json.dumps({"updated_at": "2026-10-08 00:00:00", "counts": {"110103": 5}}), encoding="utf-8")

    assert write_snapshot_counts({"205": 9_792_000, "203": 3_969_000}, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["counts"] == {"110103": 5, "205": 9_792_000, "203": 3_969_000}
    assert data["updated_at"] == "2026-10-08 00:00:00"
    # 角色页读数有自己的时间戳：两套读数各算各的有效期
    assert isinstance(data.get("currency_updated_at"), str)


def test_write_snapshot_counts_creates_missing_snapshot(tmp_path: Path) -> None:
    """快照文件不存在时新建（只勾了微尘/利齿子儿的全新安装也能用）。"""
    path = tmp_path / "new.json"
    assert write_snapshot_counts({"205": 100}, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["counts"] == {"205": 100}
    assert isinstance(data.get("updated_at"), str)


def test_parse_gui_targets_blank_or_missing_means_unset() -> None:
    """GUI 逐材料框：留空/缺失 = 未设置（不刷）；0 = 显式不刷；正整数 = 目标。"""
    catalog = build_catalog(_SAMPLE_RAW, source="unit-test")
    assert parse_gui_targets({"target_110103": "", "target_110203": "0"}, catalog) == {"110203": 0}
    assert parse_gui_targets({"target_110203": "150"}, catalog) == {"110203": 150}


def test_parse_gui_candy_blank_means_unlimited() -> None:
    """GUI 逐材料吃糖次数：留空/缺失 = 不限；0 = 不吃糖；N = 上限；非法值忽略。"""
    catalog = build_catalog(_SAMPLE_RAW, source="unit-test")
    assert parse_gui_candy({"candy_110103": "", "candy_110203": "0"}, catalog) == {"110203": 0}
    assert parse_gui_candy({"candy_110203": "3"}, catalog) == {"110203": 3}
    assert parse_gui_candy({"candy_110203": "abc"}, catalog) == {}


def test_resolve_targets_precedence() -> None:
    """两层优先级：config 文件 > GUI 逐材料框；都没设置按 0（不刷）。"""
    catalog = build_catalog(_SAMPLE_RAW, source="unit-test")
    resolved = resolve_targets(catalog, {"110103": 0, "110203": 300}, {"110103": 500})
    assert resolved == {"110103": 500, "110203": 300}

    assert resolve_targets(catalog, {}, {}) == {"110103": 0, "110203": 0}


def test_plan_excludes_material_with_gui_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """GUI 里给某材料填 0 就不刷它，哪怕它缺口最大。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0, "110203": 90}))
    assert harness.plan('{"target_110103": "0", "target_110203": "100"}').success
    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "3-13"


def test_plan_all_targets_blank_or_zero_falls_back_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有目标留空或填 0 时，退回原有均衡流程。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 1}))
    assert harness.plan('{"target_110103": "", "target_110203": "0"}').success
    assert harness.context.next_overrides == [["BF_EnterWarehouse"]]


def test_plan_depot_disabled_falls_back_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """GUI「库存保持」开关关闭时直接退回原有均衡流程，config 覆盖与缺口都不看。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 1}), overrides={"110103": 500})
    assert harness.plan('{"depot_disabled": true}').success
    assert harness.context.next_overrides == [["BF_EnterWarehouse"]]
    assert harness.context.pipeline_overrides == []


def test_plan_filters_by_selected_materials(monkeypatch: pytest.MonkeyPatch) -> None:
    """GUI 勾选列表非空时只刷勾选的：未勾选的材料即使缺口更大也跳过。"""
    snapshot = _snapshot({"110103": 0, "110203": 90})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot, attach={"mat_110203": True})
    assert harness.plan().success
    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "3-13"


def test_plan_no_selection_means_no_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """一个都没勾 = 不限制，按缺口最大挑（缺口 100 的 110103 胜出）。"""
    snapshot = _snapshot({"110103": 0, "110203": 90})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    assert harness.plan().success
    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "7-26"


def test_plan_selected_material_with_zero_target_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """勾选了但目标填 0 时该材料仍不参与，全部为 0 则退回原有流程。"""
    snapshot = _snapshot({"110103": 10, "110203": 10})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot, attach={"mat_110103": True, "mat_110203": True})
    assert harness.plan('{"target_110103": "0", "target_110203": "0"}').success
    assert harness.context.next_overrides == [["BF_EnterWarehouse"]]


def test_load_target_overrides_missing_or_broken_file(tmp_path: Path) -> None:
    """文件缺失 / JSON 损坏 / 非对象时一律回退空 dict。"""
    assert load_target_overrides(tmp_path / "missing.json") == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{not valid json", encoding="utf-8")
    assert load_target_overrides(broken) == {}

    array = tmp_path / "array.json"
    array.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_target_overrides(array) == {}


def test_load_target_overrides_skips_comment_and_null(tmp_path: Path) -> None:
    """_ 前缀键是注释、null 表示「使用统一目标」，都不作为覆盖值。"""
    path = tmp_path / "targets.json"
    path.write_text(
        json.dumps({"_说明": "注释", "110103": None, "110203": 150, "110303": "x"}),
        encoding="utf-8",
    )
    assert load_target_overrides(path) == {"110203": 150}


def test_ensure_targets_template_is_safe_by_default(tmp_path: Path) -> None:
    """首次运行生成的模板：全为 null，语义上等于「全部使用统一目标」。"""
    path = tmp_path / "depot_maintain_targets.json"
    catalog = build_catalog(_SAMPLE_RAW, source="unit-test")
    depot_maintain.ensure_targets_template(catalog, path)

    assert depot_maintain.load_target_overrides(path) == {}
    written = json.loads(path.read_text(encoding="utf-8"))
    assert set(written) == {"_说明", *catalog}

    first = path.read_text(encoding="utf-8")
    depot_maintain.ensure_targets_template(catalog, path)  # 已存在则不覆盖
    assert path.read_text(encoding="utf-8") == first


def test_load_target_overrides_skips_invalid_values(tmp_path: Path) -> None:
    """合法条目采纳，非法值忽略。"""
    path = tmp_path / "targets.json"
    path.write_text(json.dumps({"110103": 200, "110203": "50", "110303": -1, "110403": "x"}), encoding="utf-8")
    assert load_target_overrides(path) == {"110103": 200, "110203": 50}


# ---------- 仓库快照 ----------


def test_snapshot_is_fresh_respects_ttl() -> None:
    now = datetime(2026, 10, 6, 12, 0, 0)
    assert snapshot_is_fresh(_snapshot({"110103": 1}, age_hours=1, now=now), now=now)
    stale = _snapshot({"110103": 1}, age_hours=depot_maintain.SNAPSHOT_TTL_HOURS + 1, now=now)
    assert not snapshot_is_fresh(stale, now=now)


def test_snapshot_is_fresh_rejects_unparsable_stamp() -> None:
    assert not snapshot_is_fresh(None)
    assert not snapshot_is_fresh({})
    assert not snapshot_is_fresh({"updated_at": "昨天", "counts": {}})
    assert not snapshot_is_fresh({"counts": {"110103": 1}})


def test_snapshot_counts_skips_non_numeric() -> None:
    snapshot = {"counts": {"110103": 5, "110203": "7", "110303": None, "110403": "x"}}
    assert snapshot_counts(snapshot) == {"110103": 5, "110203": 7}


# ---------- 缺口决策 ----------


def _catalog() -> dict[str, MaterialEntry]:
    return build_catalog(_SAMPLE_RAW, source="unit-test")


def test_pick_target_selects_largest_deficit() -> None:
    """110103 缺 80 > 110203 缺 30，挑 110103。"""
    decision = pick_target(_catalog(), {"110103": 20, "110203": 300}, {"110103": 100, "110203": 330})
    assert decision is not None
    entry, deficit = decision
    assert entry.item_id == "110103"
    assert deficit == 80


def test_pick_target_skips_materials_without_reading() -> None:
    """没有库存读数的材料不参与挑选。"""
    decision = pick_target(_catalog(), {"110203": 0}, {"110103": 100, "110203": 100})
    assert decision is not None
    entry, deficit = decision
    assert entry.item_id == "110203"
    assert deficit == 100


def test_pick_target_none_when_all_satisfied() -> None:
    assert pick_target(_catalog(), {"110103": 100, "110203": 500}, {"110103": 100, "110203": 500}) is None


def test_pick_target_unset_or_zero_material_disabled() -> None:
    """目标为 0 或没有目标配置的材料都不参与。"""
    assert pick_target(_catalog(), {"110103": 0, "110203": 0}, {"110103": 0, "110203": 0}) is None
    assert pick_target(_catalog(), {"110103": 0, "110203": 0}, {}) is None


def test_pick_target_uses_resolved_values() -> None:
    """合并后的目标值直接决定缺口：110103 缺 990 > 110203 缺 400。"""
    decision = pick_target(_catalog(), {"110103": 10, "110203": 300}, {"110103": 1000, "110203": 700})
    assert decision is not None
    entry, deficit = decision
    assert entry.item_id == "110103"
    assert deficit == 990


def test_runs_for_uses_per_run_and_defaults_to_one() -> None:
    catalog = _catalog()
    assert runs_for(9, catalog["110203"]) == 5
    assert runs_for(3, catalog["110103"]) == 3
    assert runs_for(0, catalog["110103"]) == 1


# ---------- 规划动作路由 ----------


def test_plan_without_target_falls_back_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有目标都没设置（默认）时退回原有均衡流程。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 1}))
    assert harness.plan("{}").success
    assert harness.context.next_overrides == [["BF_EnterWarehouse"]]
    assert not harness.context.pipeline_overrides


def test_plan_ignores_invalid_material_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """非法目标值只忽略该条并告警，余额为 0 时仍退回原有流程。"""
    harness = _PlanHarness(monkeypatch, snapshot=None)
    assert harness.plan('{"target_110103": "-1"}').success
    assert harness.context.next_overrides == [["BF_EnterWarehouse"]]


def test_plan_refreshes_stale_snapshot_once_then_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """快照过期：先触发一次全量扫描；再次进入规划仍不可用时退回实扫仓库。"""
    stale = _snapshot({"110103": 10, "110203": 10}, age_hours=depot_maintain.SNAPSHOT_TTL_HOURS + 5)
    harness = _PlanHarness(monkeypatch, snapshot=stale)

    assert harness.plan().success
    assert harness.context.next_overrides == [["BF_Refresh"]]

    assert harness.plan().success
    assert harness.context.next_overrides == [["BF_Refresh"], ["BF_EnterWarehouse"]]


def test_plan_enters_combat_with_stage_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """快照新鲜且有缺口：挑缺口最大者（110203 缺 100 > 110103 缺 90），覆盖关卡与次数后进入战斗。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    assert harness.plan().success
    assert harness.context.next_overrides == [["Combat"]]

    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "3-13"
    assert pipeline["SelectCombatStage"]["attach"] == {"level": "Hard", "depot_accumulate": 1}
    assert pipeline["AllIn"]["action"]["param"]["custom_action_param"]["target_count"] == 50
    assert pipeline["TargetCountFinish"] == {"next": ["BF_Plan"]}


def test_plan_reads_multi_material_targets_from_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    """多材料目标走 BF_Plan.attach：两个材料各自的目标都要生效（custom_action_param 会互相覆盖）。"""
    harness = _PlanHarness(
        monkeypatch,
        snapshot=_snapshot({"110103": 0, "110203": 0}),
        attach={
            "mat_110103": True,
            "mat_110203": True,
            "target_110103": "100",
            "target_110203": "60",
            "candy_110103": "",
        },
    )
    assert harness.plan("{}").success  # 目标全部来自 attach，custom_action_param 为空

    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "7-26"


def test_plan_applies_material_candy_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """本轮材料设了吃糖次数：覆盖 EatCandyStart.max_hit，吃糖保持可用。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0, "110203": 0}))
    assert harness.plan('{"target_110103": "100", "candy_110103": "3"}').success
    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["EatCandy"] == {"enabled": True}
    assert pipeline["EatCandyStart"] == {"max_hit": 3}


def test_plan_disables_candy_for_material(monkeypatch: pytest.MonkeyPatch) -> None:
    """某材料吃糖次数填 0：本轮关闭吃糖。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0, "110203": 0}))
    assert harness.plan('{"target_110103": "100", "candy_110103": "0"}').success
    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["EatCandy"] == {"enabled": False}


def test_plan_restores_candy_next_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """上一轮材料的吃糖设置不会泄漏到下一轮：留空即还原全局设置。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0, "110203": 0}), candy_max_hit=5)

    assert harness.plan('{"target_110103": "100", "candy_110103": "0"}').success
    assert harness.context.pipeline_overrides[0]["EatCandy"] == {"enabled": False}

    assert harness.plan('{"target_110103": "100"}').success
    pipeline = harness.context.pipeline_overrides[1]
    assert pipeline["EatCandy"] == {"enabled": True}
    assert pipeline["EatCandyStart"] == {"max_hit": 5}


def test_plan_cannot_enable_candy_when_global_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局「吃糖」关闭时，逐材料设置不能把它打开。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0}), eat_candy=False)
    assert harness.plan('{"target_110103": "100", "candy_110103": "3"}').success
    assert harness.context.pipeline_overrides[0]["EatCandy"] == {"enabled": False}


def test_plan_disables_drop_report_for_unreportable_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """不在掉路上报表内的关卡（新加的材料）不参与上报：本轮关闭 DropRecognition。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0}))
    fake = harness.install_drop_core(monkeypatch)
    fake.drop_index = {"3-13E": [110203]}
    assert harness.plan('{"target_110103": "100"}').success
    assert harness.context.pipeline_overrides[0]["DropRecognition"] == {"enabled": False}


def test_plan_keeps_drop_report_for_table_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """上报表内的关卡（原有材料）照旧参与上报。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0}))
    harness.install_drop_core(monkeypatch)
    assert harness.plan('{"target_110103": "100"}').success
    assert harness.context.pipeline_overrides[0]["DropRecognition"] == {"enabled": True}


def test_plan_report_cannot_enable_when_global_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """全局「掉落统计上报」关闭时，表内关卡也不会被强行打开上报。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 0}), drop_report_disabled=True)
    harness.install_drop_core(monkeypatch)
    assert harness.plan('{"target_110103": "100"}').success
    assert harness.context.pipeline_overrides[0]["DropRecognition"] == {"enabled": False}


# ---------- 角色升级页读数（微尘/利齿子儿） ----------

_CURRENCY_RAW: dict[str, Any] = {
    "205": {"name": "微尘", "stage": "LP-06", "level": "None", "per_run": 12500, "source": "character"},
}


def test_parse_gui_targets_currency_accepts_k_m_suffixes() -> None:
    """货币材料（source=character）的目标框支持 K/M 缩写；仓库材料仍是纯正整数。"""
    catalog = build_catalog({**_SAMPLE_RAW, **_CURRENCY_RAW}, source="unit-test")
    params = {"target_205": "5M", "target_110103": "50K", "target_110203": "300"}
    assert parse_gui_targets(params, catalog) == {"205": 5_000_000, "110203": 300}


def test_currency_read_writes_snapshot_and_returns_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """读到两个缩写数字后合并进快照，并调用返回主界面的子任务。"""
    snapshot = tmp_path / "warehouse_inventory.json"
    snapshot.write_text(json.dumps({"updated_at": "2026-10-08 00:00:00", "counts": {}}), encoding="utf-8")
    monkeypatch.setattr(depot_maintain, "SNAPSHOT_PATH", snapshot)

    context = _FakeContext(ocr_texts={"CI_DustNumber": "9792K", "CI_CoinNumber": "3969K"})
    result = DepotCurrencyRead().run(context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    assert result.success
    assert context.run_tasks == [depot_maintain.CURRENCY_NAV_ENTRY, depot_maintain.CURRENCY_HOME_ENTRY]
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert data["counts"] == {"205": 9_792_000, "203": 3_969_000}


def test_currency_read_fails_without_readings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """两个数字都读不到时明确失败，且仍尝试返回主界面。"""
    snapshot = tmp_path / "warehouse_inventory.json"
    snapshot.write_text(json.dumps({"updated_at": "2026-10-08 00:00:00", "counts": {}}), encoding="utf-8")
    monkeypatch.setattr(depot_maintain, "SNAPSHOT_PATH", snapshot)

    context = _FakeContext()
    result = DepotCurrencyRead().run(context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]

    assert not result.success
    assert context.run_tasks == [depot_maintain.CURRENCY_NAV_ENTRY, depot_maintain.CURRENCY_HOME_ENTRY]
    assert json.loads(snapshot.read_text(encoding="utf-8"))["counts"] == {}


def test_refresh_runs_currency_scan_for_character_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """角色页材料缺读数时只进角色升级页读一次，不跑仓库扫描。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({}), raw=_CURRENCY_RAW)
    assert harness.plan('{"target_205": "100000"}').success
    assert harness.context.next_overrides == [["BF_Refresh"]]
    assert harness.refresh().success
    assert harness.context.run_tasks == ["DepotCurrencyInspect"]


def test_plan_refreshes_currency_when_timestamp_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """货币读数在、但没有货币时间戳（老快照）时补读一次；盖过时间戳后直接进入规划。"""
    snapshot = _snapshot({"205": 9_801_000})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot, raw=_CURRENCY_RAW)

    assert harness.plan('{"target_205": "10000000"}').success
    assert harness.context.next_overrides == [["BF_Refresh"]]
    assert harness.refresh().success
    assert harness.context.run_tasks == ["DepotCurrencyInspect"]

    snapshot["currency_updated_at"] = datetime.now().strftime(depot_maintain.SNAPSHOT_TS_FORMAT)
    assert harness.plan('{"target_205": "10000000"}').success
    assert harness.context.next_overrides[-1] == ["Combat"]


def test_plan_marks_completed_when_all_satisfied_after_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """一轮之后全部达标时，把最后一轮材料记进 completed，收尾总结不再误报「未达标」。"""
    snapshot = _snapshot({"110103": 100, "110203": 0})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)

    assert harness.plan().success
    assert harness.context.next_overrides == [["Combat"]]

    snapshot["counts"]["110203"] = 100  # 估算/自读回写后已达标
    assert harness.plan().success
    assert harness.context.next_overrides[-1] == ["BF_Done"]
    assert depot_maintain._state.completed == ["110203"]


def test_plan_done_when_all_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 100, "110203": 100}))
    assert harness.plan().success
    assert harness.context.next_overrides == [["BF_Done"]]


def test_plan_dry_run_skips_combat(monkeypatch: pytest.MonkeyPatch) -> None:
    """试运行只规划不进入战斗。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}), dry_run=True)
    assert harness.plan().success
    assert harness.context.next_overrides == [["BF_Done"]]
    assert not harness.context.pipeline_overrides


def test_plan_material_override_steers_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """config 文件覆盖优先于 GUI 逐材料目标。"""
    harness = _PlanHarness(
        monkeypatch,
        snapshot=_snapshot({"110103": 500, "110203": 100}),
        overrides={"110103": 1000},
    )
    assert harness.plan('{"target_110103": "10"}').success
    pipeline = harness.context.pipeline_overrides[0]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "7-26"


def test_plan_fails_when_catalog_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    """材料目录非法时明确失败，不静默跳过库存保持。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 1}))

    def _broken(path: Path | None = None) -> dict[str, MaterialEntry]:
        # 抛动作模块捕获的那个类：测试从 agent.* 导入，动作从 utils.* 导入，两者是不同的模块对象
        raise depot_maintain.CatalogError("unit-test 目录损坏")

    monkeypatch.setattr(depot_maintain, "load_catalog", _broken)
    assert not harness.plan().success


def test_refresh_follows_plan_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """刷新动作按规划设置的开关跑子任务；没有缺口时什么都不跑。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 1}))
    assert harness.refresh().success
    assert harness.context.run_tasks == []

    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({}))
    assert harness.plan('{"target_110103": "100"}').success
    assert harness.refresh().success
    assert harness.context.run_tasks == [depot_maintain.WAREHOUSE_SCAN_ENTRY]


def test_done_action_succeeds_after_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """收尾动作在规划后正常返回，不抛异常。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    harness.plan()
    result = DepotMaintainDone().run(harness.context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]
    assert result.success


# ---------- 掉落累计与提前停止 ----------


def test_accumulate_noop_outside_depot_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """未进入库存保持模式时累计节点不累计、不停止，但仍让胜利链继续。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 1}))
    assert harness.accumulate().success
    assert harness.stops == 0
    assert depot_maintain._state.observed == 0
    assert harness.context.next_overrides == [[depot_maintain.VICTORY_CLICK_NODE]]


def test_estimate_mode_when_drop_template_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """没有掉落模板的材料只按每局掉落量估算：不逐局读、不请求提前停止。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    monkeypatch.setattr(depot_maintain, "DROP_TEMPLATE_DIR", tmp_path)
    assert harness.plan().success
    assert depot_maintain._state.read_mode == depot_maintain.READ_ESTIMATE

    monkeypatch.setattr(
        depot_maintain, "read_battle_drops", lambda context, item_id, label="": pytest.fail("估算模式不应读结算页")
    )
    assert harness.accumulate().success
    assert harness.stops == 0
    assert harness.context.next_overrides[-1] == [depot_maintain.VICTORY_CLICK_NODE]


def test_accumulate_reads_drop_core_total_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """有 drop_core 时读它的 total_drops 绝对值，达标后请求批次末停止（只请求一次）。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    fake = harness.install_drop_core(monkeypatch)
    assert harness.plan().success
    assert depot_maintain._state.read_mode == depot_maintain.READ_DROP_CORE

    fake.total_drops = {110203: 30}
    assert harness.accumulate().success
    assert (depot_maintain._state.observed, harness.stops) == (30, 0)
    assert harness.context.next_overrides[-1] == [depot_maintain.VICTORY_CLICK_NODE]

    fake.total_drops = {110203: 120}
    assert harness.accumulate().success
    assert (depot_maintain._state.observed, harness.stops) == (120, 1)

    assert harness.accumulate().success
    assert harness.stops == 1


def test_accumulate_falls_back_when_report_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """掉落统计上报关闭时不能读 drop_core 累计，改用结算页自读。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}), drop_report_disabled=True)
    harness.install_drop_core(monkeypatch)
    assert harness.plan().success
    assert depot_maintain._state.read_mode == depot_maintain.READ_SETTLEMENT


def test_accumulate_self_read_accumulates_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 drop_core 时自读结算页，逐局累加并在达标后停止。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    assert harness.plan().success
    assert depot_maintain._state.read_mode == depot_maintain.READ_SETTLEMENT

    counts = iter([30, 40, 40])
    monkeypatch.setattr(depot_maintain, "read_battle_drops", lambda context, item_id, label="": next(counts))

    assert harness.accumulate().success
    assert (depot_maintain._state.observed, harness.stops) == (30, 0)
    assert harness.accumulate().success
    assert (depot_maintain._state.observed, harness.stops) == (70, 0)
    assert harness.accumulate().success
    assert (depot_maintain._state.observed, harness.stops) == (110, 1)


def test_accumulate_keeps_progress_when_reading_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """结算页读不到时按本局 0 计，不丢已有进度。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    assert harness.plan().success
    scripted = iter([30, None])
    monkeypatch.setattr(depot_maintain, "read_battle_drops", lambda context, item_id, label="": next(scripted))

    harness.accumulate()
    assert harness.accumulate().success
    assert (depot_maintain._state.observed, harness.stops) == (30, 0)


def test_accumulate_writes_snapshot_increment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每局把已确认的掉落增量写回仓库快照。"""
    snapshot = _snapshot({"110103": 10, "110203": 4})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    snapshot_path = tmp_path / "warehouse_inventory.json"
    monkeypatch.setattr(depot_maintain, "SNAPSHOT_PATH", snapshot_path)
    assert harness.plan().success

    scripted = iter([30, 40])
    monkeypatch.setattr(depot_maintain, "read_battle_drops", lambda context, item_id, label="": next(scripted))
    harness.accumulate()
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["counts"]["110203"] == 34

    harness.accumulate()
    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert written["counts"]["110203"] == 74
    assert written["updated_at"] == snapshot["updated_at"]  # 回扫时间戳不动


# ---------- 一次任务连续补多种材料 ----------


def test_round_loop_moves_to_next_material(monkeypatch: pytest.MonkeyPatch) -> None:
    """一轮补满后回到规划，自动改刷下一种缺口材料。"""
    snapshot = _snapshot({"110103": 10, "110203": 0})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    monkeypatch.setattr(depot_maintain, "read_battle_drops", lambda context, item_id, label="": 110)

    assert harness.plan().success
    assert depot_maintain._state.item_id == "110203"
    harness.accumulate()
    assert harness.stops == 1
    assert depot_maintain._state.completed == [depot_maintain.material_label("110203")]

    # 一轮结束（TargetCountFinish → BF_Plan）：快照已写回 110203，改挑 110103
    assert harness.plan().success
    assert depot_maintain._state.rounds == 2
    assert depot_maintain._state.item_id == "110103"
    assert depot_maintain._state.observed == 0  # 新一轮累计清零
    pipeline = harness.context.pipeline_overrides[-1]
    assert pipeline["SelectCombatStage"]["action"]["param"]["custom_action_param"]["stage"] == "7-26"


def test_round_loop_ends_when_no_battle_fought(monkeypatch: pytest.MonkeyPatch) -> None:
    """上一轮没打成（体力不足 / 无法复现）就收尾，不打转。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    assert harness.plan().success

    monkeypatch.setattr(depot_maintain, "battles_done", lambda: 0)
    assert harness.plan().success
    assert harness.context.next_overrides[-1] == ["BF_Done"]


def test_round_loop_ends_at_round_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """达到轮数上限时收尾。"""
    harness = _PlanHarness(monkeypatch, snapshot=_snapshot({"110103": 10, "110203": 0}))
    assert harness.plan().success

    depot_maintain._state.rounds = depot_maintain.MAX_ROUNDS_PER_TASK
    assert harness.plan().success
    assert harness.context.next_overrides[-1] == ["BF_Done"]


def test_estimate_mode_commits_progress_to_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """估算模式按实际局数回写快照，否则多轮循环会反复刷同一种材料。"""
    snapshot = _snapshot({"110103": 10, "110203": 0})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    monkeypatch.setattr(depot_maintain, "DROP_TEMPLATE_DIR", tmp_path)
    monkeypatch.setattr(depot_maintain, "SNAPSHOT_PATH", tmp_path / "snap.json")

    assert harness.plan().success
    assert depot_maintain._state.read_mode == depot_maintain.READ_ESTIMATE
    assert depot_maintain._state.per_run == 2
    assert harness.accumulate().success  # 估算模式空转

    monkeypatch.setattr(depot_maintain, "battles_done", lambda: 4)
    assert harness.plan().success  # 新一轮开始时回写上一轮
    assert snapshot["counts"]["110203"] == 8  # 4 局 × 每局 2 个


def test_estimate_commit_does_not_double_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """收尾节点不会把已经回写过的进度再写一遍。"""
    snapshot = _snapshot({"110103": 10, "110203": 0})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    monkeypatch.setattr(depot_maintain, "DROP_TEMPLATE_DIR", tmp_path)
    monkeypatch.setattr(depot_maintain, "SNAPSHOT_PATH", tmp_path / "snap.json")

    assert harness.plan().success
    monkeypatch.setattr(depot_maintain, "battles_done", lambda: 4)
    assert harness.plan().success
    assert snapshot["counts"]["110203"] == 8

    assert DepotMaintainDone().run(harness.context, _FAKE_ARGV).success  # pyright: ignore[reportArgumentType]
    assert snapshot["counts"]["110203"] == 8


def test_settlement_mode_does_not_commit_estimate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """结算页/drop_core 模式由累计节点写快照，规划节点不再按估算补写。"""
    snapshot = _snapshot({"110103": 10, "110203": 0})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    fake = harness.install_drop_core(monkeypatch)

    assert harness.plan().success
    assert depot_maintain._state.read_mode == depot_maintain.READ_DROP_CORE
    fake.total_drops = {110203: 30}
    harness.accumulate()

    monkeypatch.setattr(depot_maintain, "battles_done", lambda: 4)
    assert harness.plan().success
    assert snapshot["counts"]["110203"] == 30  # 只有累计节点的实际值，无额外补写


def test_round_loop_stops_when_all_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    """两种材料依次补齐后，下一轮规划发现无缺口直接收尾。"""
    snapshot = _snapshot({"110103": 10, "110203": 0})
    harness = _PlanHarness(monkeypatch, snapshot=snapshot)
    monkeypatch.setattr(depot_maintain, "read_battle_drops", lambda context, item_id, label="": 500)

    assert harness.plan().success
    harness.accumulate()
    assert harness.plan().success
    harness.accumulate()
    assert depot_maintain._state.completed == [
        depot_maintain.material_label("110203"),
        depot_maintain.material_label("110103"),
    ]
    assert depot_maintain._state.rounds == 2

    assert harness.plan().success
    assert harness.context.next_overrides[-1] == ["BF_Done"]
    result = DepotMaintainDone().run(harness.context, _FAKE_ARGV)  # pyright: ignore[reportArgumentType]
    assert result.success
