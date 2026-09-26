import importlib.metadata
import sys
import types
from typing import Any
from unittest.mock import Mock, patch

from agent import agent_runtime


def test_log_maafw_version_reports_native_library_version() -> None:
    logger = Mock()
    with (
        patch.object(agent_runtime, "logger", logger),
        patch("maa.library.Library.version", return_value="v5.14.0") as native_version,
        patch("importlib.metadata.version", return_value="5.12.3") as metadata_version,
    ):
        agent_runtime._log_maafw_version()

    native_version.assert_called_once_with()
    metadata_version.assert_not_called()
    logger.debug.assert_called_once_with("maafw {}", "v5.14.0")


def test_log_maafw_version_falls_back_to_binding_metadata() -> None:
    logger = Mock()
    with (
        patch.object(agent_runtime, "logger", logger),
        patch("maa.library.Library.version", side_effect=OSError("MaaFramework.dll not found")),
        patch("importlib.metadata.version", return_value="5.12.3") as metadata_version,
    ):
        agent_runtime._log_maafw_version()

    metadata_version.assert_called_once_with("maafw")
    logger.info.assert_not_called()
    logger.debug.assert_any_call("maafw {}", "5.12.3")


def test_log_maafw_version_treats_empty_native_version_as_failure() -> None:
    logger = Mock()
    with (
        patch.object(agent_runtime, "logger", logger),
        patch("maa.library.Library.version", return_value=""),
        patch("importlib.metadata.version", return_value="5.12.3") as metadata_version,
    ):
        agent_runtime._log_maafw_version()

    metadata_version.assert_called_once_with("maafw")
    logger.info.assert_not_called()
    logger.debug.assert_any_call("maafw {}", "5.12.3")


def test_log_maafw_version_survives_unresolvable_metadata() -> None:
    logger = Mock()
    with (
        patch.object(agent_runtime, "logger", logger),
        patch("maa.library.Library.version", side_effect=OSError("MaaFramework.dll not found")),
        patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError),
    ):
        agent_runtime._log_maafw_version()

    logger.info.assert_not_called()
    logger.debug.assert_called_once()


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
