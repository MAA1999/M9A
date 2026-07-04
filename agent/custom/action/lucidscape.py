import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import is_hit
from utils.params import parse_params


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

        stage = parse_params(argv.custom_action_param, "stage")["stage"]

        time.sleep(3)
        img = context.tasker.controller.post_screencap().wait().get()

        # Finish
        reco_detail = context.run_recognition("LucidscapeFinish", img)
        if is_hit(reco_detail):
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
                    "next": ["LucidscapeCombatStartFlag", "[JumpBack]CombatEntering"],
                    "custom_action_param": {"stage": stage},
                }
            }
        )

        # StageFlag02
        reco_detail = context.run_recognition("LucidscapeStageFlag02", img)
        if is_hit(reco_detail):
            context.tasker.controller.post_click(990, 300).wait()
            context.override_next("LucidscapeCombatStartFlag", ["LucidscapeTeamSelect_2"])
            logger.info("进入当前片段下半")
            return CustomAction.RunResult(success=True)

        # StageFlag01
        reco_detail = context.run_recognition("LucidscapeStageFlag01", img)
        if is_hit(reco_detail):
            context.tasker.controller.post_click(320, 445).wait()
            context.override_next("LucidscapeCombatStartFlag", ["LucidscapeTeamSelect_1"])
            logger.info("进入当前片段上半")
            return CustomAction.RunResult(success=True)

        return CustomAction.RunResult(success=False)

    def _int2RomanNumeral(self, num: int) -> str:
        RomanNumerals = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]
        return RomanNumerals[num - 1]
