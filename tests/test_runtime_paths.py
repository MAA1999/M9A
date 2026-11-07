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
