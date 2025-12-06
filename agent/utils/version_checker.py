# -*- coding: utf-8 -*-

import json
import sys
import platform
import requests
from pathlib import Path
from . import logger
from .exceptions import (
    ResourceNotFoundError,
    InvalidOSError,
    InvalidArchError,
    InvalidChannelError,
    APIBusinessError,
    APICriticalError,
    VersionCheckError,
)


def _infer_channel_from_version(version: str) -> str:
    """
    从版本号推断更新通道

    Args:
        version: 版本号，如 "v3.17.0-beta.7", "v3.16.5-alpha.1", "v3.16.5"

    Returns:
        str: 推断的通道 "alpha", "beta" 或 "stable"
    """
    version_lower = version.lower()
    if "-alpha" in version_lower:
        return "alpha"
    elif "-beta" in version_lower:
        return "beta"
    else:
        return "stable"


def check_resource_version(interface_file_path: str = "./interface.json") -> dict:
    """
    检查资源版本是否为最新

    Args:
        interface_file_path: interface.json文件路径

    Returns:
        dict: {
            "is_latest": bool,  # 是否为最新版本
            "current_version": str,  # 当前版本
            "latest_version": str,  # 最新版本
            "error": str  # 错误信息（如果检查失败）
        }
    """
    result = {
        "is_latest": True,
        "current_version": "unknown",
        "latest_version": "unknown",
        "error": "",
    }

    try:
        # 读取本地interface.json
        interface_path = Path(interface_file_path)
        if not interface_path.exists():
            # 尝试从assets目录读取
            assets_path = Path("./assets") / "interface.json"
            if assets_path.exists():
                interface_path = assets_path
            else:
                result["error"] = "未找到interface.json文件"
                logger.warning(result["error"])
                return result

        with open(interface_path, "r", encoding="utf-8") as f:
            interface_data = json.load(f)

        current_version = interface_data.get("version", "unknown")
        result["current_version"] = current_version

        # 获取项目RID
        rid = interface_data.get("mirrorchyan_rid")
        if not rid:
            result["error"] = "interface.json中未找到rid字段"
            logger.warning(result["error"])
            return result

        # 读取更新通道配置
        channel_map = {0: "alpha", 1: "beta", 2: "stable"}
        config_channel = "stable"  # 默认值

        config_path = Path("./config/config.json")
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                    channel_index = config_data.get("ResourceUpdateChannelIndex", 2)
                    config_channel = channel_map.get(channel_index, "stable")
            except Exception as e:
                logger.debug(f"读取config.json失败，使用默认通道stable: {e}")

        # 从当前版本号推断实际使用的通道
        inferred_channel = _infer_channel_from_version(current_version)

        # 通道优先级：alpha > beta > stable（数字越小越激进）
        # 选择两者中更激进的通道，这样：
        # 1. 当前是beta，配置是stable → 用beta（避免降级误报）
        # 2. 当前是stable，配置是beta → 用beta（允许用户升级到beta）
        channel_priority = {"alpha": 0, "beta": 1, "stable": 2}

        if channel_priority[inferred_channel] <= channel_priority[config_channel]:
            channel = inferred_channel
        else:
            channel = config_channel

        if inferred_channel != config_channel:
            logger.debug(
                f"检测到通道不一致: 配置通道={config_channel}, "
                f"当前版本推断通道={inferred_channel}, 将使用 {channel} 通道进行版本检查"
            )

        # 检测运行环境和架构，转换为小写
        os_type = platform.system().lower()
        machine = platform.machine().lower()

        # 调用API检查最新版本
        api_url = f"https://mirrorchyan.com/api/resources/{rid}/latest/?os={os_type}&arch={machine}&channel={channel}&user_agent=M9A-Agent"
        logger.debug(f"正在检查资源版本: {api_url}")

        response = requests.get(api_url, timeout=10)
        response.raise_for_status()

        latest_data = response.json()

        # 检查API返回的错误码
        code = latest_data.get("code", 0)
        if code != 0:
            msg = latest_data.get("msg", "未知错误")

            # 根据错误码抛出对应的异常
            if code == 8001:
                raise ResourceNotFoundError(os_type, machine)
            elif code == 8002:
                raise InvalidOSError(os_type)
            elif code == 8003:
                raise InvalidArchError(machine)
            elif code == 8004:
                channel = latest_data.get("channel", "unknown")
                raise InvalidChannelError(channel)
            elif code > 0:
                raise APIBusinessError(code, msg)
            else:
                raise APICriticalError(code, msg)

        # 从 data 字段中获取版本信息
        data = latest_data.get("data", {})
        latest_version = data.get("version_name", "unknown")
        result["latest_version"] = latest_version

        # 比较版本
        if current_version != latest_version and latest_version != "unknown":
            result["is_latest"] = False
        elif current_version == latest_version:
            logger.debug(f"资源已是最新版本: {current_version}")

        return result

    except VersionCheckError as e:
        result["error"] = e.message
        logger.debug(f"版本检查: {result['error']}")
        return result
    except requests.exceptions.RequestException as e:
        result["error"] = f"网络请求失败: {str(e)}"
        logger.debug(f"版本检查: {result['error']}")
        return result
    except json.JSONDecodeError as e:
        result["error"] = f"JSON解析失败: {str(e)}"
        logger.debug(f"版本检查: {result['error']}")
        return result
    except Exception as e:
        result["error"] = f"未知错误: {str(e)}"
        logger.debug(f"版本检查异常: {result['error']}")
        return result
