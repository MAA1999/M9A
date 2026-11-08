import os
from pathlib import Path

from agent.utils import runtime_paths


def _touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_default_work_root_prefers_client_user_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PI_USER_DATA_DIR", str(tmp_path))

    assert runtime_paths.default_work_root() == tmp_path


def test_default_work_root_falls_back_to_working_directory(monkeypatch) -> None:
    monkeypatch.delenv("PI_USER_DATA_DIR", raising=False)

    assert runtime_paths.default_work_root() == Path.cwd()


def test_default_work_root_ignores_blank_user_data_dir(monkeypatch) -> None:
    monkeypatch.setenv("PI_USER_DATA_DIR", "   ")

    assert runtime_paths.default_work_root() == Path.cwd()


def test_build_runtime_paths_keeps_project_reads_on_the_bundle_root(tmp_path: Path) -> None:
    project_root = tmp_path / "M9A.app/Contents/Resources/MXU-portable"
    work_root = tmp_path / "user-data"

    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    # Resources stay read-only inside the bundle; only config/debug/data move to the data dir.
    assert paths.interface_file == project_root.resolve() / "interface.json"
    assert paths.resource_dir == work_root.resolve() / "resource"
    assert paths.config_dir == work_root.resolve() / "config"
    assert paths.debug_dir == work_root.resolve() / "debug"
    assert paths.manifest_cache_file == work_root.resolve() / "data/manifest_cache.json"


def test_check_resource_version_reads_project_root_not_work_root(monkeypatch, tmp_path: Path) -> None:
    """MXU 把 PI_USER_DATA_DIR 给到 work_root；interface.json 仍在 bundle 项目根。"""
    project_root = tmp_path / "bundle/MXU-portable"
    work_root = tmp_path / "user-data"
    project_root.mkdir(parents=True)
    work_root.mkdir()
    (project_root / "interface.json").write_text('{"version": "v9.9.9"}', encoding="utf-8")

    from agent.utils import version_checker

    monkeypatch.setattr(
        version_checker,
        "get_runtime_paths",
        lambda: runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root),
    )

    result = version_checker.check_resource_version()

    # Reads the file (version picked up); fails only later at the missing rid field.
    assert result["current_version"] == "v9.9.9"
    assert result["error"] == "interface.json中未找到rid字段"


def _bundle_paths(tmp_path: Path) -> runtime_paths.RuntimePaths:
    project_root = tmp_path / "M9A.app/Contents/Resources/MXU-portable"
    work_root = tmp_path / "user-data"
    project_root.mkdir(parents=True)
    work_root.mkdir()
    return runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)


def test_resolve_returns_project_file_when_work_root_has_nothing(tmp_path: Path) -> None:
    paths = _bundle_paths(tmp_path)
    baseline = paths.project_root / "data/activity/cn.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("{}", encoding="utf-8")

    assert paths.resolve("data/activity/cn.json") == baseline


def test_resolve_prefers_newer_work_root_file(tmp_path: Path) -> None:
    paths = _bundle_paths(tmp_path)
    _touch(paths.project_root / "data/activity/cn.json", 1000)
    hot = paths.work_root / "data/activity/cn.json"
    _touch(hot, 2000)

    assert paths.resolve("data/activity/cn.json") == hot


def test_resolve_prefers_newer_bundle_baseline(tmp_path: Path) -> None:
    """新包体的基线 mtime 盖过旧的覆盖文件，避免读过时热更。"""
    paths = _bundle_paths(tmp_path)
    baseline = paths.project_root / "data/activity/cn.json"
    _touch(baseline, 2000)
    _touch(paths.work_root / "data/activity/cn.json", 1000)

    assert paths.resolve("data/activity/cn.json") == baseline


def test_resolve_uses_work_root_file_without_baseline(tmp_path: Path) -> None:
    paths = _bundle_paths(tmp_path)
    hot = paths.work_root / "data/redeem_code/cn.txt"
    _touch(hot, 1000)

    assert paths.resolve("data/redeem_code/cn.txt") == hot


def test_resolve_dir_prefers_work_root_directory(tmp_path: Path) -> None:
    paths = _bundle_paths(tmp_path)
    project_dir = paths.project_root / "data/redeem_code"
    work_dir = paths.work_root / "data/redeem_code"
    project_dir.mkdir(parents=True)
    work_dir.mkdir(parents=True)

    assert paths.resolve_dir("data/redeem_code") == work_dir


def test_resolve_falls_back_for_identical_roots(tmp_path: Path) -> None:
    paths = runtime_paths.build_runtime_paths(project_root=tmp_path, work_root=tmp_path)

    assert paths.resolve("data/x.json") == (tmp_path / "data/x.json").resolve()


def test_seed_work_root_copies_missing_and_stale_only(tmp_path: Path) -> None:
    paths = _bundle_paths(tmp_path)
    _touch(paths.project_root / "data/a.json", 1000)
    _touch(paths.project_root / "data/sub/b.json", 1000)
    # 数据目录里已有一份更新的热更文件，不应被旧基线覆盖
    fresh = paths.work_root / "data/a.json"
    _touch(fresh, 9000)

    assert runtime_paths.seed_work_root(paths) == 1
    assert (paths.work_root / "data/sub/b.json").exists()
    assert fresh.read_text(encoding="utf-8") == "x"
    assert os.path.getmtime(fresh) == 9000


def test_seed_work_root_seeds_interface_and_config_baseline(tmp_path: Path) -> None:
    paths = _bundle_paths(tmp_path)
    _touch(paths.project_root / "interface.json", 1000)
    _touch(paths.project_root / "config/hot_update.json", 1000)
    # 用户已有的 config 无论新旧都不能被基线覆盖（resolve_user 的「存在即赢」）
    _touch(paths.work_root / "config/m9a_data.json", 500)

    assert runtime_paths.seed_work_root(paths) == 2
    assert (paths.work_root / "interface.json").exists()
    assert (paths.work_root / "config/hot_update.json").exists()
    assert os.path.getmtime(paths.work_root / "config/m9a_data.json") == 500


def test_seed_work_root_noop_when_roots_identical(tmp_path: Path) -> None:
    paths = runtime_paths.build_runtime_paths(project_root=tmp_path, work_root=tmp_path)

    assert runtime_paths.seed_work_root(paths) == 0


def test_seed_work_root_copies_newer_bundle_baseline(tmp_path: Path) -> None:
    """下一版包体的 data/ 基线更新时，数据目录的旧副本要被覆盖（与 resolve() 一致）。"""
    paths = _bundle_paths(tmp_path)
    _touch(paths.project_root / "data/a.json", 9000)
    _touch(paths.work_root / "data/a.json", 1000)

    assert runtime_paths.seed_work_root(paths) == 1
    assert os.path.getmtime(paths.work_root / "data/a.json") == 9000


def test_seed_work_root_makes_cwd_self_sufficient(tmp_path: Path) -> None:
    """端到端目标：播种后按 cwd=work_root 的相对路径读到的内容与 resolve() 相同。"""
    paths = _bundle_paths(tmp_path)
    _touch(paths.project_root / "data/combat/drop_index.json", 2000)

    runtime_paths.seed_work_root(paths)

    cwd_read = (paths.work_root / "data/combat/drop_index.json").read_text(encoding="utf-8")
    assert cwd_read == paths.resolve("data/combat/drop_index.json").read_text(encoding="utf-8")
