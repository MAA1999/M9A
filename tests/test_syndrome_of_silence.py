"""SOSSelectNode 跨类型事件自愈的纯函数单测。

覆盖：事件归属查找（精确/相似/未命中）与备用事件名 ROI 收集（去重、排除自身）。
"""

from agent.custom.action.syndrome_of_silence import SOSSelectNode

_NODES = {
    "types": ["已完成节点", "冲突", "途中偶遇", "必经之路", "休憩处"],
    "common_interrupts": {"stats": ["SOSWarning"]},
    "已完成节点": {"event_name_roi": None, "actions": []},
    "冲突": {"event_name_roi": None, "actions": []},
    "恶战": {"event_name_roi": None, "actions": []},
    "途中偶遇": {
        "event_name_roi": [45, 74, 207, 29],
        "events": {"鬃毛的回报": {"actions": []}},
    },
    "必经之路": {
        "event_name_roi": [858, 72, 155, 33],
        "events": {"黑袍访客": {"actions": []}, "旅途的开始": {"actions": []}},
    },
    "休憩处": {
        "event_name_roi": [858, 72, 132, 33],
        "events": {"俱乐部来客": {"actions": []}},
    },
}


def test_find_event_owner_exact_hit() -> None:
    """OCR 文本与事件表精确一致时返回归属类型。"""
    assert SOSSelectNode._find_event_owner("黑袍访客", _NODES) == "必经之路"


def test_find_event_owner_fuzzy_hit() -> None:
    """OCR 有轻微错字时按 0.6 相似度兜底命中。"""
    assert SOSSelectNode._find_event_owner("黑袍访容", _NODES) == "必经之路"


def test_find_event_owner_miss_returns_none() -> None:
    """完全无关文本不强行归属。"""
    assert SOSSelectNode._find_event_owner("毫不相干的乱码", _NODES) is None


def test_find_event_owner_ignores_meta_keys() -> None:
    """types / common_interrupts 等元数据键不参与查找且不抛错。"""
    assert SOSSelectNode._find_event_owner("stats", _NODES) is None


def test_collect_alt_event_rois_excludes_own_and_dedup() -> None:
    """备用 ROI 排除自身类型，跨类型重复 ROI 只保留一次，保持首现顺序。"""
    rois = SOSSelectNode._collect_alt_event_rois(_NODES, "途中偶遇")
    assert rois == [[858, 72, 155, 33], [858, 72, 132, 33]]


def test_collect_alt_event_rois_skips_null_roi_types() -> None:
    """无事件名类型（event_name_roi=None）不产生备用 ROI。"""
    assert SOSSelectNode._collect_alt_event_rois(_NODES, "必经之路") == [
        [45, 74, 207, 29],
        [858, 72, 132, 33],
    ]


def test_match_node_type_exact_hit() -> None:
    """预览面板 OCR 文本与类型名完全一致。"""
    assert SOSSelectNode._match_node_type("必经之路", _NODES) == "必经之路"


def test_match_node_type_containment_hit() -> None:
    """类型名带前后缀修饰时按包含关系命中（如「恶战·试炼」→ 恶战）。"""
    assert SOSSelectNode._match_node_type("恶战·试炼", _NODES) == "恶战"


def test_match_node_type_miss_returns_empty() -> None:
    """无法归属的文本返回空串，保留模板识别结果。"""
    assert SOSSelectNode._match_node_type("毫不相干的乱码", _NODES) == ""
