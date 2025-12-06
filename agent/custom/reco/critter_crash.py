import json
import time
from typing import Union, Optional, cast, Any

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType, OCRResult
import numpy as np

from utils import logger
from custom.action.critter_crash import CCChessboard


@AgentServer.custom_recognition("CCBuyCard")
class CCBuyCardRec(CustomRecognition):
    """
    翻斗棋：识别可购买卡牌

    如果判断需要后续进行购买，则识别成功，此时 box 返回卡牌位置， detail 返回 1.购买类型：奖励区/粘贴处 2.附带卡牌后续操作（部署/升级/卖出）
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        # 检查奖励框是否为空
        reco_detail = context.run_recognition("CCBuyCardAwardEmptyRec", argv.image)
        if reco_detail and reco_detail.hit:
            # 识别到奖励框不为空
            for chess_info in CCChessboard.chess_types:
                card_name = chess_info["name"]
                reco_detail1 = context.run_recognition(
                    "CCBuyCardAwardRec_Template",
                    argv.image,
                    {
                        "CCBuyCardAwardRec_Template": {
                            "template": f"CritterCrash/Cards/{card_name}.png"
                        }
                    },
                )
                if reco_detail1 and reco_detail1.hit:
                    # 识别到目标卡片，查询是否可部署/能升级的棋子，有则进行
                    if CCChessboard.find_empty_position(card_name):
                        detail = {"type": 1, "action": 0, "name": card_name}
                        return CustomRecognition.AnalyzeResult(
                            box=reco_detail1.box, detail=detail
                        )
                    elif CCChessboard.can_upgrade_existing(card_name):
                        detail = {"type": 1, "action": 1, "name": card_name}
                        return CustomRecognition.AnalyzeResult(
                            box=reco_detail1.box, detail=detail
                        )
                    else:
                        # 无法部署或升级，卖掉
                        detail = {"type": 1, "action": 2, "name": card_name}
                        context.run_task("CCStartCombat")
                        return CustomRecognition.AnalyzeResult(box=None, detail=detail)
            # 无法识别奖励框内的卡牌，默认卖掉
            # 分辨卡牌类型
            reco_detail = context.run_recognition(
                "CCBuyCardAwardTypeRec_Template", context.tasker.controller.cached_image
            )
            if reco_detail and reco_detail.hit:
                # 识别到模板，判断不是藏品
                name = "unknown_2"
            else:
                # 藏品
                name = "unknown_1"
            # 查询是否有空位，有则购买后卖掉
            if CCChessboard.find_empty_position(name):
                detail = {"type": 1, "action": 2, "name": name}
                return CustomRecognition.AnalyzeResult(
                    box=[81, 618, 52, 55], detail=detail
                )
            return CustomRecognition.AnalyzeResult(box=None, detail={})
        else:
            # 奖励框为空，检查剩余缪斯币是否足够购买
            reco_detail = context.run_recognition("CCRemainMoney", argv.image)
            if reco_detail and reco_detail.hit:
                # 钱够了
                pass
            else:
                # 不够，退出
                logger.debug("当前剩余缪斯币不足")
                return CustomRecognition.AnalyzeResult(box=None, detail={})
            # 钱够了，先动态识别所有可能的卡牌，然后根据优先级选择
            upgrade_candidates = []
            for chess_info in CCChessboard.chess_types:
                card_name = chess_info["name"]
                # 动态识别当前卡牌
                reco_detail = context.run_recognition(
                    "CCBuyCardRec_Template",
                    argv.image,
                    {
                        "CCBuyCardRec_Template": {
                            "template": f"CritterCrash/Cards/{card_name}.png"
                        }
                    },
                )
                if reco_detail and reco_detail.hit:
                    # 识别成功，检查是否有空位
                    if CCChessboard.find_empty_position(card_name):
                        # 有空位，直接返回
                        logger.debug(f"找到有空位的卡牌: {card_name}")
                        detail = {"type": 0, "action": 0, "name": card_name}
                        return CustomRecognition.AnalyzeResult(
                            box=reco_detail.box, detail=detail
                        )
                    # 没有空位，检查是否能升级
                    elif CCChessboard.can_upgrade_existing(card_name):
                        # 能升级，记录为候选
                        upgrade_candidates.append((reco_detail, card_name))

            # 如果有升级候选，返回第一个
            if upgrade_candidates:
                reco_detail, card_name = upgrade_candidates[0]
                logger.debug(f"选择能升级的卡牌: {card_name}")
                detail = {"type": 0, "action": 1, "name": card_name}
                return CustomRecognition.AnalyzeResult(
                    box=reco_detail.box, detail=detail
                )

            # 没有找到合适的卡牌
            logger.debug("没有找到合适的卡牌")
            return CustomRecognition.AnalyzeResult(box=None, detail={})


@AgentServer.custom_recognition("CCRemainMoney")
class CCRemainMoney(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        img = argv.image
        # 定义目标颜色和颜色容差
        target_color = np.array([215, 241, 249])
        tolerance = 55  # 颜色容差，可以根据需要调整

        # 创建颜色过滤掩码
        lower_bound = np.maximum(target_color - tolerance, 0)
        upper_bound = np.minimum(target_color + tolerance, 255)

        # 创建掩码：保留在目标颜色范围内的像素
        color_mask = np.all((img >= lower_bound) & (img <= upper_bound), axis=-1)

        # 处理图像：保留目标颜色，其他颜色变成黑色
        processed_img = np.where(color_mask[..., None], img, 0).astype(np.uint8)

        reco_detail = context.run_recognition("CCRemainMoney_rec", processed_img)

        if reco_detail and reco_detail.hit:
            logger.debug(f"识别到剩余缪斯币: {reco_detail.best_result.text}")
            if int(reco_detail.best_result.text) >= 3:
                return CustomRecognition.AnalyzeResult(
                    box=reco_detail.box, detail=reco_detail.raw_detail
                )
        return CustomRecognition.AnalyzeResult(box=None, detail={})
