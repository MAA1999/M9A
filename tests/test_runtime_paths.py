import os
from pathlib import Path

import pytest

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


def test_default_work_root_resolves_a_relative_user_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PI_USER_DATA_DIR", "userdata")

    # main.py 在 chdir 前会把值写回成绝对路径；这里单独验证回退分支也不会返回相对路径，
    # 否则 chdir 之后 build_runtime_paths 会按新 cwd 再解析一次，数据目录多嵌一层。
    assert runtime_paths.default_work_root() == tmp_path / "userdata"


def test_build_runtime_paths_keeps_package_reads_on_the_bundle_root(tmp_path: Path) -> None:
    project_root = tmp_path / "M9A.app/Contents/Resources/MXU-portable"
    work_root = tmp_path / "user-data"

    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    # data/ 与 resource/ 随包只读；只有 config/debug 落在数据目录。
    assert paths.interface_file == project_root.resolve() / "interface.json"
    assert paths.data_dir == project_root.resolve() / "data"
    assert paths.resource_dir == project_root.resolve() / "resource"
    assert paths.config_dir == work_root.resolve() / "config"
    assert paths.debug_dir == work_root.resolve() / "debug"


def test_data_path_and_user_path_join_the_expected_root(tmp_path: Path) -> None:
    paths = runtime_paths.build_runtime_paths(project_root=tmp_path / "bundle", work_root=tmp_path / "user")

    assert paths.data_path("data/combat/items.json") == paths.project_root / "data/combat/items.json"
    assert paths.user_path("config/m9a.json") == paths.work_root / "config/m9a.json"
    assert paths.data_path(tmp_path / "absolute.json") == tmp_path / "absolute.json"


def test_link_work_root_links_package_entries_and_keeps_runtime_dirs(tmp_path: Path) -> None:
    project_root = tmp_path / "bundle"
    work_root = tmp_path / "user-data"
    project_root.mkdir()
    work_root.mkdir()
    _touch(project_root / "data/combat/items.json", 1000)
    _touch(project_root / "resource/base/image/logo.png", 1000)
    _touch(project_root / "interface.json", 1000)
    (project_root / "config").mkdir()
    (work_root / "config").mkdir()
    (work_root / "config/user.json").write_text("user", encoding="utf-8")
    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    linked, failed = runtime_paths.link_work_root(paths)

    data_link = work_root / "data"
    if not data_link.is_symlink():
        pytest.skip("platform does not allow creating symlinks")
    assert failed == 0
    assert linked > 0
    assert (data_link / "combat/items.json").is_file()
    assert (work_root / "resource").is_symlink()
    assert (work_root / "interface.json").is_symlink()
    # config/ 是运行期可写目录：保持真实目录与用户内容。
    assert (work_root / "config").is_dir()
    assert not (work_root / "config").is_symlink()
    assert (work_root / "config/user.json").read_text(encoding="utf-8") == "user"


def test_link_work_root_relinks_a_wrong_target_and_preserves_user_files(tmp_path: Path) -> None:
    project_root = tmp_path / "bundle"
    work_root = tmp_path / "user-data"
    project_root.mkdir()
    work_root.mkdir()
    (project_root / "resource").mkdir()
    _touch(project_root / "resource/logo.png", 1000)
    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)
    wrong = work_root / "resource"
    try:
        wrong.symlink_to(tmp_path / "elsewhere")
    except OSError:
        pytest.skip("platform does not allow creating symlinks")

    runtime_paths.link_work_root(paths)

    assert wrong.resolve() == (project_root / "resource").resolve()
    user_file = work_root / "keep.txt"
    user_file.write_text("keep", encoding="utf-8")
    runtime_paths.link_work_root(paths)
    assert user_file.read_text(encoding="utf-8") == "keep"


def test_link_work_root_replaces_legacy_seeded_copies(tmp_path: Path) -> None:
    project_root = tmp_path / "bundle"
    work_root = tmp_path / "user-data"
    project_root.mkdir()
    work_root.mkdir()
    _touch(project_root / "data/combat/items.json", 1000)
    (project_root / "interface.json").write_text("new", encoding="utf-8")
    # v4.14.0 seed_work_root() 遗留的真实副本
    _touch(work_root / "data/combat/items.json", 500)
    (work_root / "interface.json").write_text("stale", encoding="utf-8")
    (work_root / "version").mkdir()
    (work_root / "version/hot.json").write_text("x", encoding="utf-8")
    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    linked, failed = runtime_paths.link_work_root(paths)

    # version/ 只剩热更元数据，直接清掉。
    assert not (work_root / "version").exists()
    data_link = work_root / "data"
    if not data_link.is_symlink():
        pytest.skip("platform does not allow creating symlinks")
    assert failed == 0
    assert linked >= 3
    assert (data_link / "combat/items.json").is_file()
    assert (work_root / "interface.json").is_symlink()
    assert (work_root / "interface.json").read_text(encoding="utf-8") == "new"
    assert not list(work_root.glob("*.m9a-*"))


def test_link_work_root_keeps_legacy_copies_when_linking_fails(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path / "bundle"
    work_root = tmp_path / "user-data"
    project_root.mkdir()
    work_root.mkdir()
    _touch(project_root / "data/combat/items.json", 1000)
    (project_root / "interface.json").write_text("new", encoding="utf-8")
    _touch(work_root / "data/combat/items.json", 500)
    (work_root / "interface.json").write_text("stale", encoding="utf-8")
    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    def deny_symlink(self: Path, target: Path, target_is_directory: bool = False) -> None:
        raise OSError("symlink denied")

    monkeypatch.setattr(Path, "symlink_to", deny_symlink)

    linked, failed = runtime_paths.link_work_root(paths)

    assert linked == 0
    assert failed >= 2
    # 链接失败时旧副本不能被提前删掉。
    assert (work_root / "data/combat/items.json").is_file()
    assert (work_root / "interface.json").read_text(encoding="utf-8") == "stale"


def test_link_work_root_counts_failed_links(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path / "bundle"
    work_root = tmp_path / "user-data"
    project_root.mkdir()
    work_root.mkdir()
    _touch(project_root / "data/a.json", 1000)
    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    def deny_symlink(self: Path, target: Path, target_is_directory: bool = False) -> None:
        raise OSError("symlink denied")

    monkeypatch.setattr(Path, "symlink_to", deny_symlink)

    linked, failed = runtime_paths.link_work_root(paths)

    assert linked == 0
    assert failed == 1


def test_link_work_root_noop_when_roots_identical(tmp_path: Path) -> None:
    paths = runtime_paths.build_runtime_paths(project_root=tmp_path, work_root=tmp_path)

    assert runtime_paths.link_work_root(paths) == (0, 0)


def test_link_work_root_skips_a_project_local_work_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _touch(project_root / "data/a.json", 1000)
    work_root = project_root / "userdata"
    work_root.mkdir()
    paths = runtime_paths.build_runtime_paths(project_root=project_root, work_root=work_root)

    linked, failed = runtime_paths.link_work_root(paths)

    assert not (work_root / "userdata").exists()
    link = work_root / "data"
    if not link.is_symlink():
        pytest.skip("platform does not allow creating symlinks")
    assert failed == 0
    assert (link / "a.json").is_file()
