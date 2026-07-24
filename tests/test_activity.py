from agent.custom.action.activity import _find_active_re_release


def test_find_active_re_release_returns_open_activity() -> None:
    active_re_release = {
        "name": "复刻活动",
        "start_time": 1000,
        "end_time": 3000,
    }
    data = {
        "old": {
            "activity": {
                "combat": {"start_time": 0, "end_time": 1000},
                "re-release": active_re_release,
            }
        },
        "current": {
            "activity": {
                "combat": {"start_time": 2000, "end_time": 4000},
            }
        },
    }

    assert _find_active_re_release(data, 2000) is active_re_release


def test_find_active_re_release_returns_none_outside_open_period() -> None:
    data = {
        "current": {
            "activity": {
                "combat": {"start_time": 2000, "end_time": 4000},
                "re-release": {"start_time": 1000, "end_time": 1500},
            }
        }
    }

    assert _find_active_re_release(data, 2000) is None
