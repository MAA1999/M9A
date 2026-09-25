"""复用客户端那份 MaaFramework 原生库。

发行包不再随 agent 的 Python 运行时携带第二份原生库（各平台解压后 42~59 MiB）：MFAA 包用
``runtimes/<os>-<arch>/native``，MXU 包用 ``maafw/``，都是客户端已经在加载的同一批文件。

maa 在导入时就读 MAAFW_BINARY_PATH 定死库目录，所以本模块必须在任何会 import maa 的模块之前
调用（``utils`` 包在导入时就连带 import maa）。放成 agent/ 下的顶层模块是为了这个：按包路径
``agent.maafw_paths`` 导入同样安全，走 utils 包则不行。

开发态这两个目录要么不存在要么是空的（runtimes/ 由 pnpm sync:runtime 填充），此时不设变量，
继续用 wheel 自带的 site-packages/maa/bin。
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

ENV_NAME = "MAAFW_BINARY_PATH"

# agent/maafw_paths.py -> agent/ -> 项目根
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 文件名与 maa.library.Library.open 的拼接规则一致；agent 侧会加载前两个
_LIBRARY_NAMES: dict[str, tuple[str, str]] = {
    "win32": ("MaaFramework.dll", "MaaAgentServer.dll"),
    "darwin": ("libMaaFramework.dylib", "libMaaAgentServer.dylib"),
    "linux": ("libMaaFramework.so", "libMaaAgentServer.so"),
}

_PLATFORM_OS: dict[str, str] = {"win32": "win", "darwin": "osx", "linux": "linux"}

_PLATFORM_ARCH: dict[str, str] = {
    "amd64": "x64",
    "x86_64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def runtime_platform_tag() -> str | None:
    """返回 runtimes/ 下的平台目录名（win-x64 / linux-arm64 …），认不出则为 None。"""
    os_name = _PLATFORM_OS.get(sys.platform)
    arch = _PLATFORM_ARCH.get(platform.machine().lower())
    if os_name is None or arch is None:
        return None
    return f"{os_name}-{arch}"


def library_names() -> tuple[str, str] | None:
    """当前平台要加载的框架库与 agent 服务库文件名。"""
    return _LIBRARY_NAMES.get(sys.platform)


def candidate_library_dirs(project_root: Path | None = None) -> list[Path]:
    """客户端那份原生库的候选目录，按发行包布局排序。"""
    root = DEFAULT_PROJECT_ROOT if project_root is None else project_root
    candidates: list[Path] = []
    tag = runtime_platform_tag()
    if tag is not None:
        candidates.append(root / "runtimes" / tag / "native")
    candidates.append(root / "maafw")
    return candidates


def find_maafw_library_dir(project_root: Path | None = None) -> Path | None:
    """挑出真正可用的候选目录。

    只判断 exists() 不够：开发机上 ``runtimes/<tag>/native`` 是个空目录，指过去要到第一次
    创建 Tasker 时才炸 "Could not find module"。这里要求两个库文件都在。
    """
    names = library_names()
    if names is None:
        return None
    for candidate in candidate_library_dirs(project_root):
        if all((candidate / name).is_file() for name in names):
            return candidate
    return None


def ensure_maafw_binary_path(project_root: Path | str | None = None) -> Path | None:
    """在 import maa 之前调用，返回最终生效的原生库目录。

    已经设过 MAAFW_BINARY_PATH 的进程一律不动：Android runner 会把它指向 APK 的
    nativeLibraryDir，那里的布局与桌面的 runtimes/ 无关。返回 None 表示沿用 wheel 自带那份。
    """
    injected = os.environ.get(ENV_NAME, "").strip()
    if injected:
        return Path(injected)

    root = Path(project_root) if project_root is not None else None
    found = find_maafw_library_dir(root)
    if found is None:
        return None

    os.environ[ENV_NAME] = str(found)
    return found
