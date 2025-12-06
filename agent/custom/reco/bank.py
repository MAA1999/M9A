import json
from typing import Union, Optional

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType

from utils import logger


@AgentServer.custom_recognition("BankShop")
class BankShop(CustomRecognition):
    """
    在8个商品内容中寻找结果

    参数格式:
    {
        "expected" : "商品名称",
        "inverse": "是否反转，默认 false"
    }

    返回结果:
    识别范围
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        data = json.loads(argv.custom_recognition_param)
        expected = data.get("expected")
        inverse = data.get("inverse", False)

        img = context.tasker.controller.post_screencap().wait().get()

        roi_list = [
            [325, 286, 93, 30],
            [568, 284, 93, 30],
            [798, 286, 107, 28],
            [1047, 285, 93, 30],
            [327, 547, 93, 30],
            [566, 546, 93, 30],
            [806, 546, 93, 30],
            [1046, 547, 93, 30],
        ]

        for roi in roi_list:
            try:
                reco_detail = context.run_recognition(
                    "BankShopTemplate",
                    img,
                    {"BankShopTemplate": {"roi": roi, "expected": expected}},
                )

                if reco_detail and reco_detail.hit:
                    if inverse:
                        return None
                    return reco_detail.box
            except Exception as e:
                logger.warning(f"Recognition error: {e}")
                continue

        if inverse:
            return [0, 0, 0, 0]
        return None
