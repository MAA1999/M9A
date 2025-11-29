from typing import Union, Optional

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType

from utils import logger


@AgentServer.custom_recognition("StagePromotionComplete")
class StagePromotionComplete(CustomRecognition):
    """
    推图模式完成判断（当前关为满星且无下一关）
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        cur_flag = False
        # 轶事
        reco_detail = context.run_recognition(
            "StagePromotionCurStageComplete", argv.image
        )
        # 故事模式
        reco_detail1 = context.run_recognition(
            "StagePromotionCurStageComplete1", argv.image
        )
        # 探索模式
        reco_detail2 = context.run_recognition(
            "StagePromotionCurStageComplete2", argv.image
        )
        if reco_detail and reco_detail.hit:
            if reco_detail.best_result:
                cur_flag = True
        if reco_detail1 and reco_detail1.hit:
            if reco_detail1.best_result:
                cur_flag = True
        if reco_detail2 and reco_detail2.hit:
            if reco_detail2.best_result:
                cur_flag = True

        if cur_flag:
            reco_detail = context.run_recognition(
                "StagePromotionClickNextStage", argv.image
            )
            if reco_detail and reco_detail.hit:
                if not reco_detail.best_result:
                    return [0, 0, 0, 0]
            else:
                return [0, 0, 0, 0]
        return None
