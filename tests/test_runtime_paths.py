from pathlib import Path

from agent.utils import runtime_paths


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
