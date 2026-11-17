from __future__ import annotations

import importlib.metadata
import os
import sys

from maafw_paths import ENV_NAME
from utils.logger import logger
from utils.runtime_paths import (
    configure_runtime_paths,
    default_work_root,
    get_runtime_paths,
    link_work_root,
)

PI_ENV_KEYS = (
    "PI_INTERFACE_VERSION",
    "PI_CLIENT_NAME",
    "PI_CLIENT_VERSION",
    "PI_CLIENT_LANGUAGE",
    "PI_CLIENT_MAAFW_VERSION",
    "PI_VERSION",
    "PI_USER_DATA_DIR",
    "PI_CONTROLLER",
    "PI_RESOURCE",
)


# -------------
# region 启动入口
# -------------
def _log_maafw_version() -> None:
    """报告 agent 进程实际加载的原生库版本。

    pip 元数据不可信：客户端增量更新往 site-packages 写新版 dist-info 时不删旧版，两份
    并存时 importlib.metadata.version 返回哪份并无保证（实测返回过时值）。因此以原生库
    的 MaaVersion() 为准，元数据只在原生查询失败时兜底，失败原因会先记一行 debug。

    必须在导入 maa.agent 之后调用：version() 会首次触发 API 属性初始化，而 Library.open
    撞上已初始化标志就早退，提前调用会把 Library 钉死在非 agent 模式。

    全部走 debug：版本与加载路径是维护者排查用的诊断信息，不进用户看的 GUI 日志；
    agent 文件 sink 固定 DEBUG 级，debug/custom/*.log 里始终可查。
    """
    try:
        from maa.library import Library

        version = Library.version()
        if not version:
            raise RuntimeError("MaaVersion() 返回空值")
    except Exception as error:
        logger.debug("查询原生 MaaFW 版本失败，改用 binding 元数据: {}", error)
        try:
            logger.debug("maafw {}", importlib.metadata.version("maafw"))
        except importlib.metadata.PackageNotFoundError:
            pass
        return

    logger.debug("maafw {}", version)


def run_agent(project_root_dir: str) -> int:
    # PI v2.11.0: the client passes the absolute directory it owns for config, debug and logs.
    # Inside a macOS .app the project root lives in the bundle, which a user account cannot write
    # to, so the working directory is only a fallback for clients that do not set the variable.
    configure_runtime_paths(project_root=project_root_dir, work_root=default_work_root())

    # main.py 已把 cwd 指到数据目录；把包内只读条目链接过去（data/、resource/、agent/、
    # interface.json 等），让按 cwd 读相对路径的组件（libs/drop_core.pyd 读
    # data/combat/*.json 与 ./interface.json、仓库/SOS/掉落模板读 resource/base/image/...）
    # 拿到与 data_path() 同一份文件；config/、debug/ 保持真实目录。
    try:
        linked, failed = link_work_root(get_runtime_paths())
        if failed:
            logger.warning(
                f"{failed} 个包内条目未能链接进数据目录（符号链接不可用或权限不足），"
                "按 cwd 读取 data/resource 的组件可能读不到数据"
            )
        if linked:
            logger.debug(f"已更新 {linked} 个数据目录链接（含旧版 data/interface.json 迁移）")
    except OSError as error:
        logger.warning(f"读取项目目录失败（{error}），二进制插件可能读不到包内数据")

    # debug:纯诊断信息，不进 GUI 日志打扰用户；agent 文件 sink 固定 DEBUG 级，排查时 debug/custom/*.log 里仍有
    logger.debug("MaaFW 二进制目录: {}", os.environ.get(ENV_NAME) or "wheel 自带 (site-packages/maa/bin)")

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

    # 必须在导入 maa.agent 之后调用，原因见 _log_maafw_version
    _log_maafw_version()

    import custom

    custom.register_all()
    Tasker.set_log_dir(str(get_runtime_paths().debug_dir / "agent"))

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
