from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_fails_without_package_artifacts() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert workflow.count("package_dirs=(dist/package-*)") == 2
    assert "if (( ${#package_dirs[@]} == 0 )); then" in workflow
    assert 'for pkg_dir in "${package_dirs[@]}"; do' in workflow
    assert 'echo "[ERR] no release packages were generated"' in workflow
    assert "if-no-files-found: error" in workflow
