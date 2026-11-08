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


def _seed_file(src: Path, dst: Path, overwrite_stale: bool) -> int:
    """单个基线文件播种：目标不存在，或允许时目标更旧，才复制（``copy2`` 带 mtime）。"""
    if dst.exists() and (not overwrite_stale or _mtime(dst) >= _mtime(src)):
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return 1


def _seed_tree(src_dir: Path, dst_dir: Path, overwrite_stale: bool) -> int:
    if not src_dir.is_dir():
        return 0
    copied = 0
    for base in src_dir.rglob("*"):
        if base.is_file():
            copied += _seed_file(base, dst_dir / base.relative_to(src_dir), overwrite_stale)
    return copied


def seed_work_root(paths: RuntimePaths) -> int:
    """把包内基线播种进数据目录，让 ``work_root`` 作为 cwd 自足，返回复制文件数。

    agent 在 PI_USER_DATA_DIR 下以数据目录为 cwd（``main.py``）：libs 下的二进制
    插件（drop_core.pyd 按 cwd 读 ``data/combat/*.json`` 与 ``./interface.json``）
    和遗漏的裸相对路径不经过 ``resolve()``，数据目录必须自带一份基线，cwd 读路径
    才与 ``resolve()`` 落到同一份文件。

    - ``data/``、``interface.json``：比 mtime，包内新基线可盖过旧副本（与 ``resolve()``
      的回落规则一致），热更产物（更新）不动；
    - ``config/``：只补缺不覆盖——这是用户数据，对应 ``resolve_user()`` 的
      「存在即赢」，旧的用户存档不能被新基线替换。

    ``work_root == project_root``（便携客户端）时无事可做。
    """
    if paths.work_root == paths.project_root:
        return 0
    copied = _seed_tree(paths.project_root / "data", paths.data_dir, overwrite_stale=True)
    copied += _seed_tree(paths.project_root / "config", paths.config_dir, overwrite_stale=False)
    interface = paths.project_root / "interface.json"
    if interface.is_file():
        copied += _seed_file(interface, paths.work_root / "interface.json", overwrite_stale=True)
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

    def resolve_user(self, rel: str | Path) -> Path:
        """用户所有文件的读路径：数据目录存在即赢，只回落包内基线。

        与 ``resolve`` 的区别在不比 mtime：config/、仓库快照这类文件是用户数据，
        哪怕是旧版本写下的也必须优先于新包体里的基线——比 mtime 会让新版基线
        静默覆盖用户存档。写侧直接用 ``work_root / rel``（如 ``config_dir``）。
        """
        relative = Path(rel)
        work_candidate = self.work_root / relative
        if self.work_root != self.project_root and not work_candidate.exists():
            return self.project_root / relative
        return work_candidate


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
