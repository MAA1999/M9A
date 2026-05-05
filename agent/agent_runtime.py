import importlib
import os
import sys
from pathlib import Path

try:
    from bootstrap import read_hot_update_config
    from utils import logger
except ImportError:
    from .bootstrap import read_hot_update_config
    from .utils import logger


def _format_env_value(value: str, limit: int = 300) -> str:
    if not value:
        return "<empty>"
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...(truncated, total={len(value)})"


def log_pi_environment() -> None:
    pi_env_keys = [
        "PI_INTERFACE_VERSION",
        "PI_CLIENT_NAME",
        "PI_CLIENT_VERSION",
        "PI_CLIENT_LANGUAGE",
        "PI_CLIENT_MAAFW_VERSION",
        "PI_VERSION",
        "PI_CONTROLLER",
        "PI_RESOURCE",
    ]

    logger.debug("PI environment snapshot:")
    for key in pi_env_keys:
        logger.debug(f"{key}={_format_env_value(os.getenv(key, ''))}")


def _reload_utils(project_root_dir: str):
    # 清理模块缓存
    utils_modules = [
        name
        for name in list(sys.modules.keys())
        if name == "utils"
        or name.startswith("utils.")
        or name == "agent.utils"
        or name.startswith("agent.utils.")
    ]
    for module_name in utils_modules:
        del sys.modules[module_name]

    # 动态导入 utils 的所有内容
    try:
        import utils
    except ImportError:
        from . import utils

    importlib.reload(utils)
    try:
        from utils.runtime_paths import configure_runtime_paths, get_runtime_paths
    except ImportError:
        from .utils.runtime_paths import configure_runtime_paths, get_runtime_paths

    configure_runtime_paths(project_root=project_root_dir, work_root=Path.cwd())
    return utils, get_runtime_paths


def run_agent(project_root_dir: str, is_dev_mode=False):
    try:
        utils, get_runtime_paths = _reload_utils(project_root_dir)

        # 将 utils 的所有公共属性导入到当前命名空间
        for attr_name in dir(utils):
            if not attr_name.startswith("_"):
                globals()[attr_name] = getattr(utils, attr_name)

        if is_dev_mode:
            from utils.logger import change_console_level

            change_console_level("DEBUG")
            logger.info("开发模式：日志等级已设置为DEBUG")

        if not is_dev_mode:
            # ========== 版本检查（始终执行） ==========
            from utils.version_checker import check_resource_version

            version_info = check_resource_version()
            if not version_info["is_latest"]:
                logger.warning("检测到资源有新版本!")
                logger.warning(f"当前资源版本: {version_info['current_version']}")
                logger.warning(f"最新资源版本: {version_info['latest_version']}")
            elif version_info["error"]:
                logger.debug(f"资源版本检查遇到问题: {version_info['error']}")

            # ========== 热更新：基于 manifest 时间戳优化 ==========
            hot_update_conf = read_hot_update_config()
            if not hot_update_conf.get("enable_hot_update", True):
                logger.info("已配置为跳过部分资源热更")
            else:
                from utils.manifest_checker import (
                    check_manifest_updates,
                    save_manifest_cache_from_result,
                )

                manifest_result = check_manifest_updates()

                # 如果没有任何更新，跳过热更新
                if manifest_result["success"] and not manifest_result["has_any_update"]:
                    logger.debug("资源无更新，跳过热更新")
                else:
                    # 有更新或检查失败，执行热更新流程
                    updated_manifests = manifest_result.get("updated_manifests", [])

                    if updated_manifests or not manifest_result["success"]:
                        from utils.resource_updater import check_and_update_resources

                        # 只更新有变化的 manifest
                        manifests = (
                            updated_manifests if manifest_result["success"] else None
                        )
                        if manifests:
                            logger.debug(f"开始更新 {len(manifests)} 个资源清单...")
                        else:
                            logger.debug("开始检查所有资源...")

                        update_result = check_and_update_resources(
                            resource_manifests=manifests
                        )
                        if update_result and update_result.get("updated_files"):
                            pass
                        elif update_result and update_result.get("error"):
                            logger.debug(
                                f"热更部分资源更新遇到问题: {update_result['error']}"
                            )
                        else:
                            logger.debug("热更部分资源已是最新")
                    else:
                        logger.debug("所有 manifest 无更新，跳过热更新")

                # 检查成功后保存 manifest 缓存（无论是否有更新）
                save_manifest_cache_from_result(manifest_result)
            # ========== 热更新结束 ==========

        from maa.agent.agent_server import AgentServer
        from maa.tasker import Tasker

        try:
            import custom
        except ImportError:
            from . import custom

        custom.register_all()

        Tasker.set_log_dir(str(get_runtime_paths().debug_dir))

        if len(sys.argv) < 2:
            logger.error("缺少必要的 socket_id 参数")
            return

        socket_id = sys.argv[-1]
        logger.debug(f"socket_id: {socket_id}")

        log_pi_environment()
        AgentServer.start_up(socket_id)
        logger.info("AgentServer启动")
        AgentServer.join()
        AgentServer.shut_down()
        logger.info("AgentServer关闭")
    except ImportError as e:
        logger.error(f"导入模块失败: {e}")
        logger.error("考虑重新配置环境")
        sys.exit(1)
    except Exception:
        logger.exception("agent运行过程中发生异常")
        raise
