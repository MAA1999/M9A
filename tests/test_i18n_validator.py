import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {"zh_cn": "locales/zh_cn.json", "en_us": "locales/en_us.json"}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(PROJECT_ROOT / "tools" / "validate-i18n.mjs")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_i18n_validator_accepts_project_without_languages(tmp_path: Path) -> None:
    # i18n is opt-in: without `languages` a literal field, a literal focus message and a legacy
    # focus value are all pipeline/UI data rather than drift.
    write_json(
        tmp_path / "interface.json",
        {"interface_version": 2, "name": "demo", "label": "Demo", "import": []},
    )
    write_json(
        tmp_path / "resource/base/pipeline/Demo/Demo.json",
        {
            "Demo": {"action": "Click", "focus": {"Node.Action.Succeeded": {"content": "完成"}}},
            "DemoDone": {"focus": "旧版自定义 focus"},
        },
    )

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
            "description": "$Project.Missing",
            "languages": LANGUAGES,
        },
    )
    # Project.Missing is referenced but undefined; Project.Unused is defined but unreferenced
    write_json(tmp_path / "locales/zh_cn.json", {"Project.Label": "演示", "Project.Unused": "多余"})
    write_json(tmp_path / "locales/en_us.json", {"Project.Label": "Demo", "Project.Unused": "extra"})

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert 'missing "Project.Missing"' in output
    assert "Project.Unused" in output and "never referenced" in output


def test_i18n_validator_rejects_literal_text_once_languages_exist(tmp_path: Path) -> None:
    # A literal cannot follow the interface language, so it is drift in any language — not just Chinese.
    write_json(
        tmp_path / "interface.json",
        {
            "interface_version": 2,
            "name": "demo",
            "label": "Demo Project",
            "languages": {"zh_cn": "locales/zh_cn.json"},
        },
    )
    write_json(tmp_path / "locales/zh_cn.json", {})

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "literal text in a translatable field" in output
    assert "interface.json.label" in output


def test_i18n_validator_keeps_identifier_fields_literal(tmp_path: Path) -> None:
    # icon / license / contact hold a path or an identifier rather than display text.
    write_json(
        tmp_path / "interface.json",
        {
            "interface_version": 2,
            "name": "demo",
            "label": "$Project.Label",
            "icon": "resource/base/image/icon.png",
            "license": "AGPL-3.0-or-later",
            "contact": "https://example.invalid",
            "languages": {"zh_cn": "locales/zh_cn.json"},
        },
    )
    write_json(tmp_path / "locales/zh_cn.json", {"Project.Label": "演示"})

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_i18n_validator_rejects_unresolved_focus_key(tmp_path: Path) -> None:
    write_json(
        tmp_path / "interface.json",
        {"interface_version": 2, "name": "demo", "languages": LANGUAGES},
    )
    write_json(tmp_path / "locales/zh_cn.json", {})
    write_json(tmp_path / "locales/en_us.json", {})
    write_json(
        tmp_path / "resource/base/pipeline/Combat/Combat.json",
        {"Combat": {"action": "Click", "focus": {"Node.PipelineNode.Failed": "$Focus.Combat.StageNotFound"}}},
    )

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert 'missing "Focus.Combat.StageNotFound"' in output
    assert "resource/base/pipeline/Combat/Combat.json.Combat.focus.Node.PipelineNode.Failed" in output


def test_i18n_validator_rejects_literal_focus_content(tmp_path: Path) -> None:
    write_json(
        tmp_path / "interface.json",
        {"interface_version": 2, "name": "demo", "languages": {"zh_cn": "locales/zh_cn.json"}},
    )
    write_json(tmp_path / "locales/zh_cn.json", {})
    write_json(
        tmp_path / "resource/base/pipeline/Combat/Combat.json",
        {"Combat": {"action": "Click", "focus": {"Node.PipelineNode.Failed": "Stage not found"}}},
    )

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "literal text in a translatable field" in output
    assert "resource/base/pipeline/Combat/Combat.json.Combat.focus.Node.PipelineNode.Failed.content" in output


def test_i18n_validator_ignores_legacy_focus_values(tmp_path: Path) -> None:
    # A legacy focus value is arbitrary JSON, not a message-template map: reading it per character
    # would report one literal per Chinese character.
    write_json(
        tmp_path / "interface.json",
        {"interface_version": 2, "name": "demo", "languages": {"zh_cn": "locales/zh_cn.json"}},
    )
    write_json(tmp_path / "locales/zh_cn.json", {})
    write_json(tmp_path / "resource/base/pipeline/Demo/Demo.json", {"DemoDone": {"focus": "旧版自定义 focus"}})

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_i18n_validator_counts_default_pipeline_focus_as_reference(tmp_path: Path) -> None:
    # default_pipeline.json applies to every node, so its focus keys are referenced keys.
    write_json(
        tmp_path / "interface.json",
        {"interface_version": 2, "name": "demo", "languages": {"zh_cn": "locales/zh_cn.json"}},
    )
    write_json(tmp_path / "locales/zh_cn.json", {"Focus.Shared.Done": "全部完成"})
    write_json(
        tmp_path / "resource/base/default_pipeline.json",
        {"focus": {"Node.Action.Succeeded": {"content": "$Focus.Shared.Done"}}},
    )
    write_json(tmp_path / "resource/base/pipeline/Demo/Demo.json", {"Demo": {"action": "Click"}})

    result = run_validator(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_i18n_validator_reports_malformed_pipeline_without_traceback(tmp_path: Path) -> None:
    write_json(
        tmp_path / "interface.json",
        {"interface_version": 2, "name": "demo", "languages": {"zh_cn": "locales/zh_cn.json"}},
    )
    write_json(tmp_path / "locales/zh_cn.json", {})
    write_text(tmp_path / "resource/base/pipeline/Broken.json", "{ not json")
    write_json(tmp_path / "resource/base/pipeline/Demo/Demo.json", {"Demo": {"action": "Click"}})

    result = run_validator(tmp_path)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "Broken.json" in output
    assert "Traceback" not in output
