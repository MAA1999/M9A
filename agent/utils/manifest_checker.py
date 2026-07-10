"""
Manifest 缓存检查模块

通过比对远程 manifest 的 updated 时间戳与本地缓存，
快速判断哪些 manifest（及其文件）需要更新，支持细粒度的子目录检查。
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import requests  # pyright: ignore[reportMissingModuleSource]

from . import logger
from .http_session import create_no_proxy_session
from .runtime_paths import get_runtime_paths

# 配置
MANIFEST_URL = "https://api.1999.fan/api/manifest.json"
API_BASE_URL = "https://api.1999.fan/api"
REQUEST_TIMEOUT = 5

# 不使用系统代理（国内服务器直连更快）
session = create_no_proxy_session()

# 忽略的目录（不需要热更新）
IGNORED_DIRS = {"images"}
IGNORED_MANIFEST_PREFIXES = ("images/", "resource/data/")


def _load_cache() -> dict[str, Any]:
    """
    加载本地缓存

    Returns:
        dict: {
            "root_updated": int,
            "manifests": {
                "manifest.json": int,
                "resource/manifest.json": int,
                ...
            }
        }
    """
    default = {"root_updated": 0, "manifests": {}}
    cache_file = get_runtime_paths().manifest_cache_file
    if not cache_file.exists():
        return default
    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
            # 兼容旧格式
            if "manifests" not in data:
                return default
            return data
    except Exception:
        return default


def _save_cache(cache: dict[str, Any]) -> None:
    """将缓存原子写入本地，避免中断时留下半截 JSON。"""
    cache_file = get_runtime_paths().manifest_cache_file
    temp_path: Path | None = None
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_file.parent,
            prefix=f".{cache_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(cache, temp_file, indent=2, ensure_ascii=False)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, cache_file)
    except Exception as e:
        logger.debug(f"保存 manifest 缓存失败: {e}")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as e:
                logger.debug(f"清理 manifest 缓存临时文件失败: {temp_path}: {e}")


def _is_ignored_path(manifest_path: str) -> bool:
    """检查 manifest 路径是否在忽略目录下"""
    return manifest_path.startswith(IGNORED_MANIFEST_PREFIXES)


def _collect_updated_manifests(
    manifest_path: str,
    local_manifests: dict[str, int],
    collected_manifests: dict[str, int],
    updated_manifests: list[str],
) -> bool:
    """
    递归检查 manifest 是否需要更新

    Args:
        manifest_path: manifest 路径
        local_manifests: 本地缓存的 manifest 时间戳
        collected_manifests: 收集到的远程 manifest 时间戳
        updated_manifests: 需要更新的 manifest 路径列表

    Returns:
        bool: 是否成功
    """
    # 跳过忽略的目录
    if _is_ignored_path(manifest_path):
        logger.debug(f"跳过忽略的 manifest: {manifest_path}")
        return True

    try:
        url = f"{API_BASE_URL}/{manifest_path}"
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        manifest = response.json()

        remote_updated = manifest.get("updated", 0)
        local_updated = local_manifests.get(manifest_path, 0)
        collected_manifests[manifest_path] = remote_updated

        # 检查是否需要更新
        if remote_updated > local_updated:
            # 如果这个 manifest 包含文件，则需要更新
            if manifest.get("files"):
                updated_manifests.append(manifest_path)
                logger.debug(f"manifest 需要更新: {manifest_path} ({local_updated} → {remote_updated})")

            # 递归检查子目录
            children_succeeded = True
            for dir_info in manifest.get("directories", []):
                sub_manifest = dir_info.get("manifest", "")
                if sub_manifest:
                    child_succeeded = _collect_updated_manifests(
                        sub_manifest,
                        local_manifests,
                        collected_manifests,
                        updated_manifests,
                    )
                    children_succeeded = child_succeeded and children_succeeded
            return children_succeeded
        else:
            logger.debug(f"manifest 无更新: {manifest_path} (updated={remote_updated})")
            # 即使没更新，也要收集子 manifest 的时间戳（用于保存缓存）
            for dir_info in manifest.get("directories", []):
                sub_manifest = dir_info.get("manifest", "")
                if sub_manifest and not _is_ignored_path(sub_manifest):
                    # 使用本地缓存的时间戳
                    if sub_manifest in local_manifests:
                        collected_manifests[sub_manifest] = local_manifests[sub_manifest]

        return True

    except requests.exceptions.RequestException as e:
        logger.debug(f"获取 manifest 失败: {manifest_path}: {e}")
        return False
    except Exception as e:
        logger.debug(f"处理 manifest 异常: {manifest_path}: {e}")
        return False


def check_manifest_updates() -> dict[str, Any]:
    """
    检查远程 manifest 更新状态（细粒度，支持子目录）

    Returns:
        dict: {
            "success": bool,
            "has_any_update": bool,
            "updated_manifests": List[str],  # 需要更新的 manifest 路径列表
            "collected_manifests": Dict[str, int],  # 收集到的所有 manifest 时间戳
            "error": str,
        }
    """
    result: dict[str, Any] = {
        "success": False,
        "has_any_update": False,
        "updated_manifests": [],
        "collected_manifests": {},
        "error": "",
    }

    # 加载本地缓存
    local_cache = _load_cache()
    local_manifests = local_cache.get("manifests", {})

    try:
        # 请求远程根 manifest
        response = session.get(MANIFEST_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        root_manifest = response.json()

        remote_root_updated = root_manifest.get("updated", 0)
        local_root_updated = local_cache.get("root_updated", 0)

        result["collected_manifests"]["manifest.json"] = remote_root_updated

        # 快速路径：根时间戳相同，所有目录都不需要更新
        if remote_root_updated == local_root_updated and local_root_updated > 0:
            logger.debug(f"根 manifest 无变化 (updated={remote_root_updated})，跳过所有检查")
            result["success"] = True
            result["collected_manifests"] = local_manifests.copy()
            result["collected_manifests"]["manifest.json"] = remote_root_updated
            return result

        # 递归检查各子目录
        manifests_succeeded = True
        for dir_info in root_manifest.get("directories", []):
            dir_name = dir_info["name"]
            sub_manifest = dir_info.get("manifest", "")

            if dir_name in IGNORED_DIRS:
                logger.debug(f"跳过忽略的目录: {dir_name}")
                continue

            if sub_manifest:
                manifest_succeeded = _collect_updated_manifests(
                    sub_manifest,
                    local_manifests,
                    result["collected_manifests"],
                    result["updated_manifests"],
                )
                manifests_succeeded = manifest_succeeded and manifests_succeeded

        if not manifests_succeeded:
            result["error"] = "部分 manifest 获取失败"
            result["has_any_update"] = True
            logger.debug(result["error"])
            return result

        result["success"] = True
        result["has_any_update"] = len(result["updated_manifests"]) > 0

        if result["has_any_update"]:
            logger.info(f"检测到 {len(result['updated_manifests'])} 个 manifest 需要更新")
            for m in result["updated_manifests"]:
                logger.debug(f"  - {m}")
        else:
            logger.debug("所有 manifest 均无更新")

    except requests.exceptions.Timeout:
        result["error"] = "manifest 请求超时"
        result["has_any_update"] = True
        logger.debug(result["error"])
    except requests.exceptions.RequestException as e:
        result["error"] = f"manifest 请求失败: {e}"
        result["has_any_update"] = True
        logger.debug(result["error"])
    except Exception as e:
        result["error"] = f"manifest 检查异常: {e}"
        result["has_any_update"] = True
        logger.debug(result["error"])

    return result


def save_manifest_cache_from_result(check_result: dict[str, Any]):
    """
    根据检查结果保存缓存

    Args:
        check_result: check_manifest_updates() 的返回值
    """
    if not check_result.get("success"):
        return

    collected = check_result.get("collected_manifests", {})
    if not collected:
        return

    cache = {
        "root_updated": collected.get("manifest.json", 0),
        "manifests": collected,
    }

    _save_cache(cache)
    logger.debug(f"manifest 缓存已更新，共 {len(collected)} 个 manifest")
