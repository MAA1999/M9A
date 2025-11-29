import re
import json
from typing import Any, Dict, List, Union, Optional

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType
from utils.logger import logger


@AgentServer.custom_recognition("ActivityRe_releaseChapter")
class ActivityRe_releaseChapter(CustomRecognition):
    """
    识别复刻活动对应别名

    参数格式：
    {
        "Re_release_name": "alias"
    }
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        expected = json.loads(argv.custom_recognition_param)["Re_release_name"]
        reco_detail = context.run_recognition("ActivityLeftList", argv.image)

        if reco_detail is None or not reco_detail.hit:
            return CustomRecognition.AnalyzeResult(box=None, detail={})

        for result in reco_detail.all_results:
            if expected in result.text:
                return CustomRecognition.AnalyzeResult(box=result.box, detail={})

        return CustomRecognition.AnalyzeResult(box=None, detail={})


@AgentServer.custom_recognition("FindFirstUnplayedStageByCheckmark")
class FindFirstUnplayedStageByCheckmark(CustomRecognition):
    """
    遍历定义的关卡列表。
    对每个关卡，在指定ROI进行模板匹配以查找“绿色√”图片。
    如果“绿色√”图片未找到，则认为关卡未玩过，并返回其 click_target 区域。
    如果所有关卡都找到了“绿色√”，则返回 None。

    参数格式 (custom_recognition_param):
    {
        "difficulty": "Easy" | "Normal" | "Hard",
        "mode": "Normal" | "Quickly"
        // "template_node_name": "Alarm_FindStageFlag" // (可选)
    }
    """

    # 简单难度下的关卡坐标 (x, y, w, h)
    EASY_COORDS = [
        ((449, 139, 61, 57), (339, 210, 91, 61)),  # 左上
        ((931, 178, 66, 53), (815, 240, 60, 51)),  # 右上
        ((613, 410, 66, 55), (497, 481, 61, 54)),  # 下
    ]

    # 普通/高难难度下的关卡坐标 (x, y, w, h)
    NORMAL_HARD_COORDS = [
        ((403, 143, 62, 56), (326, 209, 66, 35)),  # 左上
        ((1037, 143, 61, 60), (948, 204, 59, 53)),  # 右上
        ((378, 449, 58, 56), (286, 509, 37, 39)),  # 左下
        ((957, 477, 63, 60), (886, 517, 50, 46)),  # 右下
        ((758, 227, 63, 52), (601, 297, 80, 63)),  # 中间
    ]

    # 难度前缀映射
    PREFIX = {"Easy": "日常第", "Normal": "中等第", "Hard": "高难第"}

    def get_stage_list(self, difficulty: str) -> List[Dict[str, Any]]:
        """
        根据难度返回关卡列表，每个关卡包含id、检测区域和点击区域。
        """
        if difficulty == "Easy":
            coords_data_list = self.EASY_COORDS
        elif difficulty in ("Normal", "Hard"):
            coords_data_list = self.NORMAL_HARD_COORDS
        else:
            return []

        prefix = self.PREFIX.get(difficulty, difficulty)
        return [
            {
                "id": f"{prefix}{i + 1}关",
                "checkmark_roi": list(checkmark_coord_tuple),  # 检查“√”的区域
                "click_target": list(click_target_coord_tuple),  # 未通关时点击的区域
            }
            for i, (checkmark_coord_tuple, click_target_coord_tuple) in enumerate(
                coords_data_list
            )
        ]

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        """
        遍历关卡，查找第一个未通关的关卡，返回其点击区域。
        """

        params = json.loads(argv.custom_recognition_param)
        difficulty = params.get("difficulty")
        mode = params.get("mode")
        # logger.info(f"[Checkmark] 开始检查关卡，难度: {difficulty}, 模式: {mode}")

        stages = self.get_stage_list(difficulty)
        if not stages:
            logger.error(f"[Checkmark] 无效难度: '{difficulty}'。")
            return None

        # 检查用的模板节点名，可自定义
        checkmark_node_name = params.get("template_node_name", "Alarm_FindStageFlag")
        # 根据模式选择遍历目标
        targets = (
            [stages[-1]] if mode == "Quickly" else stages if mode == "Normal" else []
        )

        if not targets:
            logger.error(f"[Checkmark] 无效模式: '{mode}'。")
            return None

        for stage in targets:
            sid = stage["id"]
            roi = stage["checkmark_roi"]
            click = stage["click_target"]

            logger.info(f"[Checkmark] 检查 '{sid}' 区域 {roi}。")
            # 在指定ROI区域查找“绿色√”模板
            result = context.run_recognition(
                checkmark_node_name,
                argv.image,
                pipeline_override={checkmark_node_name: {"roi": roi}},
            )

            if result and result.hit:
                # 找到“√”，说明已通关
                logger.info(f"[Checkmark] '{sid}' 已通关。")
                if mode == "Quickly":
                    # 快速模式下只检查最后一个关卡
                    return None
                continue
            else:
                # 未找到“√”，说明未通关，返回点击区域
                logger.info(f"[Checkmark] '{sid}' 未通关，返回点击区域 {click}。")
                return CustomRecognition.AnalyzeResult(
                    box=click,
                    detail={},
                )

        logger.info(f"[Checkmark] 所有关卡已通关。")
        return None


@AgentServer.custom_recognition("SailingRecordSelectTarget")
class SailingRecordSelectTarget(CustomRecognition):
    """
    识别航海记录界面中的目标关卡

    参数格式：
    {
        "level": 0 | 1,  // 0: 普通, 1: 困难
    }
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        level = json.loads(argv.custom_recognition_param)["level"]

        # level 1
        if level == 1:
            reco_detail = context.run_recognition(
                "SailingRecordFindDifficult", argv.image
            )
            if reco_detail and reco_detail.hit:
                # 扩展 roi 到 click_target
                box = [
                    reco_detail.box[0] - 317,
                    reco_detail.box[1] + 25,
                    reco_detail.box[2] + 318,
                    reco_detail.box[3] + 50,
                ]
                # 识别并记录数字
                reco_detail = context.run_recognition(
                    "SailingRecordFindNormal",
                    argv.image,
                    {"SailingRecordFindNormal": {"roi": box, "only_rec": False}},
                )
                text = reco_detail.best_result.text
                # 提取数字，支持负数
                match = re.search(r"(-?\d+)\s*~\s*(-?\d+)", text)
                if match:
                    num1, num2 = int(match.group(1)), int(match.group(2))
                SailingRecordSelectTarget.min = num1
                SailingRecordSelectTarget.max = num2
                return CustomRecognition.AnalyzeResult(box=box, detail={})
            return CustomRecognition.AnalyzeResult(box=None, detail={})

        # level 0
        if level == 0:
            reco_details = []
            for roi in [[174, 255, 140, 19], [176, 374, 137, 20], [175, 492, 125, 23]]:
                reco_detail = context.run_recognition(
                    "SailingRecordFindNormal",
                    argv.image,
                    {"SailingRecordFindNormal": {"roi": roi}},
                )
                if reco_detail is None or not reco_detail.hit:
                    return CustomRecognition.AnalyzeResult(box=None, detail={})
                reco_details.append(reco_detail)

            diffs, nums = [], []
            for detail in reco_details:
                # text: 所需点数20~25 或 所需点数-3~3 (含负数)
                text = detail.best_result.text
                # 提取数字，支持负数
                match = re.search(r"(-?\d+)\s*~\s*(-?\d+)", text)
                if match:
                    num1, num2 = int(match.group(1)), int(match.group(2))
                    nums.append((num1, num2))
                    diff = num2 - num1
                    diffs.append(diff)
            index = diffs.index(max(diffs))
            SailingRecordSelectTarget.min, SailingRecordSelectTarget.max = nums[index]
            # 扩展 roi 到 click_target
            box = [
                reco_details[index].box[0] - 53,
                reco_details[index].box[1] - 42,
                reco_details[index].box[2] + 226,
                reco_details[index].box[3] + 50,
            ]
            return CustomRecognition.AnalyzeResult(box=box, detail={})

        return CustomRecognition.AnalyzeResult(box=None, detail={})


@AgentServer.custom_recognition("SailingRecordBoatRecord")
class SailingRecordBoatRecord(CustomRecognition):
    """识别选择船队界面中骰子的点数"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        roi = [131, 476, 24, 19]
        dices = []
        for i in range(3):
            points = []
            for j in range(6):
                reco_detail = context.run_recognition(
                    "SailingRecordBoatPointRecord",
                    argv.image,
                    {"SailingRecordBoatPointRecord": {"roi": roi}},
                )
                if reco_detail is None or not reco_detail.hit:
                    return CustomRecognition.AnalyzeResult(box=None, detail={})
                point = reco_detail.best_result.text
                point = 0 if point in ["?", "？"] else point
                points.append(int(point))
                roi = [roi[0] + 47, roi[1], roi[2], roi[3]]
            dices.append(points)
            roi = [roi[0] + 100, roi[1], roi[2], roi[3]]
        SailingRecordBoatRecord.dices = dices
        return CustomRecognition.AnalyzeResult(box=[0, 0, 0, 0], detail={})
