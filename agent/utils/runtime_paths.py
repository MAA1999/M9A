from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    agent_dir: Path
    work_root: Path
    config_dir: Path
    resource_dir: Path
    debug_dir: Path
    requirements_file: Path
    interface_file: Path


def build_runtime_paths(
    project_root: str | Path | None = None,
    work_root: str | Path | None = None,
) -> RuntimePaths:
    resolved_project_root = Path(project_root or DEFAULT_PROJECT_ROOT).resolve()
    resolved_work_root = Path(work_root or resolved_project_root).resolve()
    return RuntimePaths(
        project_root=resolved_project_root,
        agent_dir=resolved_project_root / "agent",
        work_root=resolved_work_root,
        config_dir=resolved_work_root / "config",
        resource_dir=resolved_work_root / "resource",
        debug_dir=resolved_work_root / "debug",
        requirements_file=resolved_project_root / "requirements.txt",
        interface_file=resolved_project_root / "interface.json",
    )


_runtime_paths = build_runtime_paths()


def configure_runtime_paths(
    project_root: str | Path | None = None,
    work_root: str | Path | None = None,
) -> RuntimePaths:
    global _runtime_paths
    _runtime_paths = build_runtime_paths(project_root=project_root, work_root=work_root)
    return _runtime_paths


def get_runtime_paths() -> RuntimePaths:
    return _runtime_paths
