from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_USER_DATA_DIR = "PI_USER_DATA_DIR"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_work_root() -> Path:
    """返回 config / debug / data 的落盘根目录。

    PI v2.11.0 起 Client 通过 ``PI_USER_DATA_DIR`` 交出一个可写数据目录。macOS 的 .app 里项目
    根目录位于应用包内，普通用户账户不可写，所以不能回落到工作目录；Client 没设该变量时
    （例如 MFAAvalonia）与以前一致，仍用当前工作目录。
    """
    value = os.environ.get(ENV_USER_DATA_DIR, "").strip()
    return Path(value) if value else Path.cwd()


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
    manifest_cache_file: Path


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
        # 热更新写到 work_root/resource：Windows/Linux 下 MXU 的 PI_USER_DATA_DIR 就是 exe 所在
        # 目录（便携布局），写这里等于写进资源目录，与旧行为一致。
        # 已知缺口：macOS .app 下 MXU 从 Contents/Resources/MXU-portable 加载资源（以
        # interface.json 所在目录为基准，见 MXU src/utils/resourcePath.ts），不写
        # PI_USER_DATA_DIR/resource——也就是说 Mirror酱 热更新在 macOS 下写得到但读不到，
        # 每次启动都会重新提示有新版本。需要 MXU 在加载 resource.path 之外再叠加
        # PI_USER_DATA_DIR/resource（或提供等价覆盖机制）才能真正生效，属于上游改动。
        resource_dir=resolved_work_root / "resource",
        debug_dir=resolved_work_root / "debug",
        requirements_file=resolved_project_root / "requirements.txt",
        interface_file=resolved_project_root / "interface.json",
        manifest_cache_file=resolved_work_root / "data" / "manifest_cache.json",
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
