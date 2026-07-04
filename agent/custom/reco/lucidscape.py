import re

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import logger
from utils.maa_types import is_hit, ocr_text


@AgentServer.custom_recognition("LucidscapeStageSelect")
class LucidscapeStageSelect(CustomRecognition):
    """
    醒梦域界面，识别最新可进入片段。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:
        # Stage1-Stage4
        roi_list = [
            [221, 510, 95, 22],
            [644, 542, 95, 22],
            [486, 272, 95, 22],
            [982, 410, 95, 22],
        ]

        stage = 1
        target_roi = roi_list[-1]
        for roi in roi_list:
            max_score = 200 if stage == 1 or stage == 2 else 150
            reco_detail = context.run_recognition(
                "LucidscapeStageLocked",
                argv.image,
                {
                    "LucidscapeStageLocked": {
                        "expected": f"\\d/{max_score}",
                        "roi": roi,
                    }
                },
            )
            if not is_hit(reco_detail):
                return CustomRecognition.AnalyzeResult(box=None, detail={})

            logger.debug(f"stage: {stage}")
            target_roi = roi
            pattern = f"(\\d{{1,3}})/{max_score}"
            text = ocr_text(reco_detail)
            logger.debug(f"text: {text}")
            match = re.search(pattern, text)
            if match:
                score = int(match.group(1))
                logger.debug(f"score: {score}")
                if score <= max_score - 80:
                    break
            stage += 1

        if stage == 5:
            stage = 4

        logger.info(f"当前解锁片段{stage}，准备进入")
        context.override_pipeline(
            {"LucidscapeStatusDetect": {"custom_action_param": {"stage": stage}}}
        )

        return CustomRecognition.AnalyzeResult(box=target_roi, detail={"stage": stage})
