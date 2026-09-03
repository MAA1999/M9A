import io
import json
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

    def test_sentry_report_prerelease_rank_ordering(self) -> None:
        key_alpha = (4, 7, 0, report_common.PRERELEASE_RANKS["alpha"], 1)
        key_beta = (4, 7, 0, report_common.PRERELEASE_RANKS["beta"], 1)
        key_rc = (4, 7, 0, report_common.PRERELEASE_RANKS["rc"], 1)
        key_stable = (4, 7, 0, report_common.STABLE_RELEASE_RANK, 0)
        assert key_alpha < key_beta < key_rc < key_stable

    def test_sentry_report_rejects_unknown_prerelease_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import re

        custom_pattern = re.compile(r"m9a@v(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)\.(\d+))?")
        monkeypatch.setattr(report_common, "RELEASE_PATTERN", custom_pattern)
        # 支持的预发布标签
        assert report_common.release_version_key("m9a@v4.7.1-beta.2") == (4, 7, 1, 0, 2)
        assert report_common.release_version_key("m9a@v4.7.1-rc.1") == (4, 7, 1, 1, 1)
        assert report_common.release_version_key("m9a@v4.7.1-alpha.3") == (4, 7, 1, -1, 3)
        # 未知标签不应静默获得 beta 的 rank 0，必须返回 None
        assert report_common.release_version_key("m9a@v4.7.1-preview.1") is None
        assert report_common.release_version_key("m9a@v4.7.1-dev.5") is None


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

    def test_sentry_report_raises_when_collection_fields_not_string_list(self, tmp_path: Path) -> None:
        from tools.sentry.config import load_config

        # 字符串而非列表
        bad_str = tmp_path / "bad_str.json"
        bad_str.write_text('{"target": "t", "project_prefix": "p", "task_run_spans": "not_a_list"}', encoding="utf-8")
        with pytest.raises(ValueError, match="必须是字符串列表"):
            load_config(bad_str)

        # 列表中包含非字符串元素
        bad_items = tmp_path / "bad_items.json"
        bad_items.write_text('{"target": "t", "project_prefix": "p", "task_run_spans": [123]}', encoding="utf-8")
        with pytest.raises(ValueError, match="列表项必须是字符串"):
            load_config(bad_items)

    def test_sentry_report_validates_custom_release_pattern_group_count(self, tmp_path: Path) -> None:
        from tools.sentry.config import load_config

        # 仅有 3 个组，不足 5 个
        bad_pattern = tmp_path / "bad_pattern.json"
        bad_pattern.write_text(
            '{"target": "t", "project_prefix": "p", "release_pattern": "v(\\\\d+)\\\\.(\\\\d+)\\\\.(\\\\d+)"}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="必须包含恰好 5 个捕获组"):
            load_config(bad_pattern)

        good_pattern = tmp_path / "good_pattern.json"
        pattern_str = r"v(\d+)\.(\d+)\.(\d+)(?:-(beta|rc)\.(\d+))?"
        good_pattern.write_text(
            json.dumps({"target": "t", "project_prefix": "p", "release_pattern": pattern_str}),
            encoding="utf-8",
        )
        cfg = load_config(good_pattern)
        assert cfg.release_pattern is not None

    def test_sentry_report_generic_version_extraction_for_other_projects(self) -> None:
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


class TestTaskFailureEdgeCases:
    def test_sentry_report_in_version_excludes_missing_or_null_release(self) -> None:
        from tools.sentry.task_failure_report import _in_version

        key = (4, 7, 1, 2, 0)
        assert _in_version({"release": "m9a@v4.7.1"}, key) is True
        assert _in_version({"release": "m9a@v4.7.0"}, key) is False
        assert _in_version({"release": None}, key) is False
        assert _in_version({}, key) is False
        # 未指定版本时，返回 True
        assert _in_version({"release": None}, None) is True

    def test_sentry_report_build_release_rows_with_target_release(self) -> None:
        from tools.sentry.task_failure_report import build_release_rows

        totals = [
            {"release": "custom_build_1", "count_unique(trace)": 100},
            {"release": "other_build", "count_unique(trace)": 50},
        ]
        failures = [
            {"release": "custom_build_1", "count_unique(trace)": 10},
            {"release": "other_build", "count_unique(trace)": 5},
        ]
        # version_key is None (非标准 release), 指定 target_release 仅保留目标 release
        rows = build_release_rows(totals, failures, None, target_release="custom_build_1")
        assert len(rows) == 1
        assert rows[0].release == "custom_build_1"
        assert rows[0].total == 100
        assert rows[0].failed == 10

    def test_sentry_report_multi_channel_umbrella_aggregation_for_standard_version(self) -> None:
        from tools.sentry.task_failure_report import build_release_rows

        totals = [
            {"release": "m9a@v4.7.1", "count_unique(trace)": 100},
            {"release": "MXU@2.4.5+m9a@v4.7.1", "count_unique(trace)": 50},
            {"release": "m9a@v4.7.0", "count_unique(trace)": 200},
        ]
        failures = [
            {"release": "m9a@v4.7.1", "count_unique(trace)": 10},
            {"release": "MXU@2.4.5+m9a@v4.7.1", "count_unique(trace)": 5},
            {"release": "m9a@v4.7.0", "count_unique(trace)": 20},
        ]
        key = (4, 7, 1, 2, 0)
        rows = build_release_rows(totals, failures, key)
        # 同一版本的两个渠道均保留，排除不同版本
        assert len(rows) == 2
        release_names = {r.release for r in rows}
        assert "m9a@v4.7.1" in release_names
        assert "MXU@2.4.5+m9a@v4.7.1" in release_names
        assert "m9a@v4.7.0" not in release_names

    def test_sentry_report_markers_sorting_respects_reverse(self) -> None:
        from tools.sentry.task_failure_report import build_task_rows

        # 仅失败的节点标记
        totals = [
            {"span.description": "MarkerA", "count_unique(trace)": 5, "release": "m9a@v4.7.1"},
            {"span.description": "MarkerB", "count_unique(trace)": 15, "release": "m9a@v4.7.1"},
        ]
        statuses = [
            {
                "span.description": "MarkerA",
                "span.status": "internal_error",
                "count_unique(trace)": 5,
                "release": "m9a@v4.7.1",
            },
            {
                "span.description": "MarkerB",
                "span.status": "internal_error",
                "count_unique(trace)": 15,
                "release": "m9a@v4.7.1",
            },
        ]
        key = (4, 7, 1, 2, 0)
        # reverse=False: 次数多的在前 (MarkerB: 15, MarkerA: 5)
        _tasks, markers_desc = build_task_rows(totals, statuses, key, reverse=False)
        assert markers_desc[0].task == "MarkerB"
        assert markers_desc[1].task == "MarkerA"

        # reverse=True: 次数少的在前 (MarkerA: 5, MarkerB: 15)
        _tasks, markers_asc = build_task_rows(totals, statuses, key, reverse=True)
        assert markers_asc[0].task == "MarkerA"
        assert markers_asc[1].task == "MarkerB"


class TestTaskTrendEdgeCases:
    def test_sentry_report_task_filter_exact_and_fuzzy_resolution(self) -> None:
        from tools.sentry.task_trend_report import build_trend_report

        totals = [
            {"release": "m9a@v4.7.1", "span.description": "常规作战", "count_unique(trace)": 20},
            {"release": "m9a@v4.7.1", "span.description": "活动作战", "count_unique(trace)": 10},
            {"release": "m9a@v4.7.1", "span.description": "每日任务", "count_unique(trace)": 15},
        ]
        statuses = [
            {"release": "m9a@v4.7.1", "span.description": "常规作战", "span.status": "ok", "count_unique(trace)": 20},
            {"release": "m9a@v4.7.1", "span.description": "活动作战", "span.status": "ok", "count_unique(trace)": 10},
            {"release": "m9a@v4.7.1", "span.description": "每日任务", "span.status": "ok", "count_unique(trace)": 15},
        ]
        # 1. 唯一模糊匹配: "每日" -> "每日任务"
        rep1 = build_trend_report(totals, statuses, ["v4.7.1"], task_filter="每日")
        assert rep1.task_filter == "每日任务"

        # 2. 完全精确匹配优先 (即便 "常规" 也能模糊匹配, 精确匹配仍生效)
        rep2 = build_trend_report(totals, statuses, ["v4.7.1"], task_filter="常规作战")
        assert rep2.task_filter == "常规作战"

        # 3. 多个模糊匹配冲突 ("作战" 同时匹配到 "常规作战" 和 "活动作战")
        with pytest.raises(ValueError, match="匹配到多个候选任务"):
            build_trend_report(totals, statuses, ["v4.7.1"], task_filter="作战")

    def test_sentry_report_baseline_only_task_not_in_displayed_rows(self) -> None:
        from tools.sentry.task_trend_report import build_trend_report

        # 某个任务仅在最老基准版本 v4.6.1 中运行，但在展示版本 v4.7.1 中不存在
        totals = [
            {"release": "m9a@v4.7.1", "span.description": "活跃任务", "count_unique(trace)": 30},
            {"release": "m9a@v4.6.1", "span.description": "已废弃任务", "count_unique(trace)": 50},
        ]
        statuses = [
            {"release": "m9a@v4.7.1", "span.description": "活跃任务", "span.status": "ok", "count_unique(trace)": 30},
            {"release": "m9a@v4.6.1", "span.description": "已废弃任务", "span.status": "ok", "count_unique(trace)": 50},
        ]
        # 查询 2 个版本 (v4.7.1 与基准 v4.6.1)，但 display_versions 仅展示 ["v4.7.1"]
        rep = build_trend_report(
            totals,
            statuses,
            ["v4.7.1", "v4.6.1"],
            display_versions=["v4.7.1"],
        )
        task_names = [row.task for row in rep.rows]
        assert "活跃任务" in task_names
        assert "已废弃任务" not in task_names
