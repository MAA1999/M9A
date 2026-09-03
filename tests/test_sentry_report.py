import io
from pathlib import Path
from typing import Any

import pytest

from tools.sentry import cli, report_common, task_failure_report, task_trend_report


def span_row(**values: Any) -> dict[str, Any]:
    return values


class TestM9AReleaseVersionKey:
    def test_parses_embedded_stable_version(self) -> None:
        assert report_common.m9a_release_version_key("MXU@2.4.5+m9a@v4.7.1") == (4, 7, 1, 2, 0)
        assert report_common.m9a_release_version_key("m9a@v4.7.1") == (4, 7, 1, 2, 0)

    def test_parses_embedded_beta_version(self) -> None:
        assert report_common.m9a_release_version_key("MFA@v2.16.1-beta.3+m9a@v4.7.0-beta.1") == (4, 7, 0, 0, 1)

    def test_rejects_release_without_m9a_suffix(self) -> None:
        assert report_common.m9a_release_version_key("MXU@2.4.5") is None
        assert report_common.m9a_release_version_key("MXU@2.4.5+m9a@v4.7.1+extra") is None
        assert report_common.m9a_release_version_key("MXU@2.4.5+m9a@abc") is None


class TestSelectLatestReportedRelease:
    def test_requires_finalized_release_with_deploy(self) -> None:
        rows = [
            {
                "version": "MXU@2.4.5+m9a@v4.7.1",
                "dateReleased": "2026-09-01T00:00:00Z",
                "deployCount": 0,
            },
            {
                "version": "MFA@v2.16.0+m9a@v4.7.0",
                "dateReleased": "2026-08-27T10:30:34Z",
                "deployCount": 1,
            },
        ]
        assert report_common.select_latest_reported_m9a_release(rows) == "MFA@v2.16.0+m9a@v4.7.0"

    def test_returns_none_without_qualifying_release(self) -> None:
        rows: list[dict[str, Any]] = [
            {"version": "MXU@2.4.5+m9a@v4.7.1", "dateReleased": None, "deployCount": 0},
            {"version": "MXU@2.4.2+m9a@v4.7.0", "dateCreated": "2026-08-30T13:00:00Z"},
        ]
        assert report_common.select_latest_reported_m9a_release(rows) is None


class TestSelectLatestSpansRelease:
    def test_picks_highest_version_above_user_threshold(self) -> None:
        rows = [
            span_row(release="MFA@v2.16.0+m9a@v4.7.0", **{"count_unique(user)": 500, "count_unique(trace)": 900}),
            span_row(release="MXU@2.4.5+m9a@v4.7.1", **{"count_unique(user)": 20, "count_unique(trace)": 30}),
            span_row(release="MXU@0.1.0+m9a@v4.7.1", **{"count_unique(user)": 3, "count_unique(trace)": 5}),
            span_row(release="MXU@2.4.2", **{"count_unique(user)": 800, "count_unique(trace)": 900}),
        ]
        assert report_common.select_latest_m9a_release(rows) == "MXU@2.4.5+m9a@v4.7.1"

    def test_raises_when_no_release_meets_threshold(self) -> None:
        rows = [span_row(release="MXU@2.4.5+m9a@v4.7.1", **{"count_unique(user)": 3, "count_unique(trace)": 5})]
        with pytest.raises(RuntimeError, match="显式指定"):
            report_common.select_latest_m9a_release(rows)


class TestBuildTaskRows:
    def test_aggregates_status_columns_and_sorts_by_failures(self) -> None:
        totals = [
            span_row(**{"span.description": "领取奖励", "count_unique(trace)": 100}),
            span_row(**{"span.description": "mfa.task_run", "count_unique(trace)": 200}),
        ]
        statuses = [
            span_row(**{"span.description": "领取奖励", "span.status": "ok", "count_unique(trace)": 90}),
            span_row(**{"span.description": "领取奖励", "span.status": "internal_error", "count_unique(trace)": 7}),
            span_row(**{"span.description": "领取奖励", "span.status": "cancelled", "count_unique(trace)": 3}),
            span_row(**{"span.description": "mfa.task_run", "span.status": "ok", "count_unique(trace)": 180}),
            span_row(
                **{"span.description": "mfa.task_run", "span.status": "internal_error", "count_unique(trace)": 20}
            ),
        ]
        rows, markers = task_failure_report.build_task_rows(totals, statuses, None)
        assert [(row.task, row.total, row.failed, row.cancelled) for row in rows] == [
            ("mfa.task_run", 200, 20, 0),
            ("领取奖励", 100, 7, 3),
        ]
        assert markers == []
        assert rows[0].failure_rate == pytest.approx(0.1)
        assert rows[1].failure_rate == pytest.approx(0.07)

    def test_status_counts_stay_separate_per_status(self) -> None:
        totals = [span_row(**{"span.description": "收取荒原", "count_unique(trace)": 10})]
        statuses = [
            span_row(**{"span.description": "收取荒原", "span.status": "ok", "count_unique(trace)": 9}),
            span_row(**{"span.description": "收取荒原", "span.status": "internal_error", "count_unique(trace)": 2}),
        ]
        rows, markers = task_failure_report.build_task_rows(totals, statuses, None)
        assert rows[0].total == 10
        assert rows[0].failed == 2
        assert rows[0].failure_rate == pytest.approx(0.2)
        assert markers == []

    def test_failure_only_descriptions_become_markers(self) -> None:
        totals = [
            span_row(**{"span.description": "领取奖励", "count_unique(trace)": 100}),
            span_row(**{"span.description": "ReturnMain", "count_unique(trace)": 131}),
            span_row(**{"span.description": "controller_initialization_failed", "count_unique(trace)": 2231}),
        ]
        statuses = [
            span_row(**{"span.description": "领取奖励", "span.status": "ok", "count_unique(trace)": 95}),
            span_row(**{"span.description": "领取奖励", "span.status": "internal_error", "count_unique(trace)": 5}),
            span_row(**{"span.description": "ReturnMain", "span.status": "internal_error", "count_unique(trace)": 131}),
            span_row(
                **{
                    "span.description": "controller_initialization_failed",
                    "span.status": "internal_error",
                    "count_unique(trace)": 2231,
                }
            ),
        ]
        rows, markers = task_failure_report.build_task_rows(totals, statuses, None)
        assert [row.task for row in rows] == ["领取奖励"]
        assert [(row.task, row.total) for row in markers] == [
            ("controller_initialization_failed", 2231),
            ("ReturnMain", 131),
        ]

    def test_aggregates_across_channel_releases_for_same_version(self) -> None:
        mfa = "MFA@v2.16.1-beta.3+m9a@v4.7.1"
        mxu = "MXU@2.4.5+m9a@v4.7.1"
        totals = [
            span_row(**{"span.description": "领取奖励", "release": mfa, "count_unique(trace)": 100}),
            span_row(**{"span.description": "领取奖励", "release": mxu, "count_unique(trace)": 50}),
            span_row(
                **{"span.description": "领取奖励", "release": "MFA@v2.16.0+m9a@v4.7.0", "count_unique(trace)": 999}
            ),
        ]
        statuses = [
            span_row(
                **{
                    "span.description": "领取奖励",
                    "release": mfa,
                    "span.status": "internal_error",
                    "count_unique(trace)": 5,
                }
            ),
            span_row(
                **{"span.description": "领取奖励", "release": mxu, "span.status": "ok", "count_unique(trace)": 45}
            ),
        ]
        rows, _ = task_failure_report.build_task_rows(totals, statuses, (4, 7, 1, 2, 0))
        assert rows[0].total == 150
        assert rows[0].failed == 5
        assert rows[0].failure_rate == pytest.approx(5 / 150)

    def test_sorts_by_rate_and_respects_limit(self) -> None:
        totals = [
            span_row(**{"span.description": "LowRate", "count_unique(trace)": 100}),
            span_row(**{"span.description": "HighRate", "count_unique(trace)": 100}),
        ]
        statuses = [
            span_row(**{"span.description": "LowRate", "span.status": "internal_error", "count_unique(trace)": 5}),
            span_row(**{"span.description": "LowRate", "span.status": "ok", "count_unique(trace)": 95}),
            span_row(**{"span.description": "HighRate", "span.status": "internal_error", "count_unique(trace)": 30}),
            span_row(**{"span.description": "HighRate", "span.status": "ok", "count_unique(trace)": 70}),
        ]
        tasks, _ = task_failure_report.build_task_rows(totals, statuses, None, sort="rate", limit=1)
        assert len(tasks) == 1
        assert tasks[0].task == "HighRate"
        assert tasks[0].failure_rate == pytest.approx(0.3)


class TestBuildReleaseRows:
    def test_aggregates_by_release_string_and_sorts_by_total(self) -> None:
        totals = [
            span_row(release="MFA@v2.16.1-beta.3+m9a@v4.7.1", **{"count_unique(trace)": 500}),
            span_row(release="MXU@2.4.5+m9a@v4.7.1", **{"count_unique(trace)": 200}),
        ]
        failures = [span_row(release="MXU@2.4.5+m9a@v4.7.1", **{"count_unique(trace)": 50})]
        rows = task_failure_report.build_release_rows(totals, failures, (4, 7, 1, 2, 0))
        assert [(row.release, row.total, row.failed) for row in rows] == [
            ("MFA@v2.16.1-beta.3+m9a@v4.7.1", 500, 0),
            ("MXU@2.4.5+m9a@v4.7.1", 200, 50),
        ]
        assert rows[1].failure_rate == pytest.approx(0.25)

    def test_drops_releases_embedding_other_m9a_versions(self) -> None:
        totals = [
            span_row(release="MFA@v2.16.1-beta.3+m9a@v4.7.1", **{"count_unique(trace)": 500}),
            span_row(release="MFA@v2.16.0+m9a@v4.7.0", **{"count_unique(trace)": 400}),
            span_row(release="MXU@2.4.2", **{"count_unique(trace)": 300}),
        ]
        rows = task_failure_report.build_release_rows(totals, [], (4, 7, 1, 2, 0))
        assert [row.release for row in rows] == ["MFA@v2.16.1-beta.3+m9a@v4.7.1"]

    def test_keeps_all_releases_without_version_key(self) -> None:
        totals = [
            span_row(release="MFA@v2.16.1-beta.3+m9a@v4.7.1", **{"count_unique(trace)": 500}),
            span_row(release="MFA@v2.16.0+m9a@v4.7.0", **{"count_unique(trace)": 400}),
        ]
        rows = task_failure_report.build_release_rows(totals, [], None)
        assert len(rows) == 2


class TestConsoleTable:
    def test_aligns_cjk_wide_characters(self) -> None:
        output = io.StringIO()
        report_common.write_console_table(
            ("任务/节点", "失败率"),
            [("收取荒原", "5.0%"), ("StartUp", "21.4%")],
            output,
            right_aligned={1},
        )
        lines = output.getvalue().splitlines()
        widths = {report_common.display_width(line) for line in lines}
        assert len(widths) == 1
        assert "│ 收取荒原" in lines[3]
        assert "│   5.0%" in lines[3]


class TestFormatRate:
    def test_formats_percentages_and_missing_samples(self) -> None:
        assert report_common.format_rate(0.052) == "5.2%"
        assert report_common.format_rate(None) == "暂无样本"


class TestCli:
    def test_lists_task_failure_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main([]) == 0
        out = capsys.readouterr().out
        assert "task-failure" in out
        assert "task-trend" in out

    def test_rejects_unknown_report(self) -> None:
        with pytest.raises(SystemExit):
            cli.main(["no-such-report"])

    def test_help_options(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["-h"]) == 0
        out = capsys.readouterr().out
        assert "usage: python -m tools.sentry.cli [-h]" in out
        assert "task-failure" in out
        assert "task-trend" in out

        assert cli.main(["--help"]) == 0
        assert "usage: python -m tools.sentry.cli [-h]" in capsys.readouterr().out


class TestFormatRateWithDelta:
    def test_formats_positive_delta(self) -> None:
        assert task_trend_report.format_rate_with_delta(0.07, 1.4) == "7.0% (+1.4pp)"

    def test_formats_negative_delta(self) -> None:
        assert task_trend_report.format_rate_with_delta(0.056, -1.4) == "5.6% (-1.4pp)"

    def test_formats_zero_delta(self) -> None:
        assert task_trend_report.format_rate_with_delta(0.056, 0.0) == "5.6% (0.0pp)"

    def test_formats_without_delta(self) -> None:
        assert task_trend_report.format_rate_with_delta(0.056, None) == "5.6%"

    def test_formats_missing_sample(self) -> None:
        assert task_trend_report.format_rate_with_delta(None, None) == "暂无样本"


class TestDiscoverVersions:
    def test_filters_prerelease_by_default(self) -> None:
        rows = [
            span_row(release="MFA@v2.16.1-beta.3+m9a@v4.7.1", **{"count_unique(user)": 100}),
            span_row(release="MFA@v2.16.0+m9a@v4.7.0-beta.1", **{"count_unique(user)": 50}),
            span_row(release="MFA@v2.16.0+m9a@v4.7.0", **{"count_unique(user)": 80}),
            span_row(release="MFA@v2.15.2+m9a@v4.6.2", **{"count_unique(user)": 90}),
        ]
        versions = task_trend_report.discover_versions(rows, count=2, include_prerelease=False)
        assert versions == ["v4.7.1", "v4.7.0", "v4.6.2"]

    def test_includes_prerelease_when_flag_set(self) -> None:
        rows = [
            span_row(release="MFA@v2.16.1-beta.3+m9a@v4.7.1", **{"count_unique(user)": 100}),
            span_row(release="MFA@v2.16.0+m9a@v4.7.0-beta.1", **{"count_unique(user)": 50}),
            span_row(release="MFA@v2.16.0+m9a@v4.7.0", **{"count_unique(user)": 80}),
        ]
        versions = task_trend_report.discover_versions(rows, count=2, include_prerelease=True)
        assert versions == ["v4.7.1", "v4.7.0", "v4.7.0-beta.1"]


class TestBuildTrendReport:
    def test_calculates_cross_version_deltas(self) -> None:
        mfa_v471 = "MFA@v2.16.1-beta.3+m9a@v4.7.1"
        mxu_v471 = "MXU@2.4.5+m9a@v4.7.1"
        mfa_v470 = "MFA@v2.16.0+m9a@v4.7.0"
        mfa_v462 = "MFA@v2.15.2+m9a@v4.6.2"

        totals = [
            span_row(**{"span.description": "领取奖励", "release": mfa_v471, "count_unique(trace)": 60}),
            span_row(**{"span.description": "领取奖励", "release": mxu_v471, "count_unique(trace)": 40}),
            span_row(**{"span.description": "领取奖励", "release": mfa_v470, "count_unique(trace)": 100}),
            span_row(**{"span.description": "领取奖励", "release": mfa_v462, "count_unique(trace)": 100}),
            span_row(**{"span.description": "ReturnMain", "release": mfa_v471, "count_unique(trace)": 20}),
        ]
        statuses = [
            span_row(
                **{
                    "span.description": "领取奖励",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 5,
                }
            ),
            span_row(
                **{
                    "span.description": "领取奖励",
                    "release": mfa_v471,
                    "span.status": "ok",
                    "count_unique(trace)": 95,
                }
            ),
            span_row(
                **{
                    "span.description": "领取奖励",
                    "release": mfa_v470,
                    "span.status": "internal_error",
                    "count_unique(trace)": 10,
                }
            ),
            span_row(
                **{
                    "span.description": "领取奖励",
                    "release": mfa_v462,
                    "span.status": "internal_error",
                    "count_unique(trace)": 8,
                }
            ),
            span_row(
                **{
                    "span.description": "ReturnMain",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 20,
                }
            ),
        ]

        report = task_trend_report.build_trend_report(
            totals,
            statuses,
            ["v4.7.1", "v4.7.0", "v4.6.2"],
            min_latest_runs=10,
        )
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.task == "领取奖励"
        assert row.latest_total == 100
        assert row.version_rates["v4.7.1"] == pytest.approx(0.05)
        assert row.version_rates["v4.7.0"] == pytest.approx(0.10)
        assert row.version_rates["v4.6.2"] == pytest.approx(0.08)
        assert row.version_deltas["v4.7.1"] == pytest.approx(-5.0)
        assert row.version_deltas["v4.7.0"] == pytest.approx(2.0)
        assert row.version_deltas["v4.6.2"] is None

    def test_single_task_filter_builds_detailed_stats(self) -> None:
        mfa_v471 = "MFA@v2.16.1-beta.3+m9a@v4.7.1"
        mfa_v470 = "MFA@v2.16.0+m9a@v4.7.0"
        totals = [
            span_row(**{"span.description": "常规作战", "release": mfa_v471, "count_unique(trace)": 50}),
            span_row(**{"span.description": "常规作战", "release": mfa_v470, "count_unique(trace)": 50}),
        ]
        statuses = [
            span_row(
                **{
                    "span.description": "常规作战",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 10,
                }
            ),
            span_row(
                **{
                    "span.description": "常规作战",
                    "release": mfa_v471,
                    "span.status": "ok",
                    "count_unique(trace)": 40,
                }
            ),
            span_row(
                **{
                    "span.description": "常规作战",
                    "release": mfa_v470,
                    "span.status": "internal_error",
                    "count_unique(trace)": 5,
                }
            ),
        ]
        report = task_trend_report.build_trend_report(
            totals,
            statuses,
            ["v4.7.1", "v4.7.0"],
            task_filter="常规作战",
        )
        assert report.detailed_task_stats is not None
        assert len(report.detailed_task_stats) == 2
        assert report.detailed_task_stats[0].version == "v4.7.1"
        assert report.detailed_task_stats[0].failure_rate == pytest.approx(0.2)
        assert report.detailed_task_stats[0].delta_pp == pytest.approx(10.0)

    def test_sorts_by_rate_and_respects_limit(self) -> None:
        mfa_v471 = "MFA@v2.16.1-beta.3+m9a@v4.7.1"
        mfa_v470 = "MFA@v2.16.0+m9a@v4.7.0"
        totals = [
            span_row(**{"span.description": "LowRate", "release": mfa_v471, "count_unique(trace)": 100}),
            span_row(**{"span.description": "LowRate", "release": mfa_v470, "count_unique(trace)": 100}),
            span_row(**{"span.description": "HighRate", "release": mfa_v471, "count_unique(trace)": 100}),
            span_row(**{"span.description": "HighRate", "release": mfa_v470, "count_unique(trace)": 100}),
        ]
        statuses = [
            span_row(
                **{
                    "span.description": "LowRate",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 2,
                }
            ),
            span_row(
                **{
                    "span.description": "LowRate",
                    "release": mfa_v471,
                    "span.status": "ok",
                    "count_unique(trace)": 98,
                }
            ),
            span_row(
                **{
                    "span.description": "HighRate",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 25,
                }
            ),
            span_row(
                **{
                    "span.description": "HighRate",
                    "release": mfa_v471,
                    "span.status": "ok",
                    "count_unique(trace)": 75,
                }
            ),
        ]
        report = task_trend_report.build_trend_report(
            totals,
            statuses,
            ["v4.7.1", "v4.7.0"],
            sort="rate",
            limit=1,
        )
        assert len(report.rows) == 1
        assert report.rows[0].task == "HighRate"
        assert report.rows[0].version_rates["v4.7.1"] == pytest.approx(0.25)

    def test_sorts_by_delta_descending(self) -> None:
        mfa_v471 = "MFA@v2.16.1-beta.3+m9a@v4.7.1"
        mfa_v470 = "MFA@v2.16.0+m9a@v4.7.0"
        totals = [
            span_row(**{"span.description": "Improved", "release": mfa_v471, "count_unique(trace)": 100}),
            span_row(**{"span.description": "Improved", "release": mfa_v470, "count_unique(trace)": 100}),
            span_row(**{"span.description": "Regressed", "release": mfa_v471, "count_unique(trace)": 100}),
            span_row(**{"span.description": "Regressed", "release": mfa_v470, "count_unique(trace)": 100}),
        ]
        statuses = [
            span_row(
                **{
                    "span.description": "Improved",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 2,
                }
            ),
            span_row(
                **{
                    "span.description": "Improved",
                    "release": mfa_v471,
                    "span.status": "ok",
                    "count_unique(trace)": 98,
                }
            ),
            span_row(
                **{
                    "span.description": "Improved",
                    "release": mfa_v470,
                    "span.status": "internal_error",
                    "count_unique(trace)": 10,
                }
            ),
            span_row(
                **{
                    "span.description": "Regressed",
                    "release": mfa_v471,
                    "span.status": "internal_error",
                    "count_unique(trace)": 20,
                }
            ),
            span_row(
                **{
                    "span.description": "Regressed",
                    "release": mfa_v471,
                    "span.status": "ok",
                    "count_unique(trace)": 80,
                }
            ),
            span_row(
                **{
                    "span.description": "Regressed",
                    "release": mfa_v470,
                    "span.status": "internal_error",
                    "count_unique(trace)": 5,
                }
            ),
        ]
        report = task_trend_report.build_trend_report(
            totals,
            statuses,
            ["v4.7.1", "v4.7.0"],
            sort="delta",
        )
        assert len(report.rows) == 2
        # Regressed: v4.7.1 (20%) - v4.7.0 (5%) = +15pp
        # Improved: v4.7.1 (2%) - v4.7.0 (10%) = -8pp
        assert report.rows[0].task == "Regressed"
        assert report.rows[1].task == "Improved"


class TestConfig:
    def test_loads_config_from_json(self) -> None:
        from tools.sentry.config import CONFIG

        assert CONFIG.target == "m9a/gui"
        assert CONFIG.project_prefix == "m9a"
        assert "mfa.task_run" in CONFIG.task_run_spans

    def test_raises_when_config_file_not_found(self, tmp_path: Path) -> None:
        from tools.sentry.config import load_config

        nonexistent = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            load_config(nonexistent)

    def test_raises_when_missing_required_fields(self, tmp_path: Path) -> None:
        from tools.sentry.config import load_config

        bad_file = tmp_path / "bad_config.json"
        bad_file.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="缺少必填字段"):
            load_config(bad_file)

    def test_generic_version_extraction_for_other_projects(self) -> None:
        import re

        # MaaEnd standard release: MaaEnd@v2.1.0-beta.2
        prefix = "MaaEnd"
        pattern = re.compile(
            rf"(?:^|[+/]){re.escape(prefix)}@v?(\d+)\.(\d+)\.(\d+)(?:-(beta|rc)\.(\d+))?$",
            re.IGNORECASE,
        )
        match = pattern.search("MaaEnd@v2.1.0-beta.2")
        assert match is not None
        assert match.groups() == ("2", "1", "0", "beta", "2")

        match_release = pattern.search("MaaEnd@v2.1.0")
        assert match_release is not None
        assert match_release.groups() == ("2", "1", "0", None, None)
