from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_USER_DATA_DIR = "PI_USER_DATA_DIR"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_work_root() -> Path:
    """返回 config / debug 的落盘根目录。

    Client 通过 ``PI_USER_DATA_DIR`` 交出一个可写数据目录。macOS 的 .app 里项目根目录位于应用
    包内，普通用户账户不可写，所以不能回落到工作目录；Client 没设该变量时（例如 MFAAvalonia）
    与以前一致，仍用当前工作目录。
    """
    value = os.environ.get(ENV_USER_DATA_DIR, "").strip()
    # 相对值按调用时的 cwd 收成绝对路径：main.py 会在 chdir 前把 env 写回绝对路径，
    # 这里再 resolve 一次是兜底，避免漏网的相对值在 chdir 后多嵌一层。
    return Path(value).expanduser().resolve() if value else Path.cwd()


# Client 把配置和日志写在数据目录；不能把这两项链到只读包内。
_WORK_ROOT_OWNED_ENTRIES = frozenset({"config", "debug"})


def _ensure_link(target: Path, source: Path) -> int:
    """让 ``target`` 成为指向 ``source`` 的符号链接：不存在/指错就（重）建，

    真实文件/目录（用户内容）与已正确的链接都原样保留。目标平台不支持符号链接
    时静默跳过。
    """
    real_source = source.resolve()
    try:
        if target.is_symlink():
            if target.resolve() == real_source:
                return 0
            target.unlink()
        elif os.path.lexists(target):
            return 0
        target.symlink_to(real_source, target_is_directory=source.is_dir())
    except OSError:
        return 0
    return 1


def link_work_root(paths: RuntimePaths) -> int:
    """把包内只读顶层条目链进数据目录，让 ``work_root`` 作为 cwd 自足，返回改动条目数。

    agent 在 PI_USER_DATA_DIR 下以数据目录为 cwd（``main.py``）：按 cwd 读相对路径的
    组件必须能在数据目录看到同一份文件。``resource/``、``agent/``、``interface.json``
    等建成指向包内实际路径的符号链接；指错（.app 被移动）会重链，用户自建的同名真实
    文件不碰。``config/``、``debug/`` 不链。

    ``work_root == project_root``（便携客户端）时无事可做；``work_root`` 位于项目内时
    跳过数据目录自身及包含它的祖先，否则会给 ``work_root`` 建出指回自身的链接。
    """
    if paths.work_root == paths.project_root:
        return 0
    linked = 0
    for entry in paths.project_root.iterdir():
        if entry.name in _WORK_ROOT_OWNED_ENTRIES:
            continue
        real_entry = entry.resolve()
        if paths.work_root == real_entry or paths.work_root.is_relative_to(real_entry):
            continue
        linked += _ensure_link(paths.work_root / entry.name, entry)
    return linked


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    agent_dir: Path
    work_root: Path
    config_dir: Path
    resource_dir: Path
    debug_dir: Path
    interface_file: Path

    def resolve(self, rel: str | Path) -> Path:
        """包内项目文件：始终读 ``project_root``。

        写用户数据用 ``work_root / rel``（如 ``config_dir``）。
        """
        return self.project_root / Path(rel)


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
        resource_dir=resolved_project_root / "resource",
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
