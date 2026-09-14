from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = PROJECT_ROOT / "tools" / "android-packaging.mjs"

CORE_SCRIPT = Path("Android/MaaFwApp/scripts/build_agent_bundle.py")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_repo(
    root: Path,
    *,
    core_tag: str = "3.13.15-maafw5.12.3",
    pin: str | None = "5.13.0",
    display_name: str = "M9A",
    slug: str = "m9a",
    agent: bool = True,
) -> Path:
    core = root / CORE_SCRIPT
    core.parent.mkdir(parents=True, exist_ok=True)
    core.write_text(f'CORE_TAG = "{core_tag}"\n', encoding="utf-8")
    if pin is not None:
        (root / "requirements.txt").write_text(f"# comment\nmaafw=={pin}\nloguru==0.7.3\n", encoding="utf-8")
    write_json(
        root / "maa-project.json",
        {"project": {"slug": slug, "displayName": display_name}, "maafw": {"channel": "beta", "version": ""}},
    )
    interface: dict[str, object] = {"interface_version": 2, "name": slug, "label": display_name, "import": []}
    if agent:
        interface["agent"] = [{"child_exec": "uv", "child_args": ["run", "python", "agent/main.py"]}]
    write_json(root / "interface.json", interface)
    return root


def run_resolver(root: Path, output: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
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
    )


def test_agent_project_outputs_tag_prefix_and_agent_flag(tmp_path: Path) -> None:
    write_repo(tmp_path)
    output = tmp_path / "github_output"

    result = run_resolver(tmp_path, output)

    assert result.returncode == 0, result.stdout + result.stderr
    written = output.read_text(encoding="utf-8")
    assert "maafw_tag=v5.12.3" in written
    assert "artifact_prefix=M9A" in written
    assert "has_agent=true" in written
    assert "client MaaFW tag : v5.12.3" in result.stdout
    assert "::warning::" in result.stdout  # requirements 的 5.13.0 与内核 5.12.3 不一致


def test_matching_pin_is_quiet(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning::" not in result.stdout


def test_pipeline_project_needs_no_python(tmp_path: Path) -> None:
    write_repo(tmp_path, pin=None, agent=False)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "has agent        : false" in result.stdout
    assert "（无 requirements.txt，纯 pipeline 项目）" in result.stdout
    assert "::warning::" not in result.stdout


def test_unsafe_display_name_falls_back_to_slug(tmp_path: Path) -> None:
    write_repo(tmp_path, display_name="我的项目", slug="demo")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "artifact prefix  : demo" in result.stdout


def test_broken_core_tag_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path, core_tag="broken")

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout


def test_missing_interface_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path)
    (tmp_path / "interface.json").unlink()

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
