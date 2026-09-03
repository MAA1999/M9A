"""根据 Sentry spans 生成任务失败率分析报告。

默认分析 Sentry 上最新的应用版本最近 7 天的任务运行数据。
任务级分析按版本聚合：同一版本由多个渠道 release 内嵌，
查询覆盖内嵌该版本的全部渠道。trace 归属唯一 release，跨渠道求和不产生重复计数。

报告区分三种口径，均按唯一 trace 去重：

- **任务结果**：任务级 span 按 ok / internal_error / cancelled 分列，
  失败率 = 失败 trace 数 / 总 trace 数，是最接近“这个任务失败概率”的口径；
- **失败节点标记**：仅在节点失败时才上报的 span 和系统级失败（控制器初始化失败等），
  没有成功样本，“触发次数”即触发该失败的运行数，不参与失败率计算；
- **运行失败率**：各渠道 umbrella span 的 internal_error 占比，即“一次完整运行失败的概率”，
  用于跨渠道对比。
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
        DEFAULT_SENTRY_TIMEOUT_SECONDS,
        explore,
        format_rate,
        release_version_key,
        resolve_latest_release,
        resolve_sentry_command,
        show_progress,
        version_label,
        write_console_table,
    )
except ImportError:
    from report_common import (
        DEFAULT_SENTRY_TIMEOUT_SECONDS,
        explore,
        format_rate,
        release_version_key,
        resolve_latest_release,
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
DEFAULT_PERIOD = "7d"
INTERNAL_ERROR = "internal_error"
CANCELLED = "cancelled"
OK = "ok"
# 各渠道上报"整次运行"的 umbrella span 名称。
TASK_RUN_SPANS = CONFIG.task_run_spans
UMBRELLA_FILTER = f"span.description:[{','.join(TASK_RUN_SPANS)}]"
SYSTEM_LABELS = {
    "controller_initialization_failed": "控制器初始化失败",
    "connection_failed": "连接失败",
    "agent_start_failed": "Agent 启动失败",
    "resource_initialization_failed": "资源初始化失败",
    "controller_link_start_failed": "控制器连接失败",
}


@dataclass(frozen=True)
class TaskRow:
    task: str
    total: int
    failed: int
    cancelled: int
    failure_rate: float | None


@dataclass(frozen=True)
class ReleaseRow:
    release: str
    total: int
    failed: int
    failure_rate: float


@dataclass(frozen=True)
class Report:
    release: str
    version: str | None
    tasks: list[TaskRow]
    markers: list[TaskRow]
    runs: list[ReleaseRow]


def describe(description: str) -> str:
    """把系统级 span 描述翻译为可读标签,任务名保持原样。"""
    return SYSTEM_LABELS.get(description, description)


def _unique_trace_count(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    return value if isinstance(value, int) else None


def _in_version(row: dict[str, Any], version_key: tuple[int, int, int, int, int] | None) -> bool:
    """判断行是否属于目标版本;无法判定(行缺少 release)时视为属于。"""
    if version_key is None:
        return True
    release = row.get("release")
    if not isinstance(release, str):
        return True
    return release_version_key(release) == version_key


def build_task_rows(
    totals: Iterable[dict[str, Any]],
    statuses: Iterable[dict[str, Any]],
    version_key: tuple[int, int, int, int, int] | None,
    *,
    sort: str = "failures",
    reverse: bool = False,
    limit: int | None = None,
) -> tuple[list[TaskRow], list[TaskRow]]:
    """根据任务执行总量与各状态 trace 行聚合各任务的成功率与失败率。"""
    total_by_task: dict[str, int] = defaultdict(int)
    status_by_task: dict[str, dict[str, int]] = defaultdict(dict)
    for row in totals:
        if not _in_version(row, version_key):
            continue
        description = row.get("span.description")
        if not isinstance(description, str):
            continue
        count = _unique_trace_count(row, "count_unique(trace)")
        if count is not None:
            total_by_task[description] += count

    for row in statuses:
        if not _in_version(row, version_key):
            continue
        description = row.get("span.description")
        if not isinstance(description, str):
            continue
        count = _unique_trace_count(row, "count_unique(trace)")
        if count is None:
            continue
        status = str(row["span.status"])
        status_by_task[description][status] = status_by_task[description].get(status, 0) + count

    tasks: list[TaskRow] = []
    markers: list[TaskRow] = []
    for description in total_by_task.keys() | status_by_task.keys():
        status_counts = status_by_task.get(description, {})
        failed = status_counts.get(INTERNAL_ERROR, 0)
        cancelled = status_counts.get(CANCELLED, 0)
        ok = status_counts.get(OK, 0)
        if ok == 0 and cancelled == 0 and failed > 0:
            markers.append(TaskRow(task=description, total=failed, failed=failed, cancelled=0, failure_rate=None))
            continue
        total = total_by_task.get(description) or (ok + failed + cancelled)
        failed = min(failed, total)
        cancelled = min(cancelled, total - failed)
        tasks.append(
            TaskRow(
                task=description,
                total=total,
                failed=failed,
                cancelled=cancelled,
                failure_rate=failed / total if total else None,
            )
        )

    if sort == "rate":
        tasks.sort(
            key=lambda row: (row.failure_rate is not None, row.failure_rate or 0.0, row.total),
            reverse=not reverse,
        )
    elif sort == "total":
        tasks.sort(key=lambda row: (row.total, row.task), reverse=not reverse)
    elif sort == "name":
        tasks.sort(key=lambda row: row.task, reverse=reverse)
    else:  # "failures" (默认)
        tasks.sort(key=lambda row: (row.failed, row.total, row.task), reverse=not reverse)

    markers.sort(key=lambda row: (-row.total, row.task))
    if limit is not None and limit > 0:
        tasks = tasks[:limit]
        markers = markers[:limit]

    return tasks, markers


def build_release_rows(
    totals: Iterable[dict[str, Any]],
    failures: Iterable[dict[str, Any]],
    version_key: tuple[int, int, int, int, int] | None,
) -> list[ReleaseRow]:
    """按 release 字符串聚合运行失败率;version_key 非空时仅保留内嵌同版本号的渠道。"""
    total_by_release: dict[str, int] = {}
    failed_by_release: dict[str, int] = defaultdict(int)
    for row in totals:
        release = str(row["release"])
        count = _unique_trace_count(row, "count_unique(trace)")
        if count is not None:
            total_by_release[release] = count
    for row in failures:
        release = str(row["release"])
        count = _unique_trace_count(row, "count_unique(trace)")
        if count is not None:
            failed_by_release[release] = count

    report = []
    for release, total in total_by_release.items():
        if version_key is not None and release_version_key(release) != version_key:
            continue
        failed = failed_by_release.get(release, 0)
        report.append(
            ReleaseRow(
                release=release,
                total=total,
                failed=failed,
                failure_rate=failed / total if total else 0.0,
            )
        )
    return sorted(report, key=lambda row: (-row.total, row.release))


def collect_report(
    *,
    sentry_command: str,
    release: str | None,
    target: str,
    period: str,
    sort: str = "failures",
    reverse: bool = False,
    limit: int | None = None,
    timeout_seconds: float,
    verbose: bool,
    quiet: bool,
) -> Report:
    if release is None:
        show_progress("[0/4] 自动选择最新版本", quiet=quiet)
        release = resolve_latest_release(
            sentry_command,
            target=target,
            verbose=verbose,
            timeout_seconds=timeout_seconds,
        )
    version_key = release_version_key(release)
    version = version_label(release)
    if version is not None:
        show_progress(
            f"分析版本 {version}(版本确定自 release:{release},任务数据聚合覆盖所有内嵌该版本的渠道)",
            quiet=quiet,
        )
    else:
        show_progress(f"分析单个 Sentry release:{release}", quiet=quiet)
    escaped_release = release.replace('"', '\\"')
    scope_filter = f'release:"{escaped_release}"'
    # 任务级分析按版本聚合:同一版本内嵌于多个渠道 release,
    # 查询不带 release 过滤,取回后按版本键本地过滤。
    # release 无法解析出版本时(--release 传入了非标准字符串),
    # 回退为按该 release 精确过滤。
    task_query = "" if version_key is not None else scope_filter

    show_progress("[1/4] 查询任务执行总量", quiet=quiet)
    task_total_rows = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("span.description", "release", "count_unique(trace)"),
        query=task_query,
        sort="-count_unique(trace)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    show_progress("[2/4] 查询任务结果分布", quiet=quiet)
    task_status_rows = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("span.description", "span.status", "release", "count_unique(trace)"),
        query=task_query,
        sort="-count_unique(trace)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    show_progress("[3/4] 查询各渠道运行总量", quiet=quiet)
    run_total_rows = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("release", "count_unique(trace)"),
        query=UMBRELLA_FILTER,
        sort="-count_unique(trace)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    show_progress("[4/4] 查询各渠道运行失败分布", quiet=quiet)
    run_failure_rows = explore(
        sentry_command,
        target=target,
        period=period,
        fields=("release", "count_unique(trace)"),
        query=f"{UMBRELLA_FILTER} span.status:{INTERNAL_ERROR}",
        sort="-count_unique(trace)",
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    runs = build_release_rows(run_total_rows, run_failure_rows, version_key)

    tasks, markers = build_task_rows(
        task_total_rows,
        task_status_rows,
        version_key,
        sort=sort,
        reverse=reverse,
        limit=limit,
    )
    return Report(
        release=release,
        version=version,
        tasks=tasks,
        markers=markers,
        runs=runs,
    )


def write_console(report: Report, output: TextIO) -> None:
    if report.version:
        print(f"版本: {report.version}", file=output)
    else:
        print(f"Sentry release: {report.release}", file=output)
    print("报告内所有次数均按唯一 trace 去重。\n", file=output)
    write_console_table(
        ("任务", "总次数", "失败", "取消", "失败率"),
        [
            (row.task, str(row.total), str(row.failed), str(row.cancelled), format_rate(row.failure_rate))
            for row in report.tasks
        ],
        output,
        right_aligned={1, 2, 3, 4},
    )

    print("\n失败节点标记", file=output)
    print("以下 span 仅在失败时上报;触发次数即触发该失败的任务运行数,不参与失败率计算。\n", file=output)
    write_console_table(
        ("节点/系统", "触发次数"),
        [(describe(row.task), str(row.total)) for row in report.markers],
        output,
        right_aligned={1},
    )

    spans_desc = " / ".join(TASK_RUN_SPANS)
    print("\n运行失败率(跨渠道对比)", file=output)
    print(
        f"口径:各渠道 umbrella span({spans_desc})的失败率,"
        "即一次完整运行失败的占比。release 字符串由渠道注册,内嵌相同的版本号。\n",
        file=output,
    )
    write_console_table(
        ("release", "运行数", "失败", "失败率"),
        [(row.release, str(row.total), str(row.failed), format_rate(row.failure_rate)) for row in report.runs],
        output,
        right_aligned={1, 2, 3},
    )


def write_markdown(report: Report, output: TextIO) -> None:
    if report.version:
        print(f"> 版本: {report.version}\n", file=output)
    else:
        print(f"> Sentry release: `{report.release}`\n", file=output)
    print("> 报告内所有次数均按唯一 trace 去重。\n", file=output)
    print("## 任务失败率\n", file=output)
    print("| 任务 | 总次数 | 失败 | 取消 | 失败率 |", file=output)
    print("|---|---:|---:|---:|---:|", file=output)
    for row in report.tasks:
        print(
            f"| {row.task} | {row.total} | {row.failed} | {row.cancelled} | {format_rate(row.failure_rate)} |",
            file=output,
        )

    print("\n## 失败节点标记\n", file=output)
    print("> 以下 span 仅在失败时上报;触发次数即触发该失败的任务运行数,不参与失败率计算。\n", file=output)
    print("| 节点/系统 | 触发次数 |", file=output)
    print("|---|---:|", file=output)
    for row in report.markers:
        print(f"| {describe(row.task)} | {row.total} |", file=output)

    spans_desc = " / ".join(TASK_RUN_SPANS)
    print("\n## 运行失败率(跨渠道对比)\n", file=output)
    print(
        f"> 口径:各渠道 umbrella span({spans_desc})的失败率,即一次完整运行失败的占比。\n",
        file=output,
    )
    print("| release | 运行数 | 失败 | 失败率 |", file=output)
    print("|---|---:|---:|---:|", file=output)
    for row in report.runs:
        print(
            f"| `{row.release}` | {row.total} | {row.failed} | {format_rate(row.failure_rate)} |",
            file=output,
        )


def write_json(report: Report, output: TextIO) -> None:
    json.dump(asdict(report), output, ensure_ascii=False, indent=2)
    output.write("\n")


def create_argument_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument(
        "--release",
        help=("指定 Sentry release(取其内嵌的项目版本);未指定时自动选择最新版本"),
    )
    parser.add_argument("--target", default=DEFAULT_TARGET, help="<org>/<project>")
    parser.add_argument(
        "--period",
        default=DEFAULT_PERIOD,
        help='查询范围,例如 "24h"、"7d" 或 "2026-08-23..2026-08-24"',
    )
    parser.add_argument(
        "--sort",
        choices=("failures", "rate", "total", "name"),
        default="failures",
        help="任务排序规则: failures(失败次数从多到少,默认), rate(失败率从高到低), total(总次数从多到少), name(任务名)",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="反转排序顺序",
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
    if arguments.limit is not None and arguments.limit <= 0:
        raise ValueError("--limit 必须是大于 0 的整数。")

    report = collect_report(
        sentry_command=resolve_sentry_command(),
        release=arguments.release,
        target=arguments.target,
        period=arguments.period,
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
