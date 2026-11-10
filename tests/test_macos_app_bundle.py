import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MACHO_MAGIC = b"\xcf\xfa\xed\xfe" + b"\x00" * 4


def write_release_package(root: Path) -> Path:
    package = root / "package-mxu"
    files = {
        "m9a": MACHO_MAGIC,
        "interface.json": b'{"name":"m9a"}',
        "resource/logo.png": b"png",
        "agent/main.py": b"# main\n",
        "agent/libs/drop_core.so": MACHO_MAGIC,
        "maafw/libMaaFramework.dylib": MACHO_MAGIC,
        "python/bin/python3": MACHO_MAGIC,
    }
    for relative, content in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return package


def run_bundler(
    package: Path,
    app: Path,
    *,
    version: str = "v1.2.3",
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "node",
            str(PROJECT_ROOT / "tools" / "macos-app-bundle.mjs"),
            "--package",
            str(package),
            "--app",
            str(app),
            "--skip-sign",
            "--version",
            version,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_macos_bundle_keeps_code_out_of_the_data_directory(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)
    app = tmp_path / "M9A.app"

    result = run_bundler(package, app)

    assert result.returncode == 0, result.stdout + result.stderr
    macos = app / "Contents/MacOS"
    portable = app / "Contents/Resources/MXU-portable"
    # Only the GUI executable is real inside the code directory; everything else is a link so the
    # bundle seal never has to cover mutable-looking data in Contents/MacOS.
    assert (macos / "m9a").is_file()
    assert not (macos / "m9a").is_symlink()
    for relative in ("interface.json", "agent", "resource", "maafw", "python"):
        assert (macos / relative).is_symlink(), relative
        assert (macos / relative).resolve() == (portable / relative).resolve()
    # The real files sit in the portable directory, so MXU and the Agent still resolve them
    for relative in ("interface.json", "agent/main.py", "agent/libs/drop_core.so", "python/bin/python3"):
        assert (portable / relative).is_file(), relative
        assert not (portable / relative).is_symlink()

    plist = (app / "Contents/Info.plist").read_text(encoding="utf-8")
    assert "<string>com.m9a.app</string>" in plist
    assert "<key>CFBundleExecutable</key>\n    <string>m9a</string>" in plist
    assert "<string>1.2.3</string>" in plist


def test_macos_bundle_rejects_package_without_entrypoint(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)
    (package / "m9a").unlink()

    result = run_bundler(package, tmp_path / "M9A.app")

    assert result.returncode != 0
    assert "release package has no entrypoint: m9a" in result.stdout + result.stderr


def test_macos_bundle_rejects_app_inside_the_package(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)

    result = run_bundler(package, package / "M9A.app")

    assert result.returncode != 0
    assert "--app must not live inside the release package" in result.stdout + result.stderr
    assert (package / "m9a").is_file()


def test_macos_bundle_rejects_app_that_contains_the_package(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)

    result = run_bundler(package, tmp_path)

    assert result.returncode != 0
    assert "--app must not contain the release package" in result.stdout + result.stderr
    assert (package / "m9a").is_file()


def test_macos_bundle_refuses_to_clean_the_working_directory(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)
    keep = tmp_path / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    result = run_bundler(package, tmp_path, cwd=tmp_path)

    assert result.returncode != 0
    assert "--app must not be the working directory" in result.stdout + result.stderr
    assert keep.is_file()


def test_macos_bundle_keeps_previous_output_when_the_package_is_invalid(tmp_path: Path) -> None:
    app = tmp_path / "M9A.app"
    previous = app / "Contents" / "Info.plist"
    previous.parent.mkdir(parents=True)
    previous.write_text("previous", encoding="utf-8")
    package = write_release_package(tmp_path)
    (package / "m9a").unlink()

    result = run_bundler(package, app)

    assert result.returncode != 0
    assert "release package has no entrypoint: m9a" in result.stdout + result.stderr
    assert previous.read_text(encoding="utf-8") == "previous"


def test_macos_bundle_resolves_symlinked_app_aliases(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    package = write_release_package(real)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("platform does not allow creating symlinks")

    result = run_bundler(package, alias)

    assert result.returncode != 0
    assert "--app must not contain the release package" in result.stdout + result.stderr
    assert (package / "m9a").is_file()


def test_macos_bundle_rejects_a_non_numeric_version_before_touching_output(tmp_path: Path) -> None:
    app = tmp_path / "M9A.app"
    previous = app / "Contents" / "Info.plist"
    previous.parent.mkdir(parents=True)
    previous.write_text("previous", encoding="utf-8")
    package = write_release_package(tmp_path)

    result = run_bundler(package, app, version="vnightly")

    assert result.returncode != 0
    assert "--version must start with a numeric version" in result.stdout + result.stderr
    assert previous.read_text(encoding="utf-8") == "previous"
    assert (package / "m9a").is_file()


def test_macos_bundle_uses_numeric_bundle_version_for_prereleases(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)
    app = tmp_path / "M9A.app"

    result = run_bundler(package, app, version="v2.0.0-rc.1")

    assert result.returncode == 0, result.stdout + result.stderr
    plist = (app / "Contents" / "Info.plist").read_text(encoding="utf-8")
    assert "<key>CFBundleShortVersionString</key>\n    <string>2.0.0</string>" in plist
    assert "<key>CFBundleVersion</key>\n    <string>2.0.0</string>" in plist
