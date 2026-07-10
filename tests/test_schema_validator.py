import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_schema_validator_rejects_invalid_nested_task(tmp_path: Path) -> None:
    shutil.copytree(PROJECT_ROOT / "tools" / "schema", tmp_path / "tools" / "schema")
    shutil.copy2(PROJECT_ROOT / "interface.json", tmp_path / "interface.json")
    shutil.copy2(PROJECT_ROOT / "package.json", tmp_path / "package.json")
    nested_task = tmp_path / "tasks" / "presets" / "invalid.json"
    nested_task.parent.mkdir(parents=True)
    nested_task.write_text("[]\n", encoding="utf-8")

    result = subprocess.run(
        ["node", str(PROJECT_ROOT / "tools" / "validate-schema.mjs")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}".replace("\\", "/")

    assert result.returncode == 1
    assert "tasks/presets/invalid.json" in output
    assert "must be object" in output
