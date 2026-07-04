import sys
import types
from typing import Any
from unittest.mock import Mock, patch

from agent import agent_runtime


def test_maa_log_dir_matches_pre_refactor_relative_debug_path() -> None:
    fake_agent_server: Any = types.ModuleType("maa.agent.agent_server")
    fake_agent_server.AgentServer = types.SimpleNamespace(
        start_up=Mock(),
        join=Mock(),
        shut_down=Mock(),
    )

    fake_tasker: Any = types.ModuleType("maa.tasker")
    fake_tasker.Tasker = types.SimpleNamespace(set_log_dir=Mock())

    fake_custom: Any = types.ModuleType("custom")
    fake_custom.register_all = Mock()

    fake_modules = {
        "maa": types.ModuleType("maa"),
        "maa.agent": types.ModuleType("maa.agent"),
        "maa.agent.agent_server": fake_agent_server,
        "maa.tasker": fake_tasker,
        "custom": fake_custom,
    }

    with patch.dict(sys.modules, fake_modules):
        with patch.object(sys, "argv", ["agent/main.py", "socket-id"]):
            with patch.object(agent_runtime, "_check_resource_version"):
                with patch.object(agent_runtime, "_hot_update"):
                    agent_runtime.run_agent("C:/Users/example/新建文件夹")

    fake_tasker.Tasker.set_log_dir.assert_called_once_with("./debug")
