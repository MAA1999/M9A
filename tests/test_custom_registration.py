import ast
import importlib
import json
from pathlib import Path
from unittest.mock import call, patch

import agent.custom as custom
import agent.custom.action as action
import agent.custom.reco as reco
import agent.custom.sink as sink

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _decorator_contract(directory: str, decorator_name: str) -> tuple[list[str], set[str]]:
    names: list[str] = []
    modules: set[str] = set()
    for path in sorted((PROJECT_ROOT / directory).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == decorator_name
                    and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                    and isinstance(decorator.args[0].value, str)
                ):
                    names.append(decorator.args[0].value)
                    modules.add(path.stem)
    return names, modules


def _schema_const(definition: object, property_name: str) -> str | None:
    if not isinstance(definition, dict):
        return None
    properties = definition.get("properties")
    if not isinstance(properties, dict):
        return None
    custom_property = properties.get(property_name)
    if not isinstance(custom_property, dict):
        return None
    name = custom_property.get("const")
    return name if isinstance(name, str) else None


def _schema_names(schema_file: str, property_name: str) -> tuple[set[str], set[str], set[str]]:
    schema = json.loads((PROJECT_ROOT / "tools" / "schema" / schema_file).read_text(encoding="utf-8"))
    enum_names = set(schema["properties"][property_name]["enum"])

    referenced_defs = {
        item["$ref"].rsplit("/", 1)[-1]
        for item in schema["anyOf"]
        if isinstance(item, dict) and isinstance(item.get("$ref"), str)
    }
    referenced_names = {
        const_name
        for name in referenced_defs
        if (const_name := _schema_const(schema["$defs"].get(name), property_name)) is not None
    }
    defined_names = {
        const_name
        for definition in schema["$defs"].values()
        if (const_name := _schema_const(definition, property_name)) is not None
    }
    return enum_names, referenced_names, defined_names


def test_package_import_provides_top_level_custom_alias() -> None:
    assert importlib.import_module("custom") is custom


def test_custom_registers_actions_recognitions_then_sinks() -> None:
    with patch.object(custom.action, "register_all") as register_actions:
        with patch.object(custom.reco, "register_all") as register_reco:
            with patch.object(custom.sink, "register_all") as register_sink:
                custom.register_all()

    register_actions.assert_called_once_with()
    register_reco.assert_called_once_with()
    register_sink.assert_called_once_with()


def test_action_register_all_imports_declared_modules() -> None:
    with patch.object(action, "import_module") as import_module:
        action.register_all()

    assert import_module.call_args_list == [call(f"custom.action.{module}") for module in action.ACTION_MODULES]


def test_reco_register_all_imports_declared_modules() -> None:
    with patch.object(reco, "import_module") as import_module:
        reco.register_all()

    assert import_module.call_args_list == [call(f"custom.reco.{module}") for module in reco.RECO_MODULES]


def test_sink_register_all_imports_declared_modules() -> None:
    with patch.object(sink, "import_module") as import_module:
        sink.register_all()

    assert import_module.call_args_list == [call(f"custom.sink.{module}") for module in sink.SINK_MODULES]


def test_custom_action_registration_matches_schema() -> None:
    registered_name_list, registered_modules = _decorator_contract("agent/custom/action", "custom_action")
    registered_names = set(registered_name_list)
    enum_names, referenced_names, defined_names = _schema_names("custom.action.schema.json", "custom_action")

    assert len(registered_name_list) == len(registered_names)
    assert registered_modules == set(action.ACTION_MODULES)
    assert registered_names == enum_names == referenced_names == defined_names


def test_custom_recognition_registration_matches_schema() -> None:
    registered_name_list, registered_modules = _decorator_contract("agent/custom/reco", "custom_recognition")
    registered_names = set(registered_name_list)
    enum_names, referenced_names, defined_names = _schema_names("custom.recognition.schema.json", "custom_recognition")

    assert len(registered_name_list) == len(registered_names)
    assert registered_modules == set(reco.RECO_MODULES)
    assert registered_names == enum_names == referenced_names == defined_names
