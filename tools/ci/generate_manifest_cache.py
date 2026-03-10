# -*- coding: utf-8 -*-

"""
生成初始 manifest 缓存

在打包时调用，将远程 manifest 的时间戳信息保存到本地，
使用户首次启动时可以跳过不必要的检查。

注意：使用 urllib 而不是 requests，因为 CI 环境中的 embed Python 可能没有 requests。
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

API_BASE_URL = "https://api.1999.fan/api"
MANIFEST_URL = f"{API_BASE_URL}/manifest.json"
REQUEST_TIMEOUT = 10

# 忽略的目录（不需要热更新）
IGNORED_DIRS = {"images"}


def _fetch_json(opener, url: str) -> dict:
    """获取 JSON 数据"""
    with opener.open(url, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _collect_all_manifests(opener, manifest_path: str, collected: dict):
    """
    递归收集所有 manifest 的 updated 时间戳

    Args:
        opener: urllib opener
        manifest_path: manifest 路径（如 "resource/manifest.json"）
        collected: 收集结果的字典 {manifest_path: updated}
    """
    url = f"{API_BASE_URL}/{manifest_path}"
    print(f"  Fetching: {manifest_path}")

    try:
        manifest = _fetch_json(opener, url)
        collected[manifest_path] = manifest.get("updated", 0)

        # 如果有子目录，递归获取
        for dir_info in manifest.get("directories", []):
            sub_manifest = dir_info.get("manifest", "")
            if sub_manifest:
                _collect_all_manifests(opener, sub_manifest, collected)
    except Exception as e:
        print(f"  Warning: Failed to fetch {manifest_path}: {e}")


def generate_manifest_cache(output_dir: Path) -> bool:
    """
    从远程递归获取所有 manifest 并生成缓存文件

    Args:
        output_dir: 输出目录（如 install/config）

    Returns:
        bool: 是否成功
    """
    try:
        print(f"Fetching root manifest from {MANIFEST_URL}...")
        # 创建不使用代理的 opener（国内服务器直连更快）
        no_proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(no_proxy_handler)

        root_manifest = _fetch_json(opener, MANIFEST_URL)

        # 构建缓存数据（扁平结构，保存所有 manifest 的时间戳）
        cache = {
            "root_updated": root_manifest.get("updated", 0),
            "manifests": {"manifest.json": root_manifest.get("updated", 0)},
        }

        # 递归收集所有子 manifest 的时间戳
        print("Collecting all sub-manifests...")
        for dir_info in root_manifest.get("directories", []):
            dir_name = dir_info["name"]

            # 跳过忽略的目录
            if dir_name in IGNORED_DIRS:
                print(f"  Skipping ignored directory: {dir_name}")
                continue

            sub_manifest = dir_info.get("manifest", "")
            if sub_manifest:
                _collect_all_manifests(opener, sub_manifest, cache["manifests"])

        # 确保目录存在
        output_dir.mkdir(parents=True, exist_ok=True)

        # 写入缓存文件
        cache_file = output_dir / "manifest_cache.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

        print(f"\nGenerated manifest cache: {cache_file}")
        print(f"  root_updated: {cache['root_updated']}")
        print(f"  Total manifests cached: {len(cache['manifests'])}")
        for path, updated in cache["manifests"].items():
            print(f"    {path}: {updated}")

        return True

    except urllib.error.URLError as e:
        print(f"Warning: Failed to fetch manifest (URL error): {e}")
        print("Skipping manifest cache generation.")
        return False
    except Exception as e:
        print(f"Warning: Failed to generate manifest cache: {e}")
        return False


if __name__ == "__main__":
    import sys

    # 支持命令行指定输出目录
    if len(sys.argv) > 1:
        output_dir = Path(sys.argv[1])
    else:
        # 默认输出到 install/config
        script_dir = Path(__file__).parent
        output_dir = script_dir.parent.parent / "install" / "config"

    success = generate_manifest_cache(output_dir)
    sys.exit(0 if success else 1)
