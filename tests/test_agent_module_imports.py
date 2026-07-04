import importlib

import pytest


@pytest.mark.parametrize("module_name", ("agent.bootstrap", "agent.agent_runtime"))
def test_bootstrap_and_runtime_support_package_imports(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module is not None
