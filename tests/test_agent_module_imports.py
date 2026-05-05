import importlib
import unittest


class AgentModuleImportsTest(unittest.TestCase):
    def test_bootstrap_and_runtime_support_package_imports(self):
        for module_name in ("agent.bootstrap", "agent.agent_runtime"):
            with self.subTest(module_name=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)


if __name__ == "__main__":
    unittest.main()
