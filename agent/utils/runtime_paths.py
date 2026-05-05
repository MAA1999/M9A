"""
Runtime path resolution.

The launcher may switch cwd so Maa can resolve pipeline/resource-relative paths.
Python code should read paths from this module instead of assuming cwd directly.
"""

from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    agent_dir: Path
    assets_dir: Path
    work_root: Path
    config_dir: Path
    resource_dir: Path
    debug_dir: Path
    deps_dir: Path
    requirements_file: Path
    root_interface_file: Path
    assets_interface_file: Path
    manifest_cache_file: Path


def build_runtime_paths(
    project_root: str | Path | None = None,
    work_root: str | Path | None = None,
) -> RuntimePaths:
    resolved_project_root = Path(project_root or _DEFAULT_PROJECT_ROOT).resolve()
    resolved_work_root = Path(work_root or resolved_project_root).resolve()
    assets_dir = resolved_project_root / "assets"

    return RuntimePaths(
        project_root=resolved_project_root,
        agent_dir=resolved_project_root / "agent",
        assets_dir=assets_dir,
        work_root=resolved_work_root,
        config_dir=resolved_work_root / "config",
        resource_dir=resolved_work_root / "resource",
        debug_dir=resolved_work_root / "debug",
        deps_dir=resolved_project_root / "deps",
        requirements_file=resolved_project_root / "requirements.txt",
        root_interface_file=resolved_project_root / "interface.json",
        assets_interface_file=assets_dir / "interface.json",
        manifest_cache_file=(
            resolved_work_root / "resource" / "data" / "manifest_cache.json"
        ),
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
