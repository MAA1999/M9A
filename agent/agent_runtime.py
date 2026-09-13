from __future__ import annotations

import importlib.metadata
import json
import os
import sys
from typing import Any

from utils import logger
from utils.runtime_paths import configure_runtime_paths, get_runtime_paths

PI_ENV_KEYS = (
    "PI_INTERFACE_VERSION",
    "PI_CLIENT_NAME",
    "PI_CLIENT_VERSION",
    "PI_CLIENT_LANGUAGE",
    "PI_CLIENT_MAAFW_VERSION",
    "PI_VERSION",
    "PI_CONTROLLER",
    "PI_RESOURCE",
)


# -------------
# region 启动时的版本检查与资源热更新
# -------------
def _read_hot_update_config() -> dict[str, Any]:
    """读取热更新配置"""
    paths = get_runtime_paths()
    config_path = paths.config_dir / "hot_update.json"
    if not config_path.exists():
        return {"enable_hot_update": True}
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("读取 hot_update.json 失败，使用默认配置")
        return {"enable_hot_update": True}


# manifest → 用户可理解的功能，用于热更新失败时说明影响范围
_MANIFEST_FEATURE_HINTS = {
    "data/activity/manifest.json": "活动代币刷取 / 复刻活动",
    "data/combat/manifest.json": "常规作战",
    "data/redeem_code/manifest.json": "使用兑换码",
    "data/sos/manifest.json": "局外演绎：无声综合征",
}


def _describe_hot_update_failure(update_result: dict[str, Any]) -> str:
    """把热更新失败整理成用户能看懂的一段话（含影响范围与重试方式）。"""
    failed_files = list(update_result.get("failed_files") or [])
    failed_manifests = list(update_result.get("failed_manifests") or [])
    updated_files = list(update_result.get("updated_files") or [])

    lines = ["资源热更新未完成，以下功能可能仍在使用旧数据："]
    if failed_manifests:
        hints = [f"{m}（{_MANIFEST_FEATURE_HINTS.get(m, '未知功能')}）" for m in failed_manifests]
        lines.append(f"- 未更新：{'; '.join(hints)}")
    if failed_files:
        lines.append(f"- 校验失败的文件：{', '.join(failed_files)}")
    lines.append(f"- 本次已更新 {len(updated_files)} 个文件；失败的文件保持旧版本")
    lines.append("- 下次启动会自动重试；若反复失败，请携带 debug/custom 日志反馈")
    if update_result.get("error"):
        lines.append(f"- 失败原因：{update_result['error']}")
    return "\n".join(lines)


def _check_resource_version() -> None:
    """版本检查"""
    from utils.version_checker import check_resource_version

    version_info = check_resource_version()
    if not version_info["is_latest"]:
        logger.warning("检测到资源有新版本!")
        logger.warning(f"当前资源版本: {version_info['current_version']}")
        logger.warning(f"最新资源版本: {version_info['latest_version']}")
    elif version_info["error"]:
        logger.debug(f"资源版本检查遇到问题: {version_info['error']}")


def _hot_update() -> None:
    """热更新：基于 manifest 时间戳优化"""
    hot_update_conf = _read_hot_update_config()
    if not hot_update_conf.get("enable_hot_update", True):
        logger.info("已配置为跳过部分资源热更")
        return

    from utils.manifest_checker import (
        check_manifest_updates,
        save_manifest_cache_from_result,
    )

    manifest_result = check_manifest_updates()
    should_save_manifest_cache = manifest_result["success"] and not manifest_result["has_any_update"]

    if manifest_result["success"] and not manifest_result["has_any_update"]:
        logger.debug("资源无更新，跳过热更新")
    else:
        updated_manifests = manifest_result.get("updated_manifests", [])

        if updated_manifests or not manifest_result["success"]:
            from utils.resource_updater import check_and_update_resources

            manifests = updated_manifests if manifest_result["success"] else None
            if manifests:
                logger.debug(f"开始更新 {len(manifests)} 个资源清单...")
            else:
                logger.debug("开始检查所有资源...")

            update_result = check_and_update_resources(resource_manifests=manifests)
            if update_result and update_result.get("success"):
                should_save_manifest_cache = manifest_result["success"]
            elif update_result:
                # 失败要留下用户能看懂的结论：哪些功能没更新、怎么重试
                logger.warning(_describe_hot_update_failure(update_result))
            else:
                logger.warning("资源热更新未成功（未返回结果），下次启动会自动重试")
        else:
            logger.debug("所有 manifest 无更新，跳过热更新")

    if should_save_manifest_cache:
        save_manifest_cache_from_result(manifest_result)
    else:
        logger.debug("热更新未完整成功，保留原 manifest 缓存")


# -------------
# endregion
# -------------


# -------------
# region 启动入口
# -------------
def run_agent(project_root_dir: str) -> int:
    configure_runtime_paths(project_root=project_root_dir, work_root=os.getcwd())

    try:
        logger.info(f"maafw {importlib.metadata.version('maafw')}")
    except importlib.metadata.PackageNotFoundError:
        pass

    if len(sys.argv) < 2:
        logger.error("Missing MaaFW Agent socket id argument.")
        return 2

    try:
        from maa.agent.agent_server import AgentServer
        from maa.tasker import Tasker
    except ImportError as error:
        logger.error("Failed to import MaaFW Agent runtime: {}", error)
        logger.error("Run `uv sync` for development or sync runtime before release.")
        return 1

    # 版本检查
    _check_resource_version()

    # 热更新
    _hot_update()

    import custom

    custom.register_all()
    Tasker.set_log_dir("./debug/agent")

    socket_id = sys.argv[-1]
    logger.debug("socket_id: {}", socket_id)
    log_pi_environment()

    AgentServer.start_up(socket_id)
    logger.info("AgentServer started.")
    AgentServer.join()
    AgentServer.shut_down()
    logger.info("AgentServer stopped.")
    return 0


def log_pi_environment() -> None:
    logger.debug("PI environment snapshot:")
    for key in PI_ENV_KEYS:
        logger.debug("{}={}", key, format_env_value(os.getenv(key, "")))


def format_env_value(value: str, limit: int = 300) -> str:
    if not value:
        return "<empty>"
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...(truncated, total={len(value)})"


# -------------
# endregion
# -------------
