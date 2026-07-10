import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def prepare_release_project(root: Path, imports: list[str] | None = None) -> None:
    root.mkdir(exist_ok=True)
    write_json(root / "maa-project.lock.json", {"pending": []})
    write_json(
        root / "maa-project.json",
        {"runtime": {"mfa": {"enabled": True}, "mxu": {"enabled": False}}},
    )
    write_json(
        root / "interface.json",
        {
            "name": "m9a",
            "version": "v0.1.0",
            "resource": [],
            "import": imports or [],
            "agent": [{}],
        },
    )

    for relative_path in (
        "tasks",
        "resource",
        "runtimes/win-x64/native",
        "libs/MaaAgentBinary",
        "plugins",
        "agent/__pycache__",
        ".create-maa-project/runtime/mfaa/win-x64",
        ".create-maa-project/runtime/python/win-x64",
    ):
        (root / relative_path).mkdir(parents=True)

    (root / "runtimes/win-x64/native/MaaPiCli.exe").write_bytes(b"cli")
    (root / ".create-maa-project/runtime/mfaa/win-x64/MFAAvalonia.exe").write_bytes(b"gui")
    (root / ".create-maa-project/runtime/python/win-x64/python.exe").write_bytes(b"python")
    (root / "agent/bootstrap.py").write_text("# bootstrap\n", encoding="utf-8")
    (root / "agent/__pycache__/main.cpython-313.pyc").write_bytes(b"cache")
    (root / "agent/main.pyo").write_bytes(b"cache")
    (root / "requirements.txt").write_text("maafw\n", encoding="utf-8")


def run_release_builder(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "node",
            str(PROJECT_ROOT / "tools" / "build-release.mjs"),
            "--release-tag",
            "v0.0.0-test",
        ],
        cwd=root,
        env={**os.environ, "CREATE_MAA_PROJECT_RUNTIME_PLATFORM": "win-x64"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_release_package_excludes_python_cache_files(tmp_path: Path) -> None:
    prepare_release_project(tmp_path)
    result = run_release_builder(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    package_agent = tmp_path / "dist/package-mfaa/agent"
    assert (package_agent / "bootstrap.py").is_file()
    assert not (package_agent / "__pycache__").exists()
    assert not (package_agent / "main.pyo").exists()


def test_release_builder_rejects_paths_outside_project_root(tmp_path: Path) -> None:
    outside_path = tmp_path / "outside.json"
    outside_path.write_text("{}\n", encoding="utf-8")

    for index, unsafe_path in enumerate(("../outside.json", outside_path.resolve().as_posix())):
        project_root = tmp_path / f"project-{index}"
        prepare_release_project(project_root, [unsafe_path])

        result = run_release_builder(project_root)

        assert result.returncode != 0
        assert "release paths must stay within the project root" in result.stdout + result.stderr
