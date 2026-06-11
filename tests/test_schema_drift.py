"""schema 与识别类常量的防漂移校验。

custom.recognition.schema.json 中 APMapAnalyze / ATTrailAnalyze 的参数声明
（key 集合与 default 值）必须与类的 OVERRIDABLE 白名单及类常量保持一致，
任何一侧单独修改都会在此失败。
"""

import json
import sys
import types
from pathlib import Path

import pytest

_stub = types.ModuleType("maa.agent.agent_server")


class _StubAgentServer:
    @staticmethod
    def custom_recognition(name):
        def deco(cls):
            return cls

        return deco

    @staticmethod
    def custom_action(name):
        def deco(cls):
            return cls

        return deco


_stub.AgentServer = _StubAgentServer
sys.modules.setdefault("maa.agent.agent_server", _stub)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from custom.reco.auto_promotion import APMapAnalyze  # noqa: E402
from custom.reco.auto_trail import ATTrailAnalyze  # noqa: E402

SCHEMA = json.loads(
    (ROOT / "deps/tools/custom.recognition.schema.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("cls", [APMapAnalyze, ATTrailAnalyze], ids=lambda c: c.__name__)
def test_schema_matches_overridable(cls):
    props = SCHEMA["$defs"][cls.__name__]["properties"]["custom_recognition_param"][
        "properties"
    ]
    schema_keys = set(props) - {"query"}
    code_keys = {const.lower() for const in cls.OVERRIDABLE}
    assert schema_keys == code_keys, (
        f"schema 与 OVERRIDABLE 不一致：仅 schema 有 {schema_keys - code_keys}，"
        f"仅代码有 {code_keys - schema_keys}"
    )


@pytest.mark.parametrize("cls", [APMapAnalyze, ATTrailAnalyze], ids=lambda c: c.__name__)
def test_schema_defaults_match_constants(cls):
    props = SCHEMA["$defs"][cls.__name__]["properties"]["custom_recognition_param"][
        "properties"
    ]
    for const in cls.OVERRIDABLE:
        key = const.lower()
        code_default = getattr(cls, const)
        schema_default = props[key]["default"]
        if isinstance(code_default, (tuple, list)):
            assert list(schema_default) == list(code_default), key
        else:
            assert schema_default == code_default, key
