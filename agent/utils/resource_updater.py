"""
资源热更新模块

支持基于 manifest 的增量更新，可按目录选择性更新资源。
提交粒度为单个 manifest：某个清单失败不会影响其它清单中已校验通过的文件。
"""

import hashlib
import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import requests  # pyright: ignore[reportMissingModuleSource]

from . import logger
from .http_session import create_no_proxy_session
from .runtime_paths import get_runtime_paths

# 默认配置
DEFAULT_API_BASE_URL = "https://api.1999.fan/api"
DEFAULT_TIMEOUT = 5  # 缩短超时时间

# 下载重试次数与退避基数；服务端是 CDN（实测 Via: varnish / Cache-Control: max-age=600），
# 边缘节点可能仍返回旧副本，重试时用时间戳参数 + no-cache 绕开缓存。
DOWNLOAD_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5
NO_CACHE_HEADERS = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
# 属于"临时性拒绝"、值得重试的 4xx；其余 4xx 重试无意义，直接失败
RETRYABLE_CLIENT_STATUS = (408, 429)

# 与 manifest_checker 保持一致；图片和迁移前的旧 data 路径不参与热更新。
IGNORED_MANIFEST_PREFIXES = ("images/", "resource/data/")

# 不使用系统代理（国内服务器直连更快）
session = create_no_proxy_session()


class FileHashMismatchError(ValueError):
    """下载内容与 manifest 声明的哈希不一致（记录双方哈希，便于定位是服务端还是链路问题）。"""

    def __init__(
        self,
        file_path: str,
        *,
        expected_hash: str,
        actual_hash: str,
        url: str,
        bytes_downloaded: int,
        attempts: int,
        response_note: str = "",
    ) -> None:
        self.file_path = file_path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        self.url = url
        self.bytes_downloaded = bytes_downloaded
        self.attempts = attempts
        self.response_note = response_note

        parts = [
            f"期望 {expected_hash[:16]}…",
            f"实际 {actual_hash[:16]}…",
            f"大小 {bytes_downloaded} 字节",
            f"尝试 {attempts} 次",
        ]
        if response_note:
            parts.append(response_note)
        super().__init__(f"文件哈希验证失败: {file_path}（{'，'.join(parts)}；最后请求 {url}）")


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


def _normalize_relative_path(path_value: Any, *, label: str) -> str:
    """校验并规范化 manifest 中的 POSIX 相对路径。"""
    if not isinstance(path_value, str) or not path_value:
        raise ValueError(f"{label} 不是有效的非空字符串")
    if "\\" in path_value:
        raise ValueError(f"{label} 不能包含反斜杠: {path_value}")

    path = PurePosixPath(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} 必须位于项目目录内: {path_value}")
    if not path.parts or ":" in path.parts[0]:
        raise ValueError(f"{label} 不是有效的相对路径: {path_value}")
    return path.as_posix()


def _resolve_project_file(project_root: Path, file_path_value: Any) -> tuple[str, Path]:
    """将 manifest 文件路径解析到项目根目录内，并拒绝路径逃逸。"""
    file_path_str = _normalize_relative_path(file_path_value, label="文件路径")
    root = project_root.resolve()
    relative_path = Path(*PurePosixPath(file_path_str).parts)
    file_path = (root / relative_path).resolve(strict=False)
    if not file_path.is_relative_to(root):
        raise ValueError(f"文件路径超出项目目录: {file_path_str}")
    return file_path_str, file_path


def _validate_sha256(hash_value: Any, file_path: str) -> str:
    if not isinstance(hash_value, str) or len(hash_value) != 64:
        raise ValueError(f"文件 SHA256 无效: {file_path}")
    try:
        int(hash_value, 16)
    except ValueError as error:
        raise ValueError(f"文件 SHA256 无效: {file_path}") from error
    return hash_value.lower()


def get_all_manifests(api_base_url: str, manifest_path: str, timeout: int) -> list[str]:
    """
    从根 manifest 递归获取所有包含文件的 manifest 路径。

    任一子 manifest 获取失败都会抛出异常，避免把不完整清单当作成功。
    """
    collected: list[str] = []
    visited: set[str] = set()

    def collect(current_path_value: Any) -> None:
        current_path = _normalize_relative_path(current_path_value, label="manifest 路径")
        if current_path in visited:
            return
        visited.add(current_path)

        if current_path.startswith(IGNORED_MANIFEST_PREFIXES):
            logger.debug(f"跳过忽略的 manifest: {current_path}")
            return

        manifest_url = f"{api_base_url.rstrip('/')}/{current_path}"
        response = session.get(manifest_url, timeout=timeout, headers=NO_CACHE_HEADERS)
        response.raise_for_status()
        manifest = response.json()
        if not isinstance(manifest, dict):
            raise ValueError(f"manifest 内容不是对象: {current_path}")

        if manifest.get("files"):
            collected.append(current_path)

        for dir_info in manifest.get("directories", []):
            if not isinstance(dir_info, dict):
                raise ValueError(f"manifest 子目录无效: {current_path}")
            collect(dir_info.get("manifest"))

    collect(manifest_path)
    return collected


def _describe_response(response: Any) -> str:
    """记录响应特征，便于判断是服务端发错还是链路/网关改写了响应体。"""
    status = getattr(response, "status_code", None)
    headers = getattr(response, "headers", None)
    content_type = headers.get("Content-Type", "?") if isinstance(headers, Mapping) else "?"
    return f"HTTP {status} content-type={content_type}"


def _write_staged_file(file_path: Path, content: bytes) -> Path:
    """把已校验的内容写入目标目录旁的临时文件。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        assert temp_path is not None
        return temp_path
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as error:
                logger.debug(f"清理热更新临时文件失败: {temp_path}: {error}")
        raise


def _stage_download(
    api_base_url: str,
    file_path_str: str,
    file_path: Path,
    remote_hash: str,
    timeout: int,
) -> Path:
    """
    下载到目标目录旁的临时文件，并在返回前完成哈希校验。

    网络错误或哈希不一致时会重试，并绕开 CDN 缓存；全部尝试失败后抛出最后一次的错误，
    其中 FileHashMismatchError 会带上双方哈希与响应信息，供用户反馈时定位。
    """
    file_url = f"{api_base_url.rstrip('/')}/{file_path_str}"
    last_error: Exception | None = None

    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        cache_busting = attempt > 1
        request_url = f"{file_url}?m9a_retry={int(time.time() * 1000)}" if cache_busting else file_url
        logger.debug(f"下载文件: {request_url}（第 {attempt}/{DOWNLOAD_ATTEMPTS} 次）")

        try:
            file_response = session.get(
                request_url,
                timeout=timeout,
                headers=NO_CACHE_HEADERS if cache_busting else None,
            )
            file_response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            status = getattr(error.response, "status_code", None)
            if isinstance(status, int) and 400 <= status < 500 and status not in RETRYABLE_CLIENT_STATUS:
                # 4xx（408/429 除外）重试不可能成功，直接失败，别浪费退避时间
                raise
            last_error = error
            logger.warning(f"文件下载失败（第 {attempt}/{DOWNLOAD_ATTEMPTS} 次）: {request_url} - {error}")
        except requests.exceptions.RequestException as error:
            last_error = error
            logger.warning(f"文件下载失败（第 {attempt}/{DOWNLOAD_ATTEMPTS} 次）: {request_url} - {error}")
        else:
            content = file_response.content
            downloaded_hash = hashlib.sha256(content).hexdigest()
            if downloaded_hash == remote_hash:
                return _write_staged_file(file_path, content)

            response_note = _describe_response(file_response)
            last_error = FileHashMismatchError(
                file_path_str,
                expected_hash=remote_hash,
                actual_hash=downloaded_hash,
                url=request_url,
                bytes_downloaded=len(content),
                attempts=attempt,
                response_note=response_note,
            )
            logger.warning(
                f"文件哈希校验失败（第 {attempt}/{DOWNLOAD_ATTEMPTS} 次）: {file_path_str} "
                f"期望 {remote_hash[:16]}… 实际 {downloaded_hash[:16]}… 大小 {len(content)} 字节 {response_note}"
            )

        if attempt < DOWNLOAD_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    if last_error is None:  # DOWNLOAD_ATTEMPTS >= 1 时不可达，仅作类型收窄
        raise RuntimeError(f"下载失败且无错误信息: {file_path_str}")
    raise last_error


def _fetch_manifest(api_base_url: str, manifest_path: str, timeout: int) -> dict[str, Any]:
    """获取并校验单个 manifest。"""
    manifest_url = f"{api_base_url.rstrip('/')}/{manifest_path}"
    logger.debug(f"获取资源清单: {manifest_url}")

    # manifest 也走 no-cache：若命中 CDN 的旧清单（旧哈希），文件侧再怎么重试都会校验失败
    response = session.get(manifest_url, timeout=timeout, headers=NO_CACHE_HEADERS)
    response.raise_for_status()
    manifest = response.json()
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest 内容不是对象: {manifest_path}")
    return manifest


def check_and_update_resources(
    api_base_url: str = DEFAULT_API_BASE_URL,
    resource_manifests: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    检查并更新资源文件。

    每个 manifest 是一个独立事务：该清单内所有文件下载并校验通过后才统一替换正式文件；
    某个清单失败只影响它自己，其它清单已校验通过的文件仍会提交。
    """
    result: dict[str, Any] = {
        "success": True,
        "updated_files": [],
        "failed_files": [],
        "failed_manifests": [],
        "error": "",
    }

    try:
        project_root = get_runtime_paths().work_root.resolve()
    except Exception as error:
        result["success"] = False
        result["error"] = f"资源更新失败: {error}"
        logger.warning(result["error"])
        return result

    if resource_manifests is None:
        try:
            logger.debug("开始从根 manifest 递归获取资源清单列表")
            resource_manifests = get_all_manifests(api_base_url, "manifest.json", timeout)
            logger.debug(f"自动获取到 {len(resource_manifests)} 个资源清单")
            if not resource_manifests:
                raise ValueError("未获取到可用的资源清单")
        except Exception as error:
            result["success"] = False
            result["error"] = f"资源更新失败: {error}"
            logger.warning(result["error"])
            return result
    else:
        logger.debug(f"使用指定的 {len(resource_manifests)} 个资源清单")

    # 跨 manifest 的重复文件检测
    seen_targets: set[Path] = set()
    errors: list[str] = []

    for manifest_path_value in resource_manifests:
        staged_files: list[tuple[str, Path, Path]] = []
        manifest_path = str(manifest_path_value)

        try:
            manifest_path = _normalize_relative_path(manifest_path_value, label="manifest 路径")
            manifest = _fetch_manifest(api_base_url, manifest_path, timeout)

            for file_info in manifest.get("files", []):
                if not isinstance(file_info, dict):
                    raise ValueError(f"manifest 文件条目无效: {manifest_path}")

                file_path_str, file_path = _resolve_project_file(project_root, file_info.get("path"))
                remote_hash = _validate_sha256(file_info.get("hash"), file_path_str)
                if file_path in seen_targets:
                    raise ValueError(f"manifest 包含重复文件路径: {file_path_str}")
                seen_targets.add(file_path)

                if file_path.exists() and calculate_file_hash(file_path) == remote_hash:
                    logger.debug(f"文件已是最新: {file_path_str}")
                    continue

                temp_path = _stage_download(
                    api_base_url,
                    file_path_str,
                    file_path,
                    remote_hash,
                    timeout,
                )
                staged_files.append((file_path_str, file_path, temp_path))

            # 该 manifest 内所有下载和哈希校验完成后才替换正式文件
            for file_path_str, file_path, temp_path in staged_files:
                os.replace(temp_path, file_path)
                result["updated_files"].append(file_path_str)

        except FileHashMismatchError as error:
            result["success"] = False
            result["failed_files"].append(error.file_path)
            result["failed_manifests"].append(manifest_path)
            message = f"资源更新失败: {error}"
            errors.append(message)
            logger.warning(message)
        except requests.exceptions.RequestException as error:
            result["success"] = False
            result["failed_manifests"].append(manifest_path)
            message = f"资源更新网络错误: {manifest_path}: {error}"
            errors.append(message)
            logger.warning(message)
        except Exception as error:
            result["success"] = False
            result["failed_manifests"].append(manifest_path)
            message = f"资源更新失败: {error}"
            errors.append(message)
            logger.warning(message)
        finally:
            for _, _, temp_path in staged_files:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError as error:
                    logger.debug(f"清理热更新临时文件失败: {temp_path}: {error}")

    result["error"] = "\n".join(errors)

    if result["updated_files"]:
        logger.info(f"部分资源热更新完成，共更新 {len(result['updated_files'])} 个文件\n如前面有提示新资源版本还请更新")
    elif result["success"]:
        logger.debug("所有资源文件已是最新")

    return result
