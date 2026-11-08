from __future__ import annotations

import os
import shutil
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


def _mtime(path: Path) -> float:
    """文件/目录的 mtime；不存在返回 -inf，让『存在的一方』自然胜出。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return float("-inf")


def seed_data_dir(paths: RuntimePaths) -> int:
    """把 ``project_root/data`` 的基线播种进 ``work_root/data``，返回复制文件数。

    数据目录（PI_USER_DATA_DIR/data）是项目 data/ 的覆盖层：热更写这里、读侧
    ``resolve()`` 优先取这里。但 libs 下的二进制插件（drop_core.pyd 按 cwd 读
    ``data/combat/*.json``）和遗漏的裸 ``open("data/...")`` 不会走 resolve，得让
    数据目录自带一份基线：数据目录没有或更旧的文件按 ``copy2`` 带 mtime 复制，
    已存在且更新（热更产物）的不动。work_root == project_root 时无事可做。
    """
    src = paths.project_root / "data"
    dst = paths.data_dir
    if paths.work_root == paths.project_root or not src.is_dir():
        return 0
    copied = 0
    for base in src.rglob("*"):
        if not base.is_file():
            continue
        target = dst / base.relative_to(src)
        if _mtime(target) >= _mtime(base):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base, target)
        copied += 1
    return copied


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    agent_dir: Path
    work_root: Path
    config_dir: Path
    resource_dir: Path
    data_dir: Path
    debug_dir: Path
    requirements_file: Path
    interface_file: Path
    manifest_cache_file: Path

    def resolve(self, rel: str | Path) -> Path:
        """解析项目内的相对路径：**写** 始终落 ``work_root``（数据目录），**读** 走覆盖层。

        覆盖层规则：数据目录里的同名文件存在且 mtime 不早于包内基线时用它，否则回落
        ``project_root``。macOS .app 下 project_root 在包内（只读、随版本发布），work_root
        是 PI_USER_DATA_DIR——首跑读包内基线，热更后读新下载的文件，下一版包体的新基线
        mtime 又会盖过旧的覆盖文件，不需要额外清理。
        """
        relative = Path(rel)
        work_candidate = self.work_root / relative
        project_candidate = self.project_root / relative
        if self.work_root == self.project_root:
            return project_candidate
        if _mtime(work_candidate) >= _mtime(project_candidate):
            return work_candidate
        return project_candidate

    def resolve_dir(self, rel: str | Path) -> Path:
        """目录版 ``resolve``：用于 glob/listdir 这类需要整目录的调用点。"""
        relative = Path(rel)
        work_candidate = self.work_root / relative
        project_candidate = self.project_root / relative
        if self.work_root == self.project_root:
            return project_candidate
        if work_candidate.is_dir() and _mtime(work_candidate) >= _mtime(project_candidate):
            return work_candidate
        return project_candidate


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
        # 热更新（Mirror酱 manifest）写 work_root 下的 data/、version/：Windows/Linux 下
        # work_root 与项目目录相同，写=读一致；macOS .app 下读取侧经 resolve() 走覆盖层
        # （数据目录新文件优先、否则回落包内基线），两边始终对齐。
        resource_dir=resolved_work_root / "resource",
        data_dir=resolved_work_root / "data",
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
