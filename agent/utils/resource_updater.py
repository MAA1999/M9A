# -*- coding: utf-8 -*-

"""
资源热更新模块

支持基于 manifest 的增量更新，可按目录选择性更新资源。
"""

import json
import hashlib
import requests
from pathlib import Path
from typing import Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import logger

# 默认配置
DEFAULT_API_BASE_URL = "https://api.1999.fan/api"
DEFAULT_TIMEOUT = 5  # 缩短超时时间

# 不使用系统代理（国内服务器直连更快）
NO_PROXY = {"http": "", "https": ""}


def calculate_file_hash(file_path: Path) -> str:
    """
    Calculate SHA256 hash of a file.

    Args:
        file_path: Path to the file

    Returns:
        Hex string of SHA256 hash
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read in chunks to handle large files
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_all_manifests(api_base_url: str, manifest_path: str, timeout: int) -> List[str]:
    """
    递归获取所有包含文件的 manifest 路径（并行）

    Args:
        api_base_url: API 基础 URL
        manifest_path: 当前 manifest 路径（如 "resource/manifest.json"）
        timeout: 请求超时时间

    Returns:
        包含文件的 manifest 路径列表
    """
    manifest_url = f"{api_base_url}/{manifest_path}"

    try:
        response = requests.get(manifest_url, timeout=timeout, proxies=NO_PROXY)
        response.raise_for_status()
        manifest = response.json()

        # 如果有 directories，并行递归获取子目录的 manifest
        if "directories" in manifest and manifest["directories"]:
            result = []
            sub_manifest_paths = [d["manifest"] for d in manifest["directories"]]

            # 使用线程池并行请求
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(
                        get_all_manifests, api_base_url, path, timeout
                    ): path
                    for path in sub_manifest_paths
                }

                for future in as_completed(futures):
                    try:
                        result.extend(future.result())
                    except Exception as e:
                        path = futures[future]
                        logger.warning(f"获取 {path} 失败: {str(e)}")

            return result

        # 如果有 files，说明这是最终的文件清单，返回该路径
        if "files" in manifest and manifest["files"]:
            return [manifest_path]

        return []

    except Exception as e:
        logger.warning(f"获取 {manifest_path} 失败: {str(e)}")
        return []


def check_and_update_resources(
    api_base_url: str = DEFAULT_API_BASE_URL,
    resource_manifests: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    检查并更新资源文件

    Args:
        api_base_url: API 基础 URL
        resource_manifests: 需要更新的 manifest 路径列表，如果为 None 则从 API 递归获取
        timeout: 请求超时时间（秒）

    Returns:
        dict: {
            "success": bool,  # 是否成功
            "updated_files": List[str],  # 已更新的文件列表
            "failed_files": List[str],  # 更新失败的文件列表
            "error": str  # 错误信息
        }
    """
    result = {
        "success": True,
        "updated_files": [],
        "failed_files": [],
        "error": "",
    }

    try:
        project_root = Path.cwd()

        # 如果未指定 manifest 列表，则从 API 递归获取所有
        if resource_manifests is None:
            try:
                logger.debug("开始递归获取资源清单列表")
                resource_manifests = get_all_manifests(
                    api_base_url, "resource/manifest.json", timeout
                )
                logger.debug(f"自动获取到 {len(resource_manifests)} 个资源清单")

                if not resource_manifests:
                    logger.warning("未获取到任何可用的资源清单")
                    result["error"] = "未获取到可用的资源清单"
                    result["success"] = False
                    return result

            except Exception as e:
                error_msg = f"获取资源清单列表失败: {str(e)}"
                logger.warning(error_msg)
                result["error"] = error_msg
                result["success"] = False
                return result
        else:
            logger.debug(f"使用指定的 {len(resource_manifests)} 个资源清单")

        for manifest_path in resource_manifests:
            try:
                # 获取远程 manifest
                manifest_url = f"{api_base_url}/{manifest_path}"
                logger.debug(f"获取资源清单: {manifest_url}")

                response = requests.get(manifest_url, timeout=timeout, proxies=NO_PROXY)
                response.raise_for_status()
                manifest = response.json()

                # 检查并更新每个文件
                for file_info in manifest.get("files", []):
                    file_name = file_info["name"]
                    file_path_str = file_info["path"]
                    remote_hash = file_info["hash"]
                    # 使用 manifest 中的完整路径
                    file_path = project_root / file_path_str

                    # 检查本地文件是否需要更新
                    need_update = False
                    if not file_path.exists():
                        logger.debug(f"本地文件不存在: {file_path_str}")
                        need_update = True
                    else:
                        local_hash = calculate_file_hash(file_path)
                        if local_hash != remote_hash:
                            logger.debug(f"文件哈希不匹配: {file_path_str}")
                            logger.debug(f"  本地 hash: {local_hash}")
                            logger.debug(f"  远程 hash: {remote_hash}")
                            logger.debug(
                                f"  文件大小: {file_path.stat().st_size} bytes"
                            )
                            need_update = True

                    if need_update:
                        # 下载文件
                        file_url = f"{api_base_url}/{file_path_str}"
                        logger.debug(f"下载文件: {file_url}")

                        file_response = requests.get(
                            file_url, timeout=timeout, proxies=NO_PROXY
                        )
                        file_response.raise_for_status()

                        # 验证下载的文件哈希
                        downloaded_hash = hashlib.sha256(
                            file_response.content
                        ).hexdigest()
                        if downloaded_hash != remote_hash:
                            logger.warning(f"文件哈希验证失败: {file_path_str}")
                            result["failed_files"].append(file_path_str)
                            continue

                        # 确保目录存在
                        file_path.parent.mkdir(parents=True, exist_ok=True)

                        # 保存文件
                        with open(file_path, "wb") as f:
                            f.write(file_response.content)

                        # logger.info(
                        #     f"已更新: {file_path_str} ({file_info['size']} bytes)"
                        # )
                        result["updated_files"].append(file_path_str)
                    else:
                        logger.debug(f"文件已是最新: {file_path_str}")

            except requests.exceptions.RequestException as e:
                error_msg = f"更新 {manifest_path} 资源失败: 网络错误 - {str(e)}"
                logger.warning(error_msg)
                result["error"] = error_msg
                result["success"] = False
            except Exception as e:
                error_msg = f"更新 {manifest_path} 资源失败: {str(e)}"
                logger.warning(error_msg)
                result["error"] = error_msg
                result["success"] = False

        if result["updated_files"]:
            logger.info(
                f"部分资源热更新完成，共更新 {len(result['updated_files'])} 个文件\n如前面有提示新资源版本还请更新"
            )
        else:
            logger.debug("所有资源文件已是最新")

        return result

    except Exception as e:
        result["success"] = False
        result["error"] = f"资源更新异常: {str(e)}"
        logger.exception("资源更新时发生异常")
        return result
