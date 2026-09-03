"""MaaFW Sentry 报告项目配置。

统一从同级目录下的 config.json 读取；未配置或缺失必填项时直接抛出异常。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectConfig:
    # Sentry 目标仓库 (<org>/<project>)
    target: str
    # 项目 Release 标识前缀 (例如 "m9a"、"MaaEnd"、"MAA")
    project_prefix: str
    # 可选: 自定义 Release 正则表达式 (未指定时根据 project_prefix 自动构造)
    release_pattern: str | None = None
    # 各渠道上报运行总量的 umbrella span 名称
    task_run_spans: tuple[str, ...] = ()
    # 任务列表中忽略的私有 span 前缀
    ignored_prefixes: tuple[str, ...] = ()
    # 任务列表中忽略的私有 span 后缀
    ignored_suffixes: tuple[str, ...] = ()


def _parse_str_list(value: Any, field_name: str, config_file: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"配置文件 {config_file} 中的 '{field_name}' 必须是字符串列表。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(
                f"配置文件 {config_file} 中的 '{field_name}' 列表项必须是字符串，发现: {type(item).__name__}"
            )
        result.append(item)
    return tuple(result)


def load_config(config_path: Path | str | None = None) -> ProjectConfig:
    """加载配置：从 config.json 读取；不存在或缺少必填字段时直接抛出异常。"""
    config_file = Path(config_path) if config_path else Path(__file__).parent / "config.json"
    if not config_file.is_file():
        raise FileNotFoundError(f"未找到 Sentry 配置文件: {config_file}。请在 tools/sentry/ 目录下提供 config.json。")

    with open(config_file, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"配置文件 {config_file} 内容格式错误，必须为 JSON 对象。")

    target = data.get("target")
    if not isinstance(target, str) or not target.strip():
        raise ValueError(f"配置文件 {config_file} 缺少必填字段 'target' (例如 <org>/<project>)。")

    project_prefix = data.get("project_prefix")
    if not isinstance(project_prefix, str) or not project_prefix.strip():
        raise ValueError(f"配置文件 {config_file} 缺少必填字段 'project_prefix'。")

    release_pattern = data.get("release_pattern")
    if release_pattern is not None:
        if not isinstance(release_pattern, str) or not release_pattern.strip():
            raise ValueError(f"配置文件 {config_file} 中的 'release_pattern' 必须是非空字符串。")
        try:
            compiled = re.compile(release_pattern)
            if compiled.groups != 5:
                raise ValueError(
                    f"配置文件 {config_file} 中的 'release_pattern' 必须包含恰好 5 个捕获组 "
                    f"(major, minor, patch, prerelease, prerelease_number)，当前包含 {compiled.groups} 个。"
                )
        except re.error as err:
            raise ValueError(f"配置文件 {config_file} 中的 'release_pattern' 正则表达式无效: {err}") from err

    return ProjectConfig(
        target=target.strip(),
        project_prefix=project_prefix.strip(),
        release_pattern=release_pattern,
        task_run_spans=_parse_str_list(data.get("task_run_spans"), "task_run_spans", config_file),
        ignored_prefixes=_parse_str_list(data.get("ignored_prefixes"), "ignored_prefixes", config_file),
        ignored_suffixes=_parse_str_list(data.get("ignored_suffixes"), "ignored_suffixes", config_file),
    )


CONFIG = load_config()
