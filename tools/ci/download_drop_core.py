"""
下载 drop_core 模块

从私有仓库的 release 下载对应平台的 drop_core 模块
"""

import os
import sys
import platform
import urllib.request
import zipfile
import shutil
import argparse

# 私有仓库信息
PRIVATE_REPO = "MAA1999/drop-upload-sign"  # 修改为你的私有仓库
RELEASE_TAG = "v1.2.6"  # 修改为要下载的版本

# 目标目录
DEST_DIR = os.path.join("agent", "libs")


def get_platform_info():
    """获取当前平台信息"""
    os_type = platform.system().lower()
    os_arch = platform.machine().lower()

    # 标准化架构名称
    arch_mapping = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }

    # Windows ARM64 检测
    if os_type == "windows":
        processor_id = os.environ.get("PROCESSOR_IDENTIFIER", "")
        if "ARM" in processor_id.upper():
            os_arch = "arm64"

    arch = arch_mapping.get(os_arch, os_arch)

    # 平台标签
    if os_type == "windows":
        platform_tag = f"win-{arch}"
    elif os_type == "darwin":
        platform_tag = f"macos-{'x86_64' if arch == 'x64' else 'aarch64'}"
    elif os_type == "linux":
        platform_tag = f"linux-{arch}"
    else:
        platform_tag = f"{os_type}-{arch}"

    return os_type, arch, platform_tag


def get_python_version():
    """获取 Python 版本"""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def get_asset_download_url(repo, tag, asset_name, token=None):
    """Get asset download URL from GitHub API"""
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"

    request = urllib.request.Request(api_url)
    if token:
        request.add_header("Authorization", f"token {token}")
    request.add_header("Accept", "application/vnd.github.v3+json")

    try:
        with urllib.request.urlopen(request) as response:
            import json

            data = json.loads(response.read().decode())

            # Find the asset by name
            for asset in data.get("assets", []):
                if asset["name"] == asset_name:
                    return asset["url"]  # API URL, not browser_download_url

            print(f"Asset not found: {asset_name}")
            return None
    except Exception as e:
        print(f"Failed to get asset info: {e}")
        return None


def download_file(url, dest_path, token=None):
    """Download file"""
    print(f"Downloading: {url}")
    print(f"To: {dest_path}")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"token {token}")
    request.add_header("Accept", "application/octet-stream")

    try:
        with urllib.request.urlopen(request) as response:
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(response, f)
        print("Download complete")
        return True
    except urllib.error.HTTPError as e:
        print(f"HTTP error {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"Download failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Download drop_core module")
    parser.add_argument("--os", help="Target OS (windows, linux, darwin)")
    parser.add_argument(
        "--arch", help="Target architecture (x64, arm64, aarch64, x86_64)"
    )
    args = parser.parse_args()

    # 获取 token（从环境变量）
    token = os.environ.get("PRIVATE_REPO_TOKEN")
    if not token:
        print(
            "Warning: PRIVATE_REPO_TOKEN not set, may not be able to access private repo"
        )

    # 获取平台信息
    if args.os and args.arch:
        # Use provided OS and arch from command line
        os_type = args.os.lower()
        arch_input = args.arch.lower()
        # Normalize architecture
        arch_mapping = {
            "amd64": "x64",
            "x86_64": "x64",
            "arm64": "arm64",
            "aarch64": "arm64",
        }
        arch = arch_mapping.get(arch_input, arch_input)
        # Build platform tag
        if os_type == "windows":
            platform_tag = f"win-{arch}"
        elif os_type == "darwin":
            platform_tag = f"macos-{'x86_64' if arch == 'x64' else 'aarch64'}"
        elif os_type == "linux":
            platform_tag = f"linux-{arch}"
        else:
            platform_tag = f"{os_type}-{arch}"
    else:
        # Fallback to auto-detection
        os_type, arch, platform_tag = get_platform_info()

    py_version = get_python_version()

    print(f"Platform: {os_type}, Arch: {arch}, Python: {py_version}")

    # 构造下载列表
    # macOS 不带 Python 版本
    # Linux 需要下载所有 Python 版本（用户可能用不同版本）
    # Windows 只下载当前版本
    if os_type == "darwin":
        artifacts = [f"drop_core-{platform_tag}-{RELEASE_TAG}"]
    elif os_type == "linux":
        # Linux 下载所有支持的 Python 版本
        linux_py_versions = ["3.11", "3.12", "3.13"]
        artifacts = [
            f"drop_core-{platform_tag}-py{v}-{RELEASE_TAG}" for v in linux_py_versions
        ]
    else:
        artifacts = [f"drop_core-{platform_tag}-py{py_version}-{RELEASE_TAG}"]

    # 下载所有需要的文件
    success_count = 0
    for artifact_name in artifacts:
        asset_name = f"{artifact_name}.zip"
        download_url = get_asset_download_url(
            PRIVATE_REPO, RELEASE_TAG, asset_name, token
        )

        if not download_url:
            print(f"Cannot get download URL for: {artifact_name}")
            continue

        zip_path = os.path.join(DEST_DIR, asset_name)

        if download_file(download_url, zip_path, token):
            # Extract
            print(f"Extracting: {artifact_name}")
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(DEST_DIR)
                os.remove(zip_path)
                success_count += 1
            except Exception as e:
                print(f"Extract failed: {e}")
        else:
            print(f"Download failed: {artifact_name}")

    if success_count == 0:
        print("No files downloaded successfully, skipping drop_core module")
        return False

    # List installed files
    print("Installed files:")
    for f in os.listdir(DEST_DIR):
        if f.endswith((".pyd", ".so")):
            print(f"  {f}")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
