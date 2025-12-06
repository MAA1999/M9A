import time

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


@AgentServer.custom_action("SummonlngSwipe")
class SummonlngSwipe(CustomAction):
    """
    分派魔精滑动名片。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.post_screencap().wait().get()

        reco_first = context.run_recognition("SummonlngCardFirst", img)
        reco_last = context.run_recognition("SummonlngCardLast", img)

        if (
            reco_first is None
            or not reco_first.hit
            or reco_last is None
            or not reco_last.hit
        ):
            return CustomAction.RunResult(success=True)
        x1, y1, x2, y2 = (
            int(reco_first.best_result.box[0] + reco_first.best_result.box[2] / 2),
            int(reco_first.best_result.box[1] + reco_first.best_result.box[3] / 2),
            int(reco_last.best_result.box[0] + reco_last.best_result.box[2] / 2),
            int(reco_last.best_result.box[1] + reco_last.best_result.box[3] / 2),
        )
        context.tasker.controller.post_swipe(x1, y1, x2, y2, duration=1000).wait()

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("GoodDreamWellFishing")
class GoodDreamWellFishing(CustomAction):
    """
    好梦井打捞。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.post_screencap().wait().get()

        reco_detail = context.run_recognition("GoodDreamWellOCR", img)

        cans = int(reco_detail.best_result.text.split("/")[0])

        reco_detail = context.run_recognition(
            "GoodDreamWellOCR",
            img,
            {
                "GoodDreamWellOCR": {
                    "roi": [4, 161, 236, 26],
                    "expected": "\\d",
                    "replace": [["距好梦井馈赠更新", ""], ["[:：]", ""], ["小时", ""]],
                }
            },
        )

        hours = int(reco_detail.best_result.text)

        if hours >= 16 and cans >= 4:
            index = 3
        elif hours >= 12 and cans >= 3:
            index = 2
        elif hours >= 8 and cans >= 2:
            index = 1
        elif hours >= 4 and cans >= 1:
            index = 0
        else:
            logger.info("未满足打捞条件")
            context.run_task("BackButton")
            return CustomAction.RunResult(success=True)

        context.run_task(
            "GoodDreamWellOCR",
            {
                "GoodDreamWellOCR": {
                    "recognition": {
                        "type": "OCR",
                        "param": {
                            "roi": [919, 145, 102, 327],
                            "only_rec": False,
                            "expected": "打捞",
                            "order_by": "Vertical",
                            "index": index,
                        },
                    }
                }
            },
        )
        time.sleep(1)
        context.run_task("BackButton")
        return CustomAction.RunResult(success=True)
