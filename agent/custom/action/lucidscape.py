import re
import time
import json

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


@AgentServer.custom_action("LucidscapeStageSelect")
class LucidscapeStageSelect(CustomAction):
    """
    醒梦域界面，选择最新可进入片段
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.post_screencap().wait().get()

        # Stage1-Stage4
        roi_list = [
            [221, 510, 95, 22],
            [644, 542, 95, 22],
            [486, 272, 95, 22],
            [982, 410, 95, 22],
        ]

        stage = 1
        for roi in roi_list:
            logger.debug(f"stage: {stage}")
            if stage == 1 or stage == 2:
                max = 200
            else:
                max = 150
            reco_detail = context.run_recognition(
                "LucidscapeStageLocked",
                img,
                {"LucidscapeStageLocked": {"expected": f"\\d/{max}", "roi": roi}},
            )
            if reco_detail is None or not reco_detail.hit:
                return CustomAction.RunResult(success=False)
            pattern = f"(\\d{{1,3}})/{max}"
            text = reco_detail.best_result.text
            logger.debug(f"text: {text}")
            match = re.search(pattern, text)
            if match:
                score = match.group(1)
                score = int(score)
                logger.debug(f"score: {score}")
                if score <= max - 80:
                    break
            stage += 1

        if stage == 5:
            stage = 4

        logger.info(f"当前解锁片段{stage}，准备进入")

        context.tasker.controller.post_click(
            int(roi[0] + roi[2] / 2), int(roi[1] + roi[3] / 2)
        ).wait()
        context.override_pipeline(
            {"LucidscapeStatusDetect": {"custom_action_param": {"stage": stage}}}
        )
        time.sleep(3)

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("LucidscapeStatusDetect")
class LucidscapeStatusDetect(CustomAction):
    """
    醒梦域片段界面，通过检测当前状态决定后续动作

    参数格式：
    {
        "stage": "所处深眠片段"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        stage = json.loads(argv.custom_action_param)["stage"]

        time.sleep(3)
        img = context.tasker.controller.post_screencap().wait().get()

        # Finish
        reco_detail = context.run_recognition("LucidscapeFinish", img)
        if reco_detail and reco_detail.hit:
            logger.info(f"醒梦片段·{self._int2RomanNumeral(stage)}已完成")
            logger.info("领取本层酬劳")
            if stage == 4:
                context.override_next("FlagInLucidscape", ["LucidscapeTotalAwards"])
            context.override_next("LucidscapeStatusDetect", ["LucidscapeAwards"])
            return CustomAction.RunResult(success=True)

        # StageFlag01~02
        context.override_pipeline(
            {
                "LucidscapeStatusDetect": {
                    "next": ["LucidscapeCombatStartFlag"],
                    "interrupt": ["CombatEntering"],
                    "custom_action_param": {"stage": stage},
                }
            }
        )

        # StageFlag02
        reco_detail = context.run_recognition("LucidscapeStageFlag02", img)
        if reco_detail and reco_detail.hit:
            context.tasker.controller.post_click(990, 300).wait()
            context.override_next(
                "LucidscapeCombatStartFlag", ["LucidscapeTeamSelect_2"]
            )
            logger.info("进入当前片段下半")
            return CustomAction.RunResult(success=True)

        # StageFlag01
        reco_detail = context.run_recognition("LucidscapeStageFlag01", img)
        if reco_detail and reco_detail.hit:
            context.tasker.controller.post_click(320, 445).wait()
            context.override_next(
                "LucidscapeCombatStartFlag", ["LucidscapeTeamSelect_1"]
            )
            logger.info("进入当前片段上半")
            return CustomAction.RunResult(success=True)

        return CustomAction.RunResult(success=False)

    def _int2RomanNumeral(self, num: int) -> str:
        RomanNumerals = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]
        return RomanNumerals[num - 1]
