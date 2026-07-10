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


def test_hot_update_does_not_save_cache_after_failed_update() -> None:
    save_cache = Mock()
    check_result = {
        "success": True,
        "has_any_update": True,
        "updated_manifests": ["data/manifest.json"],
    }
    fake_manifest_checker: Any = types.ModuleType("utils.manifest_checker")
    fake_manifest_checker.check_manifest_updates = Mock(return_value=check_result)
    fake_manifest_checker.save_manifest_cache_from_result = save_cache

    fake_resource_updater: Any = types.ModuleType("utils.resource_updater")
    fake_resource_updater.check_and_update_resources = Mock(
        return_value={"success": False, "updated_files": [], "error": "hash mismatch"}
    )

    with patch.dict(
        sys.modules,
        {
            "utils.manifest_checker": fake_manifest_checker,
            "utils.resource_updater": fake_resource_updater,
        },
    ):
        with patch.object(agent_runtime, "_read_hot_update_config", return_value={"enable_hot_update": True}):
            agent_runtime._hot_update()

    save_cache.assert_not_called()


def test_hot_update_saves_cache_after_successful_update() -> None:
    save_cache = Mock()
    check_result = {
        "success": True,
        "has_any_update": True,
        "updated_manifests": ["data/manifest.json"],
    }
    fake_manifest_checker: Any = types.ModuleType("utils.manifest_checker")
    fake_manifest_checker.check_manifest_updates = Mock(return_value=check_result)
    fake_manifest_checker.save_manifest_cache_from_result = save_cache

    fake_resource_updater: Any = types.ModuleType("utils.resource_updater")
    fake_resource_updater.check_and_update_resources = Mock(
        return_value={"success": True, "updated_files": ["data/value.json"], "error": ""}
    )

    with patch.dict(
        sys.modules,
        {
            "utils.manifest_checker": fake_manifest_checker,
            "utils.resource_updater": fake_resource_updater,
        },
    ):
        with patch.object(agent_runtime, "_read_hot_update_config", return_value={"enable_hot_update": True}):
            agent_runtime._hot_update()

    save_cache.assert_called_once_with(check_result)
