"""根据 Sentry spans 生成任务在多个版本间的表现与趋势对比报告。

支持对比最近 N 个正式版本(或包含测试版)的任务失败率走势,在各版本后使用括号
备注相对前一版本的百分点变化量(如 ``5.6% (-1.4pp)``)。

任务级数据按版本聚合覆盖所有内嵌该版本的渠道,并按唯一 trace 去重计数。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any, TextIO

try:
    from .report_common import (
        DEFAULT_RELEASE_DISCOVERY_PERIOD,
        DEFAULT_SENTRY_TIMEOUT_SECONDS,
        MIN_RELEASE_UNIQUE_USERS,
        explore,
        release_version_key,
        resolve_sentry_command,
        show_progress,
        version_label,
        write_console_table,
    )
except ImportError:
    from report_common import (
        DEFAULT_RELEASE_DISCOVERY_PERIOD,
        DEFAULT_SENTRY_TIMEOUT_SECONDS,
        MIN_RELEASE_UNIQUE_USERS,
        explore,
        release_version_key,
        resolve_sentry_command,
        show_progress,
        version_label,
        write_console_table,
    )

try:
    from .config import CONFIG
except ImportError:
    from config import CONFIG

DEFAULT_TARGET = CONFIG.target
DEFAULT_VERSIONS_COUNT = 3
DEFAULT_MIN_LATEST_RUNS = 10
INTERNAL_ERROR = "internal_error"
SYSTEM_LABELS = {
    "controller_initialization_failed": "控制器初始化失败",
    "connection_failed": "连接失败",
    "agent_start_failed": "Agent 启动失败",
    "resource_initialization_failed": "资源初始化失败",
    "controller_link_start_failed": "控制器连接失败",
}


@dataclass(frozen=True)
class VersionTaskStat:
    """单个版本内某一任务的详细统计。"""

    version: str
    total: int
    failed: int
    failure_rate: float | None
    delta_pp: float | None = None


@dataclass(frozen=True)
class TaskTrendRow:
    """多版本对比表中某一任务的汇总行。"""

    task: str
    latest_total: int
    version_rates: dict[str, float | None]
    version_deltas: dict[str, float | None]


@dataclass(frozen=True)
class TrendReport:
    """跨版本任务表现报告。"""

    versions: list[str]
    rows: list[TaskTrendRow]
    task_filter: str | None = None
    detailed_task_stats: list[VersionTaskStat] | None = None


def format_delta(delta_pp: float | None) -> str:
    """格式化百分点变化量,例如 '+1.4pp' 或 '-2.0pp'。"""
    if delta_pp is None:
        return ""
    sign = "+" if delta_pp > 0 else ""
    return f"{sign}{delta_pp:.1f}pp"


def format_rate_with_delta(rate: float | None, delta_pp: float | None) -> str:
    """把小数失败率格式化为百分比,并追加括号备注的百分点变化量。"""
    if rate is None:
        return "暂无样本"
    base = f"{rate:.1%}"
    delta = format_delta(delta_pp)
    return f"{base} ({delta})" if delta else base


def _unique_trace_count(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    return value if isinstance(value, int) else None


def discover_versions(
    rows: Sequence[dict[str, Any]],
    *,
    count: int = DEFAULT_VERSIONS_COUNT,
    include_prerelease: bool = False,
    min_users: int = MIN_RELEASE_UNIQUE_USERS,
) -> list[str]:
    """从 spans 中发现用户数达标的最近 N 个版本(降序排列)。

    额外多探索一个版本以作为最老展示版本的变化量基准。
    """
    version_users: dict[tuple[int, int, int, int, int], int] = defaultdict(int)
    version_labels: dict[tuple[int, int, int, int, int], str] = {}

    for row in rows:
        release = row.get("release")
        user_count = row.get("count_unique(user)")
        if not isinstance(release, str) or not isinstance(user_count, int):
            continue
        key = release_version_key(release)
        label = version_label(release)
        if key is None or label is None:
            continue
        # key[3] == 2 代表正式稳定版,0/1 分别为 beta/rc
        if not include_prerelease and key[3] != 2:
            continue
        version_users[key] += user_count
        version_labels[key] = label

    qualified_keys = [key for key, users in sorted(version_users.items(), reverse=True) if users >= min_users]
    # 取 count + 1 个版本,以提供最旧展示版本相对于更早版本的环比变化
    selected_keys = qualified_keys[: count + 1]
    return [version_labels[key] for key in selected_keys]


def build_trend_report(
    totals: Iterable[dict[str, Any]],
    statuses: Iterable[dict[str, Any]],
    versions: Sequence[str],
    *,
    display_versions: Sequence[str] | None = None,
    task_filter: str | None = None,
    min_latest_runs: int = DEFAULT_MIN_LATEST_RUNS,
    sort: str = "runs",
    reverse: bool = False,
    limit: int | None = None,
) -> TrendReport:
    """根据执行与状态分布行聚合各版本的任务失败率及环比变化。"""
    version_set = set(versions)
    task_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    task_failures: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    task_oks: dict[str, int] = defaultdict(int)

    for row in totals:
        release = str(row.get("release", ""))
        label = version_label(release)
        description = row.get("span.description")
        count = _unique_trace_count(row, "count_unique(trace)")
        if label in version_set and isinstance(description, str) and count:
            task_totals[label][description] += count

    for row in statuses:
        release = str(row.get("release", ""))
        label = version_label(release)
        description = row.get("span.description")
        status = row.get("span.status")
        count = _unique_trace_count(row, "count_unique(trace)")
        if label in version_set and isinstance(description, str) and count:
            if status == INTERNAL_ERROR:
                task_failures[label][description] += count
            elif status == "ok":
                task_oks[description] += count

    target_versions = set(display_versions) if display_versions else version_set
    all_tasks = set()
    for v in target_versions:
        all_tasks.update(task_totals[v].keys())

    # 若指定了单任务筛选,提取单任务在各个版本下的详细统计
    detailed_stats: list[VersionTaskStat] | None = None
    resolved_task_filter = task_filter
    if task_filter:
        exact_match = next((t for t in sorted(all_tasks) if t.lower() == task_filter.lower()), None)
        if exact_match is not None:
            target_task = exact_match
        else:
            fuzzy_matches = [t for t in sorted(all_tasks) if task_filter.lower() in t.lower()]
            if len(fuzzy_matches) == 1:
                target_task = fuzzy_matches[0]
            elif len(fuzzy_matches) > 1:
                candidates = ", ".join(f"'{m}'" for m in fuzzy_matches)
                raise ValueError(f"任务筛选 '{task_filter}' 匹配到多个候选任务: {candidates}。请指定更精确的任务名称。")
            else:
                target_task = task_filter
        resolved_task_filter = target_task
        detailed_stats = []
        for i, version in enumerate(versions):
            tot = task_totals[version].get(target_task, 0)
            fail = task_failures[version].get(target_task, 0)
            rate = (fail / tot) if tot > 0 else None

            delta_pp: float | None = None
            if i + 1 < len(versions):
                prev_version = versions[i + 1]
                prev_tot = task_totals[prev_version].get(target_task, 0)
                prev_fail = task_failures[prev_version].get(target_task, 0)
                if prev_tot > 0 and rate is not None:
                    delta_pp = (rate - (prev_fail / prev_tot)) * 100

            detailed_stats.append(
                VersionTaskStat(
                    version=version,
                    total=tot,
                    failed=fail,
                    failure_rate=rate,
                    delta_pp=delta_pp,
                )
            )

    # 聚合全局任务宽表(排除 umbrella span 与纯失败节点标记)
    latest_version = versions[0] if versions else ""
    rows: list[TaskTrendRow] = []

    for task in all_tasks:
        if task_filter and task_filter.lower() not in task.lower():
            continue
        if (
            task in SYSTEM_LABELS
            or any(task.startswith(p) for p in CONFIG.ignored_prefixes)
            or any(task.endswith(s) for s in CONFIG.ignored_suffixes)
        ):
            continue
        # 若未显式筛选单任务,排除没有成功样本的纯失败节点标记(如 ReturnMain、Start1999 等)
        if not task_filter and task_oks.get(task, 0) == 0:
            continue

        latest_total = task_totals[latest_version].get(task, 0)
        # 仅保留在最新版本或任意版本中有足够样本的任务
        any_total = sum(task_totals[v].get(task, 0) for v in versions)
        if latest_total < min_latest_runs and any_total < min_latest_runs * 2:
            continue

        rates: dict[str, float | None] = {}
        deltas: dict[str, float | None] = {}
        for i, version in enumerate(versions):
            tot = task_totals[version].get(task, 0)
            fail = task_failures[version].get(task, 0)
            rate = (fail / tot) if tot > 0 else None
            rates[version] = rate

            delta_pp: float | None = None
            if i + 1 < len(versions):
                prev_v = versions[i + 1]
                prev_tot = task_totals[prev_v].get(task, 0)
                prev_fail = task_failures[prev_v].get(task, 0)
                if prev_tot > 0 and rate is not None:
                    delta_pp = (rate - (prev_fail / prev_tot)) * 100
            deltas[version] = delta_pp

        rows.append(
            TaskTrendRow(
                task=task,
                latest_total=latest_total,
                version_rates=rates,
                version_deltas=deltas,
            )
        )

    if sort == "rate":
        rows.sort(
            key=lambda r: (
                r.version_rates.get(latest_version) is not None,
                r.version_rates.get(latest_version) or 0.0,
                r.latest_total,
            ),
            reverse=not reverse,
        )
    elif sort == "delta":
        rows.sort(
            key=lambda r: (
                r.version_deltas.get(latest_version) is not None,
                r.version_deltas.get(latest_version) or 0.0,
                r.latest_total,
            ),
            reverse=not reverse,
        )
    elif sort == "name":
        rows.sort(key=lambda r: r.task, reverse=reverse)
    else:  # "runs" (默认)
        rows.sort(key=lambda r: (r.latest_total, r.task), reverse=not reverse)

    if limit is not None and limit > 0:
        rows = rows[:limit]

    return TrendReport(
        versions=list(versions),
        rows=rows,
        task_filter=resolved_task_filter,
        detailed_task_stats=detailed_stats,
    )


def collect_report(
    *,
    sentry_command: str,
    target: str,
    period: str,
    versions_count: int,
    include_prerelease: bool,
    task_filter: str | None,
    min_latest_runs: int,
    sort: str = "runs",
    reverse: bool = False,
    limit: int | None = None,
    timeout_seconds: float,
    verbose: bool,
    quiet: bool,
) -> TrendReport:
    """查询 Sentry spans 并生成多版本任务对比报告。"""
    show_progress(
        f"[1/3] 探索最近 {versions_count} 个版本",
        quiet=quiet,
    )
    version_discovery_rows = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("release", "count_unique(user)", "count_unique(trace)"),
        query="",
        sort="-count_unique(user)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )
    all_discovered = discover_versions(
        version_discovery_rows,
        count=versions_count,
        include_prerelease=include_prerelease,
    )
    if not all_discovered:
        raise RuntimeError(f"在 {period} 内未找到符合条件的应用版本(至少 {MIN_RELEASE_UNIQUE_USERS} 位独立用户)。")

    # 展示的版本数与用于提供基准变化量的全量版本列表
    display_versions = all_discovered[:versions_count]
    query_versions = all_discovered
    show_progress(
        f"分析版本: {', '.join(display_versions)} (数据聚合覆盖各版本的所有渠道)",
        quiet=quiet,
    )

    query_filter = f'span.description:"{task_filter}"' if task_filter else ""

    show_progress("[2/3] 查询各版本任务执行总量", quiet=quiet)
    totals = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("span.description", "release", "count_unique(trace)"),
        query=query_filter,
        sort="-count_unique(trace)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    show_progress("[3/3] 查询各版本任务结果分布", quiet=quiet)
    statuses = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("span.description", "span.status", "release", "count_unique(trace)"),
        query=query_filter,
        sort="-count_unique(trace)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    report = build_trend_report(
        totals,
        statuses,
        query_versions,
        display_versions=display_versions,
        task_filter=task_filter,
        min_latest_runs=min_latest_runs,
        sort=sort,
        reverse=reverse,
        limit=limit,
    )
    # 仅展示用户指定的 display_versions
    return TrendReport(
        versions=display_versions,
        rows=report.rows,
        task_filter=report.task_filter,
        detailed_task_stats=(
            [s for s in report.detailed_task_stats if s.version in display_versions]
            if report.detailed_task_stats
            else None
        ),
    )


def write_console(report: TrendReport, output: TextIO) -> None:
    if report.detailed_task_stats:
        task_name = report.task_filter or "指定任务"
        print(f"任务趋势明细: {task_name}", file=output)
        print("所有次数均按唯一 trace 去重,变化量为相对上一版本的百分点差异(Δpp)。\n", file=output)
        headers = ("版本", "运行数", "失败数", "失败率", "相对上一版本")
        rows = [
            (
                stat.version,
                str(stat.total),
                str(stat.failed),
                f"{stat.failure_rate:.1%}" if stat.failure_rate is not None else "暂无样本",
                format_delta(stat.delta_pp) if stat.delta_pp is not None else "-",
            )
            for stat in report.detailed_task_stats
        ]
        write_console_table(headers, rows, output, right_aligned={1, 2, 3, 4})
        return

    print("任务失败率跨版本对比 (含相对上一版本的变化量)", file=output)
    print(
        "括号内备注为相对上一版本的百分点变化(如 -1.4pp 表示失败率下降 1.4%);运行数按唯一 trace 去重。\n", file=output
    )

    latest_ver = report.versions[0] if report.versions else "最新"
    headers = ["任务", f"运行数({latest_ver})", *report.versions]
    table_rows = []
    for row in report.rows:
        cells = [row.task, str(row.latest_total)]
        for v in report.versions:
            rate = row.version_rates.get(v)
            delta = row.version_deltas.get(v)
            cells.append(format_rate_with_delta(rate, delta))
        table_rows.append(cells)

    right_aligned = set(range(1, len(headers)))
    write_console_table(headers, table_rows, output, right_aligned=right_aligned)


def write_markdown(report: TrendReport, output: TextIO) -> None:
    if report.detailed_task_stats:
        task_name = report.task_filter or "指定任务"
        print(f"## 任务趋势明细: {task_name}\n", file=output)
        print("> 所有次数均按唯一 trace 去重,变化量为相对上一版本的百分点差异(Δpp)。\n", file=output)
        print("| 版本 | 运行数 | 失败数 | 失败率 | 相对上一版本 |", file=output)
        print("|---|---:|---:|---:|---:|", file=output)
        for stat in report.detailed_task_stats:
            rate_str = f"{stat.failure_rate:.1%}" if stat.failure_rate is not None else "暂无样本"
            delta_str = format_delta(stat.delta_pp) if stat.delta_pp is not None else "-"
            print(f"| {stat.version} | {stat.total} | {stat.failed} | {rate_str} | {delta_str} |", file=output)
        return

    print("## 任务失败率跨版本对比 (含相对上一版本的变化量)\n", file=output)
    print("> 括号内备注为相对上一版本的百分点变化(如 `-1.4pp` 表示失败率下降 1.4%)。\n", file=output)
    latest_ver = report.versions[0] if report.versions else "最新"
    headers = ["任务", f"运行数({latest_ver})", *report.versions]
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "|---|" + "|".join("---:" for _ in headers[1:]) + "|"
    print(header_line, file=output)
    print(separator_line, file=output)

    for row in report.rows:
        cells = [row.task, str(row.latest_total)]
        for v in report.versions:
            rate = row.version_rates.get(v)
            delta = row.version_deltas.get(v)
            cells.append(format_rate_with_delta(rate, delta))
        print("| " + " | ".join(cells) + " |", file=output)


def write_json(report: TrendReport, output: TextIO) -> None:
    json.dump(asdict(report), output, ensure_ascii=False, indent=2)
    output.write("\n")


def create_argument_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument(
        "--versions",
        type=int,
        default=DEFAULT_VERSIONS_COUNT,
        help=f"对比最近 N 个版本(默认:{DEFAULT_VERSIONS_COUNT})",
    )
    parser.add_argument(
        "--task",
        help="指定查看某一具体任务的详细版本走势(如 --task 领取奖励)",
    )
    parser.add_argument("--target", default=DEFAULT_TARGET, help="<org>/<project>")
    parser.add_argument(
        "--period",
        default=DEFAULT_RELEASE_DISCOVERY_PERIOD,
        help="查询范围(默认:90d),以覆盖多个版本的生命周期",
    )
    parser.add_argument(
        "--include-beta",
        action="store_true",
        help="版本序列中包含 beta/rc 测试版(默认仅对比正式稳定版)",
    )
    parser.add_argument(
        "--min-latest-runs",
        type=int,
        default=DEFAULT_MIN_LATEST_RUNS,
        help=f"在大表中展示任务所需的最低样本数(默认:{DEFAULT_MIN_LATEST_RUNS})",
    )
    parser.add_argument(
        "--sort",
        choices=("runs", "rate", "delta", "name"),
        default="runs",
        help="任务排序规则: runs(运行数从大到小,默认), rate(失败率从高到低), delta(恶化幅度从大到小), name(任务名)",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="反转排序顺序(例如失败率从低到高)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="限制展示的任务数量(如 --limit 10 仅展示前 10 个任务)",
    )
    parser.add_argument(
        "--format",
        choices=("console", "markdown", "json"),
        default="console",
        help="输出格式",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_SENTRY_TIMEOUT_SECONDS,
        help="单次 Sentry 查询超时秒数(默认:120)",
    )
    parser.add_argument("--verbose", action="store_true", help="输出 sentry 查询命令")
    parser.add_argument("--quiet", action="store_true", help="不输出查询进度")
    return parser


def main(argv: Sequence[str] | None = None, prog: str | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    arguments = create_argument_parser(prog).parse_args(argv)
    if not math.isfinite(arguments.timeout) or arguments.timeout <= 0:
        raise ValueError("--timeout 必须是大于 0 的有限数值。")
    if arguments.versions <= 0:
        raise ValueError("--versions 必须是大于 0 的整数。")
    if arguments.limit is not None and arguments.limit <= 0:
        raise ValueError("--limit 必须是大于 0 的整数。")

    report = collect_report(
        sentry_command=resolve_sentry_command(),
        target=arguments.target,
        period=arguments.period,
        versions_count=arguments.versions,
        include_prerelease=arguments.include_beta,
        task_filter=arguments.task,
        min_latest_runs=arguments.min_latest_runs,
        sort=arguments.sort,
        reverse=arguments.reverse,
        limit=arguments.limit,
        timeout_seconds=arguments.timeout,
        verbose=arguments.verbose,
        quiet=arguments.quiet,
    )
    writers = {
        "console": write_console,
        "markdown": write_markdown,
        "json": write_json,
    }
    writers[arguments.format](report, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"错误:{error}", file=sys.stderr)
        raise SystemExit(1) from error
