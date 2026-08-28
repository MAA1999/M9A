import sys
import types
from typing import Any
from unittest.mock import Mock, patch

from agent import agent_runtime


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
