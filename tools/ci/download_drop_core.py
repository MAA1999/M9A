"""从私有 release 下载并验证目标平台的 drop_core 模块。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PRIVATE_REPO = "MAA1999/drop-upload-sign"
RELEASE_TAG = "v1.3.1"
DEST_DIR = Path("agent/libs")
REQUEST_TIMEOUT = 30
MAX_MODULE_SIZE = 50 * 1024 * 1024

ARCH_MAPPING = {
    "amd64": "x64",
    "x86_64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str
    size: int


def normalize_arch(value: str) -> str:
    normalized = ARCH_MAPPING.get(value.lower(), value.lower())
    if normalized not in {"x64", "arm64"}:
        raise ValueError(f"Unsupported target architecture: {value}")
    return normalized


def target_platform(os_type: str, arch: str) -> tuple[str, str]:
    normalized_os = os_type.lower()
    normalized_arch = normalize_arch(arch)
    if normalized_os == "windows":
        return normalized_arch, f"win-{normalized_arch}"
    if normalized_os == "darwin":
        suffix = "x86_64" if normalized_arch == "x64" else "aarch64"
        return normalized_arch, f"macos-{suffix}"
    if normalized_os == "linux":
        return normalized_arch, f"linux-{normalized_arch}"
    raise ValueError(f"Unsupported target OS: {os_type}")


def detect_platform() -> tuple[str, str]:
    os_type = platform.system().lower()
    machine = platform.machine().lower()
    if os_type == "windows" and "ARM" in os.environ.get("PROCESSOR_IDENTIFIER", "").upper():
        machine = "arm64"
    return os_type, normalize_arch(machine)


def github_request(url: str, token: str, accept: str) -> urllib.request.Request:
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", accept)
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    return request


def get_release_asset(repo: str, tag: str, asset_name: str, token: str) -> ReleaseAsset:
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    request = github_request(api_url, token, "application/vnd.github+json")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))

    for asset in data.get("assets", []):
        if asset.get("name") != asset_name:
            continue
        digest = asset.get("digest")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise RuntimeError(f"Release asset has no SHA256 digest: {asset_name}")
        url = asset.get("url")
        size = asset.get("size")
        if not isinstance(url, str) or not isinstance(size, int) or size <= 0:
            raise RuntimeError(f"Release asset metadata is invalid: {asset_name}")
        return ReleaseAsset(name=asset_name, url=url, digest=digest, size=size)

    raise RuntimeError(f"Release asset not found: {asset_name}")


def download_asset(asset: ReleaseAsset, dest_path: Path, token: str) -> None:
    expected_hash = asset.digest.removeprefix("sha256:")
    temp_path = dest_path.with_suffix(f"{dest_path.suffix}.part")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.unlink(missing_ok=True)
    temp_path.unlink(missing_ok=True)

    request = github_request(asset.url, token, "application/octet-stream")
    downloaded_size = 0
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response, open(temp_path, "wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                downloaded_size += len(chunk)

        if downloaded_size != asset.size:
            raise RuntimeError(
                f"Release asset size mismatch for {asset.name}: expected {asset.size}, got {downloaded_size}"
            )
        if digest.hexdigest() != expected_hash:
            raise RuntimeError(f"Release asset SHA256 mismatch: {asset.name}")
        os.replace(temp_path, dest_path)
    finally:
        temp_path.unlink(missing_ok=True)


def expected_module_name(os_type: str, arch: str) -> str:
    normalized_arch = normalize_arch(arch)
    if os_type == "windows":
        platform_arch = "win_amd64" if normalized_arch == "x64" else "win_arm64"
        return f"drop_core.cp313-{platform_arch}.pyd"
    if os_type == "linux":
        platform_arch = "x86_64" if normalized_arch == "x64" else "aarch64"
        return f"drop_core.cpython-313-{platform_arch}-linux-gnu.so"
    if os_type == "darwin":
        return "drop_core.cpython-313-darwin.so"
    raise ValueError(f"Unsupported target OS: {os_type}")


def extract_module(archive_path: Path, dest_dir: Path, module_name: str) -> Path:
    temp_path = dest_dir / f".{module_name}.tmp"
    target_path = dest_dir / module_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    temp_path.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            files = [member for member in archive.infolist() if not member.is_dir()]
            if len(files) != 1 or files[0].filename != module_name or "\\" in files[0].filename:
                names = [member.filename for member in files]
                raise RuntimeError(f"Unexpected drop_core archive contents: {names}")
            if files[0].file_size <= 0 or files[0].file_size > MAX_MODULE_SIZE:
                raise RuntimeError(f"Unexpected drop_core module size: {files[0].file_size}")
            with archive.open(files[0], "r") as source, open(temp_path, "wb") as output:
                shutil.copyfileobj(source, output)

        if temp_path.stat().st_size <= 0:
            raise RuntimeError(f"Extracted drop_core module is empty: {module_name}")

        for pattern in ("drop_core*.pyd", "drop_core*.so"):
            for existing in dest_dir.glob(pattern):
                if existing != target_path:
                    existing.unlink()
        os.replace(temp_path, target_path)
        return target_path
    finally:
        temp_path.unlink(missing_ok=True)


def smoke_import() -> None:
    env = os.environ.copy()
    agent_dir = str(DEST_DIR.parent.resolve())
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [agent_dir, env.get("PYTHONPATH", "")]))
    subprocess.run(
        [sys.executable, "-c", "from libs import drop_core; print(drop_core.__file__)"],
        check=True,
        env=env,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and verify the target drop_core module")
    parser.add_argument("--os", choices=("windows", "linux", "darwin"), help="Target OS")
    parser.add_argument("--arch", help="Target architecture")
    parser.add_argument("--smoke-import", action="store_true", help="Import the extracted module on this runner")
    args = parser.parse_args(argv)
    if bool(args.os) != bool(args.arch):
        parser.error("--os and --arch must be provided together")
    return args


def main(argv: Sequence[str] | None = None) -> bool:
    args = parse_args(argv)
    token = os.environ.get("PRIVATE_REPO_TOKEN")
    if not token:
        print("PRIVATE_REPO_TOKEN is required", file=sys.stderr)
        return False

    if args.os and args.arch:
        os_type = args.os
        arch = normalize_arch(args.arch)
    else:
        os_type, arch = detect_platform()

    try:
        arch, platform_tag = target_platform(os_type, arch)
        artifact_name = f"drop_core-{platform_tag}-py3.13-{RELEASE_TAG}.zip"
        module_name = expected_module_name(os_type, arch)
        print(f"Target: {os_type}-{arch}")
        print(f"Asset: {artifact_name}")

        asset = get_release_asset(PRIVATE_REPO, RELEASE_TAG, artifact_name, token)
        archive_path = DEST_DIR / artifact_name
        try:
            download_asset(asset, archive_path, token)
            module_path = extract_module(archive_path, DEST_DIR, module_name)
        finally:
            archive_path.unlink(missing_ok=True)

        if args.smoke_import:
            smoke_import()
        print(f"Installed and verified: {module_path}")
        return True
    except Exception as error:
        print(f"drop_core setup failed: {error}", file=sys.stderr)
        return False


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
