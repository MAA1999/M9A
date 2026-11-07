import subprocess
from pathlib import Path

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


def run_bundler(package: Path, app: Path) -> subprocess.CompletedProcess[str]:
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
            "v1.2.3",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_macos_bundle_keeps_code_in_macos_and_data_in_resources(tmp_path: Path) -> None:
    package = write_release_package(tmp_path)
    app = tmp_path / "M9A.app"

    result = run_bundler(package, app)

    assert result.returncode == 0, result.stdout + result.stderr
    macos = app / "Contents/MacOS"
    portable = app / "Contents/Resources/MXU-portable"
    # Mach-O stays real in the code directory and is linked from the portable tree
    for relative in ("m9a", "agent/libs/drop_core.so", "maafw/libMaaFramework.dylib", "python/bin/python3"):
        assert (macos / relative).is_file()
        assert not (macos / relative).is_symlink()
        assert (portable / relative).is_symlink()
    # Data moves out of the code directory and is linked back, because codesign rejects it there
    for relative in ("interface.json", "resource/logo.png", "agent/main.py"):
        assert (portable / relative).is_file()
        assert not (portable / relative).is_symlink()
        assert (macos / relative).is_symlink()
        assert (macos / relative).resolve() == (portable / relative).resolve()

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
