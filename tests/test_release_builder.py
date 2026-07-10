import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_release_package_excludes_python_cache_files(tmp_path: Path) -> None:
    write_json(tmp_path / "maa-project.lock.json", {"pending": []})
    write_json(
        tmp_path / "maa-project.json",
        {"runtime": {"mfa": {"enabled": True}, "mxu": {"enabled": False}}},
    )
    write_json(
        tmp_path / "interface.json",
        {
            "name": "m9a",
            "version": "v0.1.0",
            "resource": [],
            "import": [],
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
        (tmp_path / relative_path).mkdir(parents=True)

    (tmp_path / "runtimes/win-x64/native/MaaPiCli.exe").write_bytes(b"cli")
    (tmp_path / ".create-maa-project/runtime/mfaa/win-x64/MFAAvalonia.exe").write_bytes(b"gui")
    (tmp_path / ".create-maa-project/runtime/python/win-x64/python.exe").write_bytes(b"python")
    (tmp_path / "agent/bootstrap.py").write_text("# bootstrap\n", encoding="utf-8")
    (tmp_path / "agent/__pycache__/main.cpython-313.pyc").write_bytes(b"cache")
    (tmp_path / "agent/main.pyo").write_bytes(b"cache")
    (tmp_path / "requirements.txt").write_text("maafw\n", encoding="utf-8")

    result = subprocess.run(
        [
            "node",
            str(PROJECT_ROOT / "tools" / "build-release.mjs"),
            "--release-tag",
            "v0.0.0-test",
        ],
        cwd=tmp_path,
        env={**os.environ, "CREATE_MAA_PROJECT_RUNTIME_PLATFORM": "win-x64"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    package_agent = tmp_path / "dist/package-mfaa/agent"
    assert (package_agent / "bootstrap.py").is_file()
    assert not (package_agent / "__pycache__").exists()
    assert not (package_agent / "main.pyo").exists()
