import importlib
import unittest
from unittest.mock import call, patch

import agent.custom as custom
import agent.custom.action as action
import agent.custom.reco as reco
import agent.custom.sink as sink


class CustomRegistrationTest(unittest.TestCase):
    def test_package_import_provides_top_level_custom_alias(self):
        self.assertIs(importlib.import_module("custom"), custom)

    def test_custom_registers_actions_recognitions_then_sinks(self):
        with patch.object(custom.action, "register_all") as register_actions:
            with patch.object(custom.reco, "register_all") as register_reco:
                with patch.object(custom.sink, "register_all") as register_sink:
                    custom.register_all()

        register_actions.assert_called_once_with()
        register_reco.assert_called_once_with()
        register_sink.assert_called_once_with()

    def test_action_register_all_imports_declared_modules(self):
        with patch.object(action, "import_module") as import_module:
            action.register_all()

        self.assertEqual(
            import_module.call_args_list,
            [call(f"custom.action.{module}") for module in action.ACTION_MODULES],
        )

    def test_reco_register_all_imports_declared_modules(self):
        with patch.object(reco, "import_module") as import_module:
            reco.register_all()

        self.assertEqual(
            import_module.call_args_list,
            [call(f"custom.reco.{module}") for module in reco.RECO_MODULES],
        )

    def test_sink_register_all_imports_declared_modules(self):
        with patch.object(sink, "import_module") as import_module:
            sink.register_all()

        self.assertEqual(
            import_module.call_args_list,
            [call(f"custom.sink.{module}") for module in sink.SINK_MODULES],
        )


if __name__ == "__main__":
    unittest.main()
