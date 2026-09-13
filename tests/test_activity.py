from types import SimpleNamespace
from typing import Any

from custom.action import activity as activity_action

# 注意：自定义动作/识别要用生产代码相同的模块名（custom.*）导入，
# 否则同一个文件会被加载两次，AgentServer 会因重复注册直接抛 RuntimeError
from custom.reco.activity import ActivityRe_releaseChapter

# 让"当前生效"与真实时钟无关
ALWAYS_OPEN = {"start_time": 0, "end_time": 9_999_999_999_999}


class _FakeContext:
    def __init__(self) -> None:
        self.pipeline_overrides: list[dict[str, Any]] = []
        self.next_overrides: list[tuple[str, list[str]]] = []

    def override_pipeline(self, pipeline_override: dict[str, Any]) -> None:
        self.pipeline_overrides.append(pipeline_override)

    def override_next(self, node_name: str, next_list: list[str]) -> None:
        self.next_overrides.append((node_name, next_list))


class _RecoContextWithoutCalls:
    def run_recognition(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("参数非法时不应执行识别")


def _argv(param: str, node_name: str = "JudgeDuringRe_release") -> Any:
    return SimpleNamespace(custom_action_param=param, node_name=node_name)


def test_active_section_returns_open_re_release() -> None:
    active = {"start_time": 1000, "end_time": 3000, "name": "复刻活动", "alias": "复刻活动"}
    data = {
        "old": {
            "activity": {
                "combat": {"start_time": 0, "end_time": 1000},
                "re-release": active,
            }
        },
        "current": {
            "activity": {
                "combat": {"start_time": 2000, "end_time": 4000},
            }
        },
    }

    result = activity_action._active_section(data, 2000, "re-release")

    assert result is not None
    key, block = result
    assert key == "old"
    assert block is active


def test_active_section_returns_none_outside_open_period() -> None:
    data = {
        "current": {
            "activity": {
                "combat": {"start_time": 2000, "end_time": 4000},
                "re-release": {"start_time": 1000, "end_time": 1500},
            }
        }
    }

    assert activity_action._active_section(data, 2000, "re-release") is None


def test_active_section_tolerates_missing_name_field() -> None:
    """回归：国服 3.9 的数据只有 start_time/end_time，没有 name/alias，不能抛 KeyError。"""
    data = {
        "3.9": {
            "version_name": "重燃！流金之海",
            "activity": {"re-release": dict(ALWAYS_OPEN)},
        }
    }

    result = activity_action._active_section(data, 1_700_000_000_000, "re-release")

    assert result is not None
    key, block = result
    assert key == "3.9"
    assert activity_action._re_release_alias(block) is None


def test_active_section_skips_entry_without_time_fields() -> None:
    data = {"broken": {"activity": {"combat": {"event_type": "MainStory"}}}}

    assert activity_action._active_section(data, 1_700_000_000_000, "combat") is None
    assert activity_action._active_section(data, 1_700_000_000_000, "anecdote") is None


def test_during_act_skips_when_no_active_combat(monkeypatch: Any) -> None:
    data = {"1.0": {"activity": {"combat": {"start_time": 0, "end_time": 1000}}}}
    monkeypatch.setattr(activity_action, "_load_activity_data", lambda resource: data)
    context = _FakeContext()

    result = activity_action.DuringAct().run(context, _argv('{"resource": "cn"}', "JudgeDuringAct"))

    assert result.success is True
    assert context.next_overrides == [("JudgeDuringAct", [])]


def test_during_re_release_skips_when_alias_missing(monkeypatch: Any) -> None:
    """回归：复刻数据缺 name/alias 时应明确跳过并提示，而不是拿空别名继续点卡片。"""
    data = {
        "3.9": {
            "version_name": "重燃！流金之海",
            "activity": {"re-release": dict(ALWAYS_OPEN)},
        }
    }
    monkeypatch.setattr(activity_action, "_load_activity_data", lambda resource: data)
    context = _FakeContext()

    result = activity_action.DuringRe_release().run(context, _argv('{"resource": "cn"}'))

    assert result.success is True
    assert context.pipeline_overrides == []
    assert context.next_overrides == [("JudgeDuringRe_release", ["ActivityRe_releaseChapterError"])]


def test_during_re_release_applies_alias_and_override(monkeypatch: Any) -> None:
    data_override = {"JudgeDuringRe_release": {"next": ["ActivityRe_releaseChapter"]}}
    data = {
        "3.9": {
            "version_name": "重燃！流金之海",
            "activity": {
                "re-release": {
                    **ALWAYS_OPEN,
                    "name": "迁流的盛宴",
                    "alias": "迁流的盛宴",
                    "override": data_override,
                }
            },
        }
    }
    monkeypatch.setattr(activity_action, "_load_activity_data", lambda resource: data)
    context = _FakeContext()

    result = activity_action.DuringRe_release().run(context, _argv('{"resource": "cn"}'))

    assert result.success is True
    assert context.next_overrides == []
    assert {
        "ActivityMainChapter": {"enabled": True},
        "ActivityRe_releaseChapter": {"custom_recognition_param": {"Re_release_name": "迁流的盛宴"}},
    } in context.pipeline_overrides
    assert data_override in context.pipeline_overrides


def test_activity_re_release_recognition_rejects_empty_name() -> None:
    """回归：空别名会让 `expected in text` 恒真，必须直接判失败。"""
    recognition = ActivityRe_releaseChapter()

    result = recognition.analyze(
        _RecoContextWithoutCalls(),
        SimpleNamespace(custom_recognition_param='{"Re_release_name": ""}', node_name="ActivityRe_releaseChapter"),
    )

    assert result.box is None
