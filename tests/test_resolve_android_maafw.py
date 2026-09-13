from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ci import resolve_android_maafw

CORE_SCRIPT_TEXT = """\
CORE_REPO = "Aliothmoon/MaaAgentCoreAndroid"
CORE_TAG = "3.13.15-maafw5.12.3"
CORE_PY = "3.13.15"
"""


def _write_repo(
    root: Path,
    *,
    core_tag: str = "3.13.15-maafw5.12.3",
    pin: str = "5.13.0",
    project: object = None,
) -> Path:
    (root / resolve_android_maafw.CORE_SCRIPT).parent.mkdir(parents=True)
    (root / resolve_android_maafw.CORE_SCRIPT).write_text(f'CORE_TAG = "{core_tag}"\n', encoding="utf-8")
    (root / resolve_android_maafw.REQUIREMENTS).write_text(
        f"# comment\nmaafw=={pin}\nloguru==0.7.3\n", encoding="utf-8"
    )
    payload = (
        {"project": {"slug": "m9a", "displayName": "M9A"}, "maafw": {"channel": "beta", "version": ""}}
        if project is None
        else project
    )
    (root / resolve_android_maafw.PROJECT_CONFIG).write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_parse_core_version_reads_version_after_maafw() -> None:
    assert resolve_android_maafw.parse_core_version(CORE_SCRIPT_TEXT) == "5.12.3"


def test_parse_core_version_rejects_missing_core_tag() -> None:
    with pytest.raises(ValueError, match="CORE_TAG"):
        resolve_android_maafw.parse_core_version('CORE_TAG = "no-version-here"\n')


def test_parse_requirement_pin_reads_exact_pin() -> None:
    assert resolve_android_maafw.parse_requirement_pin("maafw==5.13.0\n") == "5.13.0"


def test_parse_requirement_pin_rejects_range() -> None:
    with pytest.raises(ValueError, match="maafw=="):
        resolve_android_maafw.parse_requirement_pin("maafw>=5.13.0\n")


def test_declared_target_prefers_explicit_version() -> None:
    assert resolve_android_maafw.declared_target({"maafw": {"channel": "beta", "version": "5.14.0"}}) == "5.14.0"


def test_declared_target_falls_back_to_channel() -> None:
    assert resolve_android_maafw.declared_target({"maafw": {"channel": "beta", "version": ""}}) == "beta 通道最新"
    assert resolve_android_maafw.declared_target({}) == "stable 通道最新"


def test_artifact_prefix_prefers_display_name() -> None:
    assert resolve_android_maafw.artifact_prefix({"project": {"slug": "m9a", "displayName": "M9A"}}) == "M9A"


def test_artifact_prefix_falls_back_to_slug_when_display_name_unsafe() -> None:
    assert resolve_android_maafw.artifact_prefix({"project": {"slug": "m9a", "displayName": "我的项目"}}) == "m9a"


def test_artifact_prefix_rejects_both_missing() -> None:
    with pytest.raises(ValueError, match="displayName"):
        resolve_android_maafw.artifact_prefix({})


def test_resolve_collects_every_field(tmp_path: Path) -> None:
    packaging = resolve_android_maafw.resolve(_write_repo(tmp_path))
    assert packaging.maafw_tag == "v5.12.3"
    assert packaging.artifact_prefix == "M9A"
    assert packaging.requirement_pin == "5.13.0"
    assert packaging.declared_target == "beta 通道最新"


def test_resolve_rejects_non_object_project_config(tmp_path: Path) -> None:
    _write_repo(tmp_path, project=["not", "an", "object"])
    with pytest.raises(ValueError, match="顶层必须是对象"):
        resolve_android_maafw.resolve(tmp_path)


def test_main_writes_github_output_and_warns_on_pin_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_repo(tmp_path)
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert resolve_android_maafw.main([str(tmp_path)]) == 0

    written = output.read_text(encoding="utf-8")
    assert "maafw_tag=v5.12.3" in written
    assert "artifact_prefix=M9A" in written
    printed = capsys.readouterr().out
    assert "::warning::" in printed  # requirements 的 5.13.0 与内核 5.12.3 不一致
    assert "client MaaFW tag : v5.12.3" in printed


def test_main_is_quiet_when_pin_matches_kernel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_repo(tmp_path, pin="5.12.3")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github_output"))

    assert resolve_android_maafw.main([str(tmp_path)]) == 0
    assert "::warning::" not in capsys.readouterr().out


def test_main_reports_broken_core_script(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_repo(tmp_path, core_tag="broken")
    assert resolve_android_maafw.main([str(tmp_path)]) == 1
    assert "::error::" in capsys.readouterr().out
