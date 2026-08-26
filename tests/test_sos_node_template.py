"""SOSSelectNodeTemplate 哨兵测试：只保留跨文件契约与资产完整性检查。

算法纯函数（IoU / NMS / 几何）不在此测——逻辑冻结且实跑验证过；
这里防的是：types 表错位、模板资产缺失、
reco↔action 的 detail 结构漂移。
"""

import json
from pathlib import Path

from agent.custom.reco.sos_node_template import NodeHit, SOSSelectNodeTemplate

# data/sos/nodes.json types（中文）与 CLASS_NAMES（英文）的对应关系
_CN_TYPES = {
    0: "已完成节点",
    1: "冲突",
    2: "险象环生",
    3: "遭遇",
    4: "途中偶遇",
    5: "途中余兴",
    6: "恶战",
    7: "对话",
    8: "休憩处",
    9: "购物契机",
    10: "巧匠之手",
    11: "必经之路",
    12: "藏宝地",
}


def test_class_names_align_with_nodes_json() -> None:
    """CLASS_NAMES 顺序必须与 data/sos/nodes.json 的 types 数组一致。

    动作侧用 nodes["types"][cls_index] 查表，顺序错位不会报错，只会静默点错节点类型。
    """
    class_names = SOSSelectNodeTemplate.CLASS_NAMES
    with open("data/sos/nodes.json", encoding="utf-8") as f:
        nodes = json.load(f)
    assert len(nodes["types"]) == len(class_names) == 13
    for index, cn_name in _CN_TYPES.items():
        assert nodes["types"][index] == cn_name


def _hit(cls_index: int, cls_name: str, box: tuple[int, int, int, int], score: float) -> NodeHit:
    return NodeHit(cls_index=cls_index, cls_name=cls_name, box=box, score=score)


def test_hits_to_detail_matches_action_contract() -> None:
    """SOSSelectNode 动作消费 detail['best']['cls_index'] / ['box']，结构必须兼容。"""
    hits = [
        _hit(6, "FierceBattle", (100, 100, 70, 70), 0.9),
        _hit(9, "ShoppingOpportunity", (500, 300, 70, 70), 0.8),
    ]
    detail = SOSSelectNodeTemplate.hits_to_detail(hits[0], hits)
    assert detail["best"]["cls_index"] == 6
    assert detail["best"]["box"] == [100, 100, 70, 70]
    assert detail["best"]["score"] == 0.9
    assert len(detail["filtered"]) == len(detail["all"]) == 2


def test_templates_shipped_for_all_expected_classes() -> None:
    """每个 expected 类都必须有主模板 nodes/<类名>.png，缺文件会导致该类漏检。"""
    for cls_name in SOSSelectNodeTemplate.EXPECTED_CLASSES:
        path = Path(f"resource/base/image/SyndromeOfSilence/nodes/{cls_name}.png")
        assert path.exists(), f"missing template: {path}"


def test_visited_check_template_shipped() -> None:
    """对勾模板必须随资源发布，缺失会导致已走过节点门控失效。"""
    for rel in SOSSelectNodeTemplate.VISITED_TEMPLATES:
        assert Path(f"resource/base/image/{rel}").exists(), f"missing visited template: {rel}"
