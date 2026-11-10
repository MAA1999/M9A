from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

ENV_USER_DATA_DIR = "PI_USER_DATA_DIR"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_work_root() -> Path:
    """返回 config / debug 的落盘根目录。

    PI v2.11.0 起 Client 通过 ``PI_USER_DATA_DIR`` 交出一个可写数据目录。macOS 的 .app 里项目
    根目录位于应用包内，普通用户账户不可写，所以不能回落到工作目录；Client 没设该变量时
    （例如 MFAAvalonia）与以前一致，仍用当前工作目录。
    """
    value = os.environ.get(ENV_USER_DATA_DIR, "").strip()
    return Path(value) if value else Path.cwd()


# 运行期会写这两个目录（用户配置、日志），链接进数据目录会把只读包内路径当成可写目录。
_WORK_ROOT_OWNED_ENTRIES = frozenset({"config", "debug"})
# v4.14.0 的 seed_work_root() 把这三项复制进 PI_USER_DATA_DIR；升级后要用链接替换旧副本。
_LEGACY_COPIED_ENTRIES = frozenset({"data", "interface.json"})


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _ensure_link(target: Path, source: Path, *, replace_existing: bool = False) -> int:
    """让 ``target`` 成为指向 ``source`` 的符号链接：不存在/指错就（重）建。

    返回 ``1``（建立/替换）、``0``（已正确或保留用户内容）、``-1``（链接失败）。
    ``replace_existing`` 为真时，已存在的真实文件/目录会被替换——只用于 v4.14.0
    播种出的 ``data/``、``interface.json`` 这类包内拥有的旧副本。
    """
    real_source = source.resolve()
    try:
        if target.is_symlink():
            if target.resolve() == real_source:
                return 0
            target.unlink()
        elif os.path.lexists(target):
            if not replace_existing:
                return 0
            _remove_path(target)
        target.symlink_to(real_source, target_is_directory=source.is_dir())
    except OSError:
        return -1
    return 1


def link_work_root(paths: RuntimePaths) -> tuple[int, int]:
    """把包内只读顶层条目链接进数据目录，让 ``work_root`` 作为 cwd 自足。

    返回 ``(改动条目数, 失败条目数)``。agent 在 PI_USER_DATA_DIR 下以数据目录为 cwd
    （``main.py``）：libs 下的二进制插件（drop_core.pyd 按 cwd 读
    ``data/combat/*.json`` 与 ``./interface.json``）和遗漏的裸相对路径没有调用
    ``RuntimePaths.data_path()``，数据目录必须能按 cwd 读到同一份文件，所以 ``data/``、
    ``resource/``、``tasks/``、``interface.json`` 等包内条目以符号链接接入；
    ``config/``、``debug/`` 是运行期可写目录，保持真实目录。

    从 v4.14.0 升级时，旧 ``seed_work_root()`` 复制出的 ``data/``、``interface.json``
    会被替换成链接，旧 ``version/`` 直接清掉；用户自建的其他真实目录保持不动。

    ``work_root == project_root``（便携客户端）时无事可做；``work_root`` 位于项目内时
    跳过数据目录自身及包含它的祖先，避免自引用。
    """
    if paths.work_root == paths.project_root:
        return 0, 0
    linked = 0
    failed = 0
    legacy_version = paths.work_root / "version"
    if legacy_version.is_symlink() or os.path.lexists(legacy_version):
        try:
            _remove_path(legacy_version)
            linked += 1
        except OSError:
            failed += 1
    for entry in paths.project_root.iterdir():
        if entry.name in _WORK_ROOT_OWNED_ENTRIES:
            continue
        real_entry = entry.resolve()
        if paths.work_root == real_entry or paths.work_root.is_relative_to(real_entry):
            continue
        result = _ensure_link(
            paths.work_root / entry.name,
            entry,
            replace_existing=entry.name in _LEGACY_COPIED_ENTRIES,
        )
        if result > 0:
            linked += 1
        elif result < 0:
            failed += 1
    return linked, failed


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    agent_dir: Path
    work_root: Path
    config_dir: Path
    resource_dir: Path
    data_dir: Path
    debug_dir: Path
    interface_file: Path

    def data_path(self, rel: str | Path) -> Path:
        """包内只读数据路径：``project_root / rel``（``data/``、``resource/`` 等）。

        data/ 只随包发布；需要按 cwd 读取的二进制插件走 ``link_work_root()``
        建出的链接，两边指向同一份文件。
        """
        return self.project_root / Path(rel)

    def user_path(self, rel: str | Path) -> Path:
        """用户所有文件路径：``work_root / rel``（``config/``、仓库快照等）。"""
        return self.work_root / Path(rel)


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
        # data/ 与 resource/ 只读、随包发布；cwd 读取由 link_work_root() 的链接兜底。
        resource_dir=resolved_project_root / "resource",
        data_dir=resolved_project_root / "data",
        debug_dir=resolved_work_root / "debug",
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
