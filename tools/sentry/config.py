"""MaaFW Sentry 报告项目配置。

统一从同级目录下的 config.json 读取；未配置或缺失必填项时直接抛出异常。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


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

    return ProjectConfig(
        target=target.strip(),
        project_prefix=project_prefix.strip(),
        release_pattern=data.get("release_pattern"),
        task_run_spans=tuple(data.get("task_run_spans", ())),
        ignored_prefixes=tuple(data.get("ignored_prefixes", ())),
        ignored_suffixes=tuple(data.get("ignored_suffixes", ())),
    )


CONFIG = load_config()
