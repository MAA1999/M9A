from __future__ import annotations

import os
import sys

from utils import logger
from utils.runtime_paths import configure_runtime_paths

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


def run_agent(project_root_dir: str) -> int:
    configure_runtime_paths(project_root=project_root_dir, work_root=os.getcwd())

    if len(sys.argv) < 2:
        logger.error("Missing MaaFW Agent socket id argument.")
        return 2

    try:
        from maa.agent.agent_server import AgentServer
        from maa.tasker import Tasker
    except ImportError as error:
        logger.error("Failed to import MaaFW Agent runtime: %s", error)
        logger.error("Run `uv sync` for development or sync runtime before release.")
        return 1

    import custom

    custom.register_all()
    Tasker.set_log_dir("./debug")

    socket_id = sys.argv[-1]
    logger.debug("socket_id: %s", socket_id)
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
        logger.debug("%s=%s", key, format_env_value(os.getenv(key, "")))


def format_env_value(value: str, limit: int = 300) -> str:
    if not value:
        return "<empty>"
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...(truncated, total={len(value)})"
