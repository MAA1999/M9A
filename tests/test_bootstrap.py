from pathlib import Path

import pytest

from agent import bootstrap


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
