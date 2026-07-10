import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.ci import download_drop_core


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()


@pytest.mark.parametrize(
    ("os_type", "arch", "platform_tag", "module_name"),
    [
        ("windows", "x64", "win-x64", "drop_core.cp313-win_amd64.pyd"),
        ("linux", "arm64", "linux-arm64", "drop_core.cpython-313-aarch64-linux-gnu.so"),
        ("darwin", "x64", "macos-x86_64", "drop_core.cpython-313-darwin.so"),
        ("darwin", "arm64", "macos-aarch64", "drop_core.cpython-313-darwin.so"),
    ],
)
def test_target_artifact_and_module_names(
    os_type: str,
    arch: str,
    platform_tag: str,
    module_name: str,
) -> None:
    assert download_drop_core.target_platform(os_type, arch) == (arch, platform_tag)
    assert download_drop_core.expected_module_name(os_type, arch) == module_name


def test_rejects_unsupported_architecture() -> None:
    with pytest.raises(ValueError, match="Unsupported target architecture"):
        download_drop_core.target_platform("linux", "riscv64")


def test_extract_module_accepts_only_expected_root_file(tmp_path: Path) -> None:
    module_name = "drop_core.cp313-win_amd64.pyd"
    archive_path = tmp_path / "drop_core.zip"
    dest_dir = tmp_path / "libs"
    dest_dir.mkdir()
    stale_module = dest_dir / "drop_core.cpython-313-x86_64-linux-gnu.so"
    stale_module.write_bytes(b"stale")
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(module_name, b"verified-module")

    module_path = download_drop_core.extract_module(archive_path, dest_dir, module_name)

    assert module_path.read_bytes() == b"verified-module"
    assert not stale_module.exists()


def test_extract_module_rejects_unexpected_archive_contents(tmp_path: Path) -> None:
    archive_path = tmp_path / "drop_core.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../drop_core.cp313-win_amd64.pyd", b"unsafe")

    with pytest.raises(RuntimeError, match="Unexpected drop_core archive contents"):
        download_drop_core.extract_module(
            archive_path,
            tmp_path / "libs",
            "drop_core.cp313-win_amd64.pyd",
        )


def test_download_asset_rejects_sha256_mismatch(monkeypatch: Any, tmp_path: Path) -> None:
    content = b"downloaded"
    asset = download_drop_core.ReleaseAsset(
        name="drop_core.zip",
        url="https://api.github.test/assets/1",
        digest=f"sha256:{hashlib.sha256(b'expected').hexdigest()}",
        size=len(content),
    )
    monkeypatch.setattr(
        download_drop_core.urllib.request,
        "urlopen",
        lambda request, timeout: FakeHTTPResponse(content),
    )
    dest_path = tmp_path / asset.name

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        download_drop_core.download_asset(asset, dest_path, "token")

    assert not dest_path.exists()
    assert not (tmp_path / "drop_core.zip.part").exists()


def test_main_requires_private_repo_token(monkeypatch: Any) -> None:
    monkeypatch.delenv("PRIVATE_REPO_TOKEN", raising=False)

    assert download_drop_core.main(["--os", "windows", "--arch", "x64"]) is False
