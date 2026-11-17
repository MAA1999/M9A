import importlib.metadata
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
