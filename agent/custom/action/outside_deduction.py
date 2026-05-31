import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import is_hit, ocr_text
from utils.params import parse_params


@AgentServer.custom_action("SOD_DifficultySelect")
class SOD_DifficultySelect(CustomAction):
    """
    黄昏的音序难度选择

    参数格式:
    {
        "level": "5,10,11,cur,max"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        level = parse_params(argv.custom_action_param, "level")["level"]

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("SOD_CurrentLevel", img)
        if not is_hit(reco_detail):
            return CustomAction.RunResult(success=False)
        cur = int(ocr_text(reco_detail))

        if level == "cur":
            logger.info(f"选定当前难度 {cur}")
            context.override_pipeline(
                {"ODR_FlagInDifficultySelect": {"enabled": False}}
            )
            return CustomAction.RunResult(success=True)
        elif level in {"5", "10", "11"}:
            level = int(level)
            if cur > level:
                delta = cur - level
                for _i in range(delta):
                    context.tasker.controller.post_click(20, 360).wait()
                    time.sleep(0.5)
            else:
                delta = level - cur
                for _i in range(delta):
                    context.tasker.controller.post_click(1260, 360).wait()
                    time.sleep(0.5)
        else:
            # max
            # level 20
            if cur == 20:
                logger.info(f"选定当前难度 {cur}")
                context.override_pipeline(
                    {"ODR_FlagInDifficultySelect": {"enabled": False}}
                )
                return CustomAction.RunResult(success=True)

            # To Locked Level
            img = context.tasker.controller.post_screencap().wait().get()
            reco_detail = context.run_recognition("SOD_LevelLocked", img)

            while not is_hit(reco_detail):
                context.tasker.controller.post_click(1260, 360).wait()
                time.sleep(0.5)
                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition("SOD_LevelLocked", img)

            # To UnLocked Level
            while is_hit(reco_detail):
                context.tasker.controller.post_click(20, 360).wait()
                time.sleep(0.5)
                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition("SOD_LevelLocked", img)

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("SOD_CurrentLevel", img)
        if not is_hit(reco_detail):
            return CustomAction.RunResult(success=False)
        cur = int(ocr_text(reco_detail))

        context.override_pipeline({"ODR_FlagInDifficultySelect": {"enabled": False}})
        logger.info(f"选定难度 {cur}")

        return CustomAction.RunResult(success=True)
