import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(PROJECT_ROOT / "tools" / "validate-i18n.mjs")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_i18n_validator_accepts_project_without_languages(tmp_path: Path) -> None:
    write_json(tmp_path / "interface.json", {"interface_version": 2, "name": "demo", "label": "Demo", "import": []})

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no translation files are declared" in result.stdout


def test_i18n_validator_rejects_keys_without_languages(tmp_path: Path) -> None:
    write_json(tmp_path / "interface.json", {"interface_version": 2, "name": "demo", "label": "$Project.Label"})

    result = run_validator(tmp_path)

    assert result.returncode == 1
    assert "no `languages` block" in result.stdout + result.stderr


def test_i18n_validator_rejects_unresolved_and_orphan_keys(tmp_path: Path) -> None:
    write_json(
        tmp_path / "interface.json",
        {
            "interface_version": 2,
            "name": "demo",
            "label": "$Project.Label",
            "languages": {"zh_cn": "i18n/zh_cn.json", "en_us": "i18n/en_us.json"},
        },
    )
    write_json(tmp_path / "i18n/zh_cn.json", {"Project.Label": "演示", "Project.Unused": "多余"})
    write_json(tmp_path / "i18n/en_us.json", {"Project.Label": "Demo", "Project.Unused": "extra"})

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "Project.Unused" in output and "never referenced" in output


def test_i18n_validator_rejects_hard_coded_chinese(tmp_path: Path) -> None:
    write_json(
        tmp_path / "interface.json",
        {
            "interface_version": 2,
            "name": "demo",
            "label": "$Project.Label",
            "languages": {"zh_cn": "i18n/zh_cn.json"},
        },
    )
    write_json(tmp_path / "i18n/zh_cn.json", {"Project.Label": "演示"})
    write_json(tmp_path / "tasks/Demo.json", {"task": [{"name": "demo", "entry": "Demo", "description": "硬编码"}]})

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "hard-coded Chinese" in output
