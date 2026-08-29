import multiprocessing
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent import bootstrap


def acquire_requirements_lock_and_touch(project_root: str, touched_path: str) -> None:
    with bootstrap.requirements_install_lock(Path(project_root), timeout_seconds=5.0):
        Path(touched_path).write_text("acquired\n", encoding="utf8")


def test_external_maafw_without_marker_does_not_skip_requirements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bootstrap, "is_package_installed", lambda _name: True)
    monkeypatch.setattr(bootstrap, "is_running_in_project_venv", lambda _root: False)

    assert bootstrap.needs_requirement_install(tmp_path, "digest") is True


def test_matching_marker_skips_reinstall_when_maafw_is_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "debug" / bootstrap.REQUIREMENTS_MARKER
    marker.parent.mkdir()
    marker.write_text("digest\n", encoding="utf8")
    monkeypatch.setattr(bootstrap, "is_package_installed", lambda _name: True)
    monkeypatch.setattr(bootstrap, "is_running_in_project_venv", lambda _root: False)

    assert bootstrap.needs_requirement_install(tmp_path, "digest") is False


def test_system_python_bin_is_not_treated_as_embedded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bootstrap.sys, "executable", "/usr/bin/python3")

    assert bootstrap.is_running_in_embedded_python(tmp_path) is False


def test_macos_packaged_python_path_is_treated_as_embedded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    embedded_python = tmp_path / "python" / "bin" / "python3"
    monkeypatch.setattr(bootstrap.sys, "executable", str(embedded_python))

    assert bootstrap.is_running_in_embedded_python(tmp_path) is True


def test_project_venv_marker_takes_priority_over_embedded_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bootstrap, "is_running_in_project_venv", lambda _root: True)
    monkeypatch.setattr(bootstrap, "is_running_in_embedded_python", lambda _root: True)

    assert bootstrap.requirements_marker(tmp_path) == tmp_path / ".venv" / bootstrap.REQUIREMENTS_MARKER


def test_waiting_installer_rechecks_marker_after_acquiring_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("maafw==1.0.0\n", encoding="utf8")
    monkeypatch.setattr(bootstrap, "requirements_install_lock", lambda _root: nullcontext())
    monkeypatch.setattr(bootstrap, "needs_requirement_install", lambda _root, _digest: False)
    monkeypatch.setattr(
        bootstrap,
        "install_from_local_wheels",
        lambda *_args: pytest.fail("local wheel installation should have been skipped"),
    )
    monkeypatch.setattr(
        bootstrap,
        "install_from_indexes",
        lambda *_args: pytest.fail("index installation should have been skipped"),
    )

    bootstrap.ensure_requirements_installed(tmp_path, requirements, "digest")


def test_requirements_lock_retries_and_releases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock_attempts = iter((False, True))
    monotonic_values = iter((0.0, 0.0))
    unlock = Mock()
    sleep = Mock()
    monkeypatch.setattr(bootstrap, "try_lock_file", lambda _handle: next(lock_attempts))
    monkeypatch.setattr(bootstrap, "unlock_file", unlock)
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(bootstrap.time, "sleep", sleep)

    with bootstrap.requirements_install_lock(tmp_path, timeout_seconds=1.0):
        pass

    sleep.assert_called_once_with(0.1)
    unlock.assert_called_once()


def test_requirements_lock_timeout_stops_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monotonic_values = iter((0.0, 2.0))
    warnings: list[str] = []
    monkeypatch.setattr(bootstrap, "try_lock_file", lambda _handle: False)
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(bootstrap, "warn", lambda _root, message: warnings.append(message))

    with pytest.raises(SystemExit):
        with bootstrap.requirements_install_lock(tmp_path, timeout_seconds=1.0):
            pass

    assert len(warnings) == 1


def test_requirements_lock_serializes_processes(tmp_path: Path) -> None:
    touched_path = tmp_path / "second-process-acquired"
    process = multiprocessing.get_context("spawn").Process(
        target=acquire_requirements_lock_and_touch,
        args=(str(tmp_path), str(touched_path)),
    )

    with bootstrap.requirements_install_lock(tmp_path, timeout_seconds=5.0):
        process.start()
        time.sleep(0.3)
        assert not touched_path.exists()

    process.join(timeout=5.0)
    assert process.exitcode == 0
    assert touched_path.exists()


def test_requirements_marker_is_written_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bootstrap, "is_running_in_project_venv", lambda _root: False)
    monkeypatch.setattr(bootstrap, "is_running_in_embedded_python", lambda _root: False)

    bootstrap.write_requirements_marker(tmp_path, "digest")

    marker = tmp_path / "debug" / bootstrap.REQUIREMENTS_MARKER
    assert marker.read_text(encoding="utf8") == "digest\n"
    assert not marker.with_name(marker.name + ".tmp").exists()


def test_empty_maafw_version_reports_invalid_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(bootstrap.importlib.metadata, "version", lambda _name: None)
    monkeypatch.setattr(bootstrap, "warn", lambda _root, message: warnings.append(message))

    bootstrap.check_maafw(tmp_path)

    assert warnings == ["Python package maafw has invalid or incomplete metadata"]
