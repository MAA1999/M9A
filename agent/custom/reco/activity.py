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

        if reco_detail is None:
            return CustomRecognition.AnalyzeResult(box=None, detail="无文字")

        for result in reco_detail.all_results:
            if expected in result.text:
                return CustomRecognition.AnalyzeResult(box=result.box, detail=expected)

        return CustomRecognition.AnalyzeResult(box=None, detail="无目标")

   
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
    EASY_COORDS = [
        (449, 139, 61, 57),
        (931, 178, 66, 53),
        (613, 410, 66, 55),
    ]

    NORMAL_HARD_COORDS = [
        (403, 143, 62, 56),
        (1037, 143, 61, 60),
        (378, 449, 58, 56),
        (957, 477, 63, 60),
        (758, 227, 63, 52),
    ]

    PREFIX = {
        "Easy": "日常第",
        "Normal": "中等第",
        "Hard": "高难第"
    }

    def get_stage_list(self, difficulty: str) -> List[Dict[str, Any]]:
        if difficulty == "Easy":
            coords = self.EASY_COORDS
        elif difficulty in ("Normal", "Hard"):
            coords = self.NORMAL_HARD_COORDS
        else:
            return []
        
        prefix = self.PREFIX.get(difficulty, difficulty)
        return [
            {
                "id": f"{prefix}{i + 1}关",
                "checkmark_roi": [x, y, w, h],
                "click_target": [x - 30, y + 30, w, h]
            }
            for i, (x, y, w, h) in enumerate(coords)
        ]

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        params = json.loads(argv.custom_recognition_param)
        difficulty = params.get("difficulty", "Normal")
        mode = params.get("mode", "Normal")

        stages = self.get_stage_list(difficulty)
        if not stages:
            logger.error(f"[Checkmark] 无效难度: '{difficulty}'。")
            return None

        checkmark_node_name = params.get("template_node_name", "Alarm_FindStageFlag")
        targets = [stages[-1]] if mode == "Quickly" else stages if mode == "Normal" else []

        if not targets:
            logger.error(f"[Checkmark] 无效模式: '{mode}'。")
            return None

        for stage in targets:
            sid = stage["id"]
            roi = stage["checkmark_roi"]
            click = stage["click_target"]

            logger.info(f"[Checkmark] 检查 '{sid}' 区域 {roi}。")
            result = context.run_recognition(
                checkmark_node_name,
                argv.image,
                pipeline_override={checkmark_node_name: {"roi": roi}}
            )

            if result is not None:
                logger.info(f"[Checkmark] '{sid}' 已通关。")
                if mode == "Quickly":
                    return None
                continue
            else:
                logger.info(f"[Checkmark] '{sid}' 未通关，返回点击区域 {click}。")
                return CustomRecognition.AnalyzeResult(
                    box=click,
                    detail=f"Unplayed stage '{sid}' (Diff: {difficulty}, Mode: {mode})"
                )

        logger.info(f"[Checkmark] 所有关卡已通关。")
        return None