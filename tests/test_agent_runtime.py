import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from agent import agent_runtime


class AgentRuntimeTest(unittest.TestCase):
    def test_maa_log_dir_matches_pre_refactor_relative_debug_path(self):
        fake_utils = types.ModuleType("utils")
        fake_logger_module: Any = types.ModuleType("utils.logger")
        fake_logger_module.change_console_level = Mock()

        fake_paths = types.SimpleNamespace(
            debug_dir=Path("C:/Users/example/新建文件夹/debug")
        )
        fake_get_runtime_paths = Mock(return_value=fake_paths)

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
            "utils": fake_utils,
            "utils.logger": fake_logger_module,
            "maa": types.ModuleType("maa"),
            "maa.agent": types.ModuleType("maa.agent"),
            "maa.agent.agent_server": fake_agent_server,
            "maa.tasker": fake_tasker,
            "custom": fake_custom,
        }

        with patch.object(
            agent_runtime,
            "_reload_utils",
            return_value=(fake_utils, fake_get_runtime_paths),
        ):
            with patch.dict(sys.modules, fake_modules):
                with patch.object(sys, "argv", ["agent/main.py", "socket-id"]):
                    agent_runtime.run_agent(
                        "C:/Users/example/新建文件夹", is_dev_mode=True
                    )

        fake_tasker.Tasker.set_log_dir.assert_called_once_with("./debug")


if __name__ == "__main__":
    unittest.main()
