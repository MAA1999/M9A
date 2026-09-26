from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = PROJECT_ROOT / "tools" / "android-packaging.mjs"

FIXTURE_NAME = "releases-fixture.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_releases(root: Path, core: list[str], maafw: list[dict[str, object]] | None = None) -> None:
    """离线替身：resolver 改从该文件读 release 列表，不碰 GitHub API"""
    write_json(root / FIXTURE_NAME, {"core": core, "maafw": maafw or []})


def write_repo(
    root: Path,
    *,
    pin: str | None = "5.12.3",
    declared_version: str | None = None,
    channel: str = "beta",
    display_name: str = "M9A",
    slug: str = "m9a",
    agent: bool = True,
) -> Path:
    if pin is not None:
        (root / "requirements.txt").write_text(f"# comment\nmaafw=={pin}\nloguru==0.7.3\n", encoding="utf-8")
    write_json(
        root / "maa-project.json",
        {
            "project": {"slug": slug, "displayName": display_name},
            "maafw": {"channel": channel, "version": declared_version or ""},
        },
    )
    interface: dict[str, object] = {"interface_version": 2, "name": slug, "label": display_name, "import": []}
    if agent:
        interface["agent"] = [{"child_exec": "uv", "child_args": ["run", "python", "agent/main.py"]}]
    write_json(root / "interface.json", interface)
    write_releases(
        root,
        core=[
            "3.13.14-maafw5.12.3",
            "3.13.15-maafw5.12.3",
            "3.13.15-maafw5.13.1",
            "3.12.0-maafw5.11.0",
        ],
    )
    return root


def run_resolver(
    root: Path,
    output: Path | None = None,
    core_tag_env: str | None = None,
    with_fixture: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("AGENT_CORE_TAG", None)
    if core_tag_env is not None:
        env["AGENT_CORE_TAG"] = core_tag_env
    fixture = root / FIXTURE_NAME
    if with_fixture and fixture.exists():
        env["ANDROID_PACKAGING_RELEASES_FIXTURE"] = str(fixture)
    else:
        env.pop("ANDROID_PACKAGING_RELEASES_FIXTURE", None)
    if output is None:
        env.pop("GITHUB_OUTPUT", None)
    else:
        env["GITHUB_OUTPUT"] = str(output)
    return subprocess.run(
        ["node", str(RESOLVER)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
        timeout=60,
    )


def test_agent_project_picks_paired_core(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3")
    output = tmp_path / "github_output"

    result = run_resolver(tmp_path, output)

    assert result.returncode == 0, result.stdout + result.stderr
    written = output.read_text(encoding="utf-8")
    # 同一 maafw 配对取最新内核，client 原生库与绑定同版本
    assert "core_tag=3.13.15-maafw5.12.3" in written
    assert "maafw_tag=v5.12.3" in written
    assert "artifact_prefix=M9A" in written
    assert "has_agent=true" in written
    assert "::warning::" not in result.stdout


def test_requirements_bump_drives_maafw_tag(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.13.1")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "client MaaFW tag : v5.13.1" in result.stdout
    assert "agent core tag   : 3.13.15-maafw5.13.1" in result.stdout
    assert "::warning::" not in result.stdout


def test_missing_paired_core_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.14.0")

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert "maafw5.14.0" in result.stdout
    assert "5.13.1" in result.stdout  # 报错里列出现有配对


def test_agent_core_tag_override_wins(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.14.0")
    output = tmp_path / "github_output"

    # 不给 fixture：应急钉内核时不需要查 API
    result = run_resolver(tmp_path, output, core_tag_env="3.13.15-maafw5.13.0", with_fixture=False)

    assert result.returncode == 0, result.stdout + result.stderr
    written = output.read_text(encoding="utf-8")
    assert "core_tag=3.13.15-maafw5.13.0" in written
    # client 原生库跟着内核绑定走，固定版本被偏离要打 warning
    assert "maafw_tag=v5.13.0" in written
    assert "::warning::" in result.stdout


def test_broken_agent_core_tag_override_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path)

    result = run_resolver(tmp_path, core_tag_env="3.13.15", with_fixture=False)

    assert result.returncode == 1
    assert "::error::" in result.stdout


def test_declared_version_mismatch_warns_but_requirements_win(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3", declared_version="5.13.0")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "client MaaFW tag : v5.12.3" in result.stdout
    assert "::warning::" in result.stdout


def test_agent_project_requires_pinned_maafw(tmp_path: Path) -> None:
    write_repo(tmp_path, pin=None)

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert "maafw==" in result.stdout


def test_pipeline_project_uses_declared_version(tmp_path: Path) -> None:
    write_repo(tmp_path, pin=None, declared_version="5.13.0", agent=False)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "client MaaFW tag : v5.13.0" in result.stdout
    assert "has agent        : false" in result.stdout
    assert "::warning::" not in result.stdout


def test_pipeline_project_resolves_channel_latest(tmp_path: Path) -> None:
    maafw_releases: list[dict[str, object]] = [
        # GitHub releases 按新到旧返回，fixture 保持同序
        {"tag": "v5.15.0-beta.1", "prerelease": True},
        {"tag": "v5.14.0", "prerelease": False},
    ]

    write_repo(tmp_path, pin=None, channel="beta", agent=False)
    write_releases(tmp_path, core=[], maafw=maafw_releases)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    # beta 收 prerelease
    assert "client MaaFW tag : v5.15.0-beta.1" in result.stdout

    write_repo(tmp_path, pin=None, channel="stable", agent=False)
    write_releases(tmp_path, core=[], maafw=maafw_releases)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    # stable 不收 prerelease
    assert "client MaaFW tag : v5.14.0" in result.stdout


def test_unsafe_display_name_falls_back_to_slug(tmp_path: Path) -> None:
    write_repo(tmp_path, display_name="我的项目", slug="demo")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "artifact prefix  : demo" in result.stdout


def test_missing_interface_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path)
    (tmp_path / "interface.json").unlink()

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
