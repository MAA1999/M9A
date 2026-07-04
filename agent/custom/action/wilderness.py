import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import is_hit, ocr_text


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

        if not is_hit(reco_first) or not is_hit(reco_last) or reco_first.box is None or reco_last.box is None:
            return CustomAction.RunResult(success=True)
        x1, y1, x2, y2 = (
            int(reco_first.box[0] + reco_first.box[2] / 2),
            int(reco_first.box[1] + reco_first.box[3] / 2),
            int(reco_last.box[0] + reco_last.box[2] / 2),
            int(reco_last.box[1] + reco_last.box[3] / 2),
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

        cans = int(ocr_text(reco_detail).split("/")[0])

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

        hours = int(ocr_text(reco_detail))

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
