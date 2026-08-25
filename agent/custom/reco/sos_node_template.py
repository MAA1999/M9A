"""局外演绎：无声综合征-节点选择（模板匹配后端）。

逐类 TemplateMatch（TM_CCOEFF_NORMED）+ 三重门控（全局阈值 / 每类阈值 /
已走过对勾门控）：新增节点类型只需在
``resource/base/image/SyndromeOfSilence/nodes/`` 下放一张 ``<类名>.png``。

- 类别索引与 ``data/sos/nodes.json`` 的 ``types`` 数组严格一致
- 输出 detail 为 best/filtered/all 结构，``SOSSelectNode`` 自定义动作直接消费
- 模板来自数据集 GT 裁剪（medoid），标定与评测工具见
  m9a-vision-training 仓库 ``tools/sos_templates/``
- 已走过节点由右上角对勾识别（游戏显式标记，跨章节外观恒定）；
  曾用的绝对亮度 V-gate 在暗色章节（巴黎子午线，可点节点 V 0.26~0.41）
  会误杀全部可点节点，已默认停用（常量保留应急）
- 实现全部收敛在 ``SOSSelectNodeTemplate`` 类内（常量 + staticmethod/
  classmethod），模块级仅暴露 ``NodeHit`` 类型；staticmethod/classmethod
  可脱离实例直接测试（见 tests/test_sos_node_template.py）
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import BoxAndScoreResult
from utils import logger
from utils.maa_types import is_hit, results_as


@dataclass(frozen=True)
class NodeHit:
    """单个节点命中。"""

    cls_index: int
    cls_name: str
    box: tuple[int, int, int, int]  # x, y, w, h
    score: float


@AgentServer.custom_recognition("SOSSelectNodeTemplate")
class SOSSelectNodeTemplate(CustomRecognition):
    """局外演绎：无声综合征-节点选择（模板匹配后端）。

    无入参：threshold / roi / v_gate / class_thresholds 等标定值
    一律以类常量为唯一真源（见下方 DEFAULT_* 定义）。
    """

    # ---- 类型表（顺序契约：与 data/sos/nodes.json 的 types 数组严格一致）----

    CLASS_NAMES: list[str] = [
        "C",
        "Conflict",
        "Dangerous",
        "Encounter",
        "EncounterAlongTheWay",
        "EntertainmentOnTheWay",
        "FierceBattle",
        "Message",
        "RestArea",
        "ShoppingOpportunity",
        "TheHandOfAMasterCraftsman",
        "TheOnlyWay",
        "TreasureLand",
    ]

    # 排除已完成节点(C)与对话(Message)：与 data/sos/nodes.json 的类型表对齐
    EXPECTED_CLASSES: list[str] = [name for name in CLASS_NAMES if name not in ("C", "Message")]

    CLASS_TO_INDEX: dict[str, int] = {name: index for index, name in enumerate(CLASS_NAMES)}

    # 每类模板：nodes/<类名>.png 为必需，<类名>_1.png / _2.png 为可选补充（不同外观状态）
    TEMPLATE_SUFFIXES: list[str] = ["", "_1", "_2"]

    # 已走过对勾模板（相对 image 目录）：橙圆白勾，游戏显式「已走过」标记
    VISITED_TEMPLATES: list[str] = ["SyndromeOfSilence/visited_check.png"]

    # ---- 标定默认值（类常量即唯一真源，无 pipeline 入参覆盖）----
    # 标定：valid 集 50 图，14 张模板（13 + 巴黎 Encounter_2）+ 对勾门控下
    # thr=0.8 时 P=0.986/R=1.000/fp_on_C=0（旧 V-gate 方案 P=1.000/R=0.957 且暗色章节全灭）；
    # TheOnlyWay TP 最低 0.847，故全局阈值不能高于 0.84（工具见 m9a-vision-training tools/sos_templates/）
    DEFAULT_THRESHOLD = 0.8
    # 每类阈值覆盖：EntertainmentOnTheWay 存在与可点徽章同形但不可领取的亮徽章
    # （NCC 0.82~0.88，无金色角标），其真命中全部 ≥0.95，0.9 可零损失切分
    DEFAULT_CLASS_THRESHOLDS: dict[str, float] = {"EntertainmentOnTheWay": 0.9}
    DEFAULT_ROI: list[int] = [0, 30, 1280, 600]
    # 已走过节点对勾门控：右上角橙圆白勾是游戏的显式「已走过」标记，跨章节外观恒定。
    # 标定：476 个可点角标 0 误报 @0.5，走过角标（数据集 C + 巴黎帧）NCC 中位 0.80。
    # 已知局限：变暗的对勾（低对比度）NCC 掉到 0.5 以下会漏检，代价是一次空点击（可恢复）。
    DEFAULT_VISITED_CHECK = 0.5
    # 亮度门限（应急保留，默认停用）：绝对 V 阈值跨章节不迁移——
    # 亮色章节可点 V p5≈0.42，暗色章节（巴黎子午线）可点 V 仅 0.26~0.41
    DEFAULT_V_GATE: float | None = None

    # ---- 禁区与滑动参数 ----

    FORBIDDEN_ROI: list[int] = [0, 140, 348, 284]
    SWIPE_LONG: dict[str, Any] = {"begin": [402, 564, 34, 36], "end": [902, 569, 34, 36], "duration": 500}
    SWIPE_SHORT: dict[str, Any] = {"begin": [402, 564, 34, 36], "end": [552, 569, 34, 36], "duration": 500}

    # ---- 几何 / 评分纯函数（staticmethod，可脱离实例直接测试）----

    @staticmethod
    def box_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        """两个 (x, y, w, h) 框的 IoU。"""
        iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        if iw <= 0 or ih <= 0:
            return 0.0
        inter = iw * ih
        return inter / (a[2] * a[3] + b[2] * b[3] - inter)

    @classmethod
    def nms_hits(cls, hits: list[NodeHit], iou_threshold: float = 0.3) -> list[NodeHit]:
        """跨类别 NMS：同一位置只保留分数最高的类别。"""
        kept: list[NodeHit] = []
        for hit in sorted(hits, key=lambda h: h.score, reverse=True):
            if all(cls.box_iou(hit.box, k.box) < iou_threshold for k in kept):
                kept.append(hit)
        return kept

    @staticmethod
    def boxes_intersect(a: tuple[int, int, int, int] | list[int], b: tuple[int, int, int, int] | list[int]) -> bool:
        """两框是否相交（只要相交就算，用于禁区判定）。"""
        return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]

    @staticmethod
    def badge_value(image: np.ndarray, box: tuple[int, int, int, int]) -> float:
        """徽章中心圆区的平均亮度 V（HSB 的 V = max(R,G,B)），用于已完成节点门控。"""
        x, y, w, h = box
        cx, cy = x + w // 2, y + h // 2
        r = max(2, int(min(w, h) * 0.32))
        crop = image[max(0, cy - r) : cy + r, max(0, cx - r) : cx + r].astype("float64") / 255.0
        if crop.size == 0:
            return 0.0
        return float(crop.max(-1).mean())

    @staticmethod
    def corner_region(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """节点框的右上角区域（对勾位置）。

        实测（巴黎帧检测框）：对勾圆心在 (x+w-3, y+1)，直径约 28px；
        区域外扩到 (x+w-20, y-14, 34, 32) 以容忍 ±5px 对齐误差。
        """
        x, y, w, _h = box
        return (x + w - 20, y - 14, 34, 32)

    @staticmethod
    def hits_to_detail(best: NodeHit | None, hits: list[NodeHit]) -> dict[str, Any]:
        """合成 best/filtered/all 结构的 detail（供 SOSSelectNode 动作消费）。"""

        def ser(hit: NodeHit) -> dict[str, Any]:
            return {
                "box": list(hit.box),
                "score": hit.score,
                "cls_index": hit.cls_index,
                "cls_name": hit.cls_name,
                "label": hit.cls_name,
            }

        serialized = [ser(hit) for hit in hits]
        return {
            "all": serialized,
            "filtered": serialized,
            "best": ser(best) if best is not None else None,
        }

    # ---- 识别主体 ----

    @classmethod
    def _existing_templates(cls, cls_name: str) -> list[str]:
        """收集某类已存在的模板路径（相对 image 目录）。"""
        templates: list[str] = []
        for suffix in cls.TEMPLATE_SUFFIXES:
            if Path(f"resource/base/image/SyndromeOfSilence/nodes/{cls_name}{suffix}.png").exists():
                templates.append(f"SyndromeOfSilence/nodes/{cls_name}{suffix}.png")
        return templates

    @classmethod
    def collect_visited_boxes(
        cls,
        context: Context,
        image: np.ndarray,
        roi: list[int],
        visited_threshold: float | None = DEFAULT_VISITED_CHECK,
    ) -> list[tuple[int, int, int, int]]:
        """整帧搜「已走过」对勾，返回全部命中框。

        复用 ``SOSSelectNode_rec_template`` 管线节点、仅覆盖参数（对勾模板 +
        固定阈值，与节点阈值无关）。``visited_threshold`` 为 None 时跳过搜索。
        """
        if visited_threshold is None:
            return []
        detail = context.run_recognition(
            "SOSSelectNode_rec_template",
            image,
            {
                "SOSSelectNode_rec_template": {
                    "recognition": {
                        "param": {
                            "template": cls.VISITED_TEMPLATES,
                            "threshold": float(visited_threshold),
                            "roi": roi,
                            "method": 5,
                            "order_by": "Score",
                        }
                    }
                }
            },
        )
        return [
            (int(result.box[0]), int(result.box[1]), int(result.box[2]), int(result.box[3]))
            for result in results_as(detail, BoxAndScoreResult)
        ]

    @classmethod
    def collect_template_hits(
        cls,
        context: Context,
        image: np.ndarray,
        threshold: float,
        roi: list[int],
        v_gate: float | None = DEFAULT_V_GATE,
        class_thresholds: dict[str, float] | None = None,
        visited_threshold: float | None = DEFAULT_VISITED_CHECK,
    ) -> list[NodeHit]:
        """逐类运行 TemplateMatch 并合并结果。

        每类一次调用（该类的全部模板放进同一次匹配），模板身份在类内无需区分。
        整帧先搜一次「已走过」对勾，命中框与节点角部相交的检测丢弃（已走过节点）。
        ``v_gate`` 不为 None 时，额外丢弃徽章中心亮度过低的检测（应急门控，默认停用）。
        ``class_thresholds`` 按类覆盖全局 ``threshold``（缺类回落全局值）。
        """
        class_thresholds = class_thresholds or {}
        visited_boxes = cls.collect_visited_boxes(context, image, roi, visited_threshold)
        hits: list[NodeHit] = []
        for cls_name in cls.EXPECTED_CLASSES:
            templates = cls._existing_templates(cls_name)
            if not templates:
                logger.warning(f"[SOSSelectNodeTemplate] 缺少模板 nodes/{cls_name}.png，跳过该类")
                continue
            cls_threshold = float(class_thresholds.get(cls_name, threshold))

            detail = context.run_recognition(
                "SOSSelectNode_rec_template",
                image,
                {
                    "SOSSelectNode_rec_template": {
                        "recognition": {
                            "param": {
                                "template": templates,
                                "threshold": cls_threshold,
                                "roi": roi,
                                "method": 5,
                                "order_by": "Score",
                            }
                        }
                    }
                },
            )
            cls_index = cls.CLASS_TO_INDEX[cls_name]
            for result in results_as(detail, BoxAndScoreResult):
                box = (int(result.box[0]), int(result.box[1]), int(result.box[2]), int(result.box[3]))
                corner = cls.corner_region(box)
                if any(cls.boxes_intersect(corner, visited) for visited in visited_boxes):
                    continue
                if v_gate is not None and cls.badge_value(image, box) < v_gate:
                    continue
                hits.append(NodeHit(cls_index, cls_name, box, float(result.score)))

        return cls.nms_hits(hits)

    # ---- 流程编排 ----

    @staticmethod
    def _run_swipe(context: Context, swipe: dict[str, Any]) -> None:
        """向右滑动地图。"""
        context.run_task(
            "Swipe",
            {
                "Swipe": {
                    "action": {
                        "type": "Swipe",
                        "param": {
                            "begin": swipe["begin"],
                            "end": swipe["end"],
                            "duration": swipe["duration"],
                        },
                    }
                }
            },
        )

    @classmethod
    def _analyze_node_hit(
        cls,
        context: Context,
        node_box: tuple[int, int, int, int] | None,
        raw_detail: dict[str, Any],
        *,
        forbidden: bool,
    ) -> "CustomRecognition.AnalyzeResult | None":
        """节点命中后的处理：禁区判断 / 滑动 / 构造返回值。

        Args:
            context: MaaFW 上下文。
            node_box: 最佳节点框；None 表示未识别到节点。
            raw_detail: 传给 AnalyzeResult.detail 的内容（best/filtered/all 结构）。
            forbidden: 是否执行禁区判断（区域委托模式下为 True）。

        Returns:
            AnalyzeResult，或 None 表示本次无节点（由调用方决定是否滑动）。
        """
        if node_box is None:
            return None

        if forbidden and cls.boxes_intersect(node_box, cls.FORBIDDEN_ROI):
            cls._run_swipe(context, cls.SWIPE_LONG)
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "action": "swipe_right",
                    "reason": "node_in_forbidden_area",
                    "node_box": list(node_box),
                },
            )

        return CustomRecognition.AnalyzeResult(box=list(node_box), detail=raw_detail)

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | None:
        hits = self.collect_template_hits(
            context,
            argv.image,
            self.DEFAULT_THRESHOLD,
            self.DEFAULT_ROI,
            self.DEFAULT_V_GATE,
            self.DEFAULT_CLASS_THRESHOLDS,
        )
        best = hits[0] if hits else None

        # 区域委托模式下禁区内的节点不可点，向右滑半屏找新节点
        entrust_detail = context.run_recognition("SOSEntrustrRec", argv.image)
        forbidden = is_hit(entrust_detail)

        result = self._analyze_node_hit(
            context, best.box if best else None, self.hits_to_detail(best, hits), forbidden=forbidden
        )
        if result is not None:
            return result

        # 非委托模式下未识别到节点，向右滑一小段；委托模式不滑动
        if not forbidden:
            self._run_swipe(context, self.SWIPE_SHORT)
        return CustomRecognition.AnalyzeResult(box=None, detail={})
