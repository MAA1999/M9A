import numpy as np
from custom.action.critter_crash import CCChessboard
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils import logger
from utils.maa_types import is_hit, ocr_text
from utils.params import parse_params


@AgentServer.custom_recognition("CCPickLeaderRec")
class CCPickLeaderRec(CustomRecognition):
    """翻斗棋 4.0 选领队：优先策略表指定的棋手 → 退出重摇 → 兜底点第一个卡位。

    为什么不能只兜底：领队决定**卡包**，卡包决定商店的棋子池（`auto_chess_master_library`
    → `auto_chess_cardpack.chessPool`）；鹿蜀流整套（32121–32126）只在部分卡包里，
    随机兜底一选就可能整局买不到鹿蜀，机器人只能空转刷新（实测一局 240s 里刷了 38 次）。
    而**选领队页返回 + 放弃这一局**会重新摇（返回本身没用，放弃那步由 pipeline 的 CCStop 承担，
    见 CritterCrash.json 文件头第 3 条），所以在没摇到优先棋手时可以退出去再摇。

    四道门，任一不成立就返回 miss（交由 pipeline 的 next 继续）：
      1. 策略表有 people 段（3.5 流程不读）；
      2. 当前确实在选领队页（OCR 标题）—— 对局页左侧也画着领队立绘，不做这道门会点错；
      3. 该卡位还没有「已被选中」角标（重复点可能取消选中）；
      4. 有优先棋手立绘就点它；没有且还有重摇额度就点返回键；额度用尽则兜底点 slots[0]。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        people = CCChessboard.strategy.people
        if people is None or not people.slots:
            return CustomRecognition.AnalyzeResult(box=None, detail={})

        # 门 2：不在选领队页就不要给出 box（对局页左侧也是同一张领队立绘）
        flag = context.run_recognition("CCFlagInSelectPeople", argv.image)
        if not is_hit(flag):
            return CustomRecognition.AnalyzeResult(box=None, detail={})

        # 门 4a：优先棋手。模板沿用 pipeline 的命名约定 Leaders_<id>.png；
        # 文件缺失时识别只是 miss，会自然走到重摇或兜底，不会抛错。
        for leader_id in people.preferred:
            reco = context.run_recognition(
                "CCPickLeader_Template",
                argv.image,
                {"CCPickLeader_Template": {"template": f"CritterCrash/Leaders_{leader_id}.png"}},
            )
            if is_hit(reco):
                logger.debug(f"选领队：命中优先棋手 {leader_id}")
                CCChessboard.set_leader(str(leader_id))
                return CustomRecognition.AnalyzeResult(box=reco.box, detail={"leader": leader_id})

        # 门 3：已经选好了就别再动
        for index in range(len(people.slots)):
            badge_roi = people.badge_roi(index)
            if badge_roi is None:
                continue
            reco = context.run_recognition(
                "CCLeaderSelected_Template",
                argv.image,
                {"CCLeaderSelected_Template": {"roi": badge_roi}},
            )
            if is_hit(reco):
                logger.debug(f"选领队：卡位 {index} 已选中，跳过")
                return CustomRecognition.AnalyzeResult(box=None, detail={"selected": index})

        # 门 4b：没摇到优先棋手 —— 还有额度就退出去重摇（返回键），否则兜底点第一个卡位
        if CCChessboard.consume_reroll("leader", people.max_reroll):
            point = people.back_point()
            logger.debug(f"选领队：没有优先棋手，退出重摇（点返回 {point}）")
            return CustomRecognition.AnalyzeResult(box=[point[0] - 5, point[1] - 5, 10, 10], detail={"reroll": True})

        point = people.click_point(0)
        if point is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={})
        logger.debug(f"选领队：重摇额度用尽，兜底点卡位 0 {point}")
        # 兜底 = 不是优先棋手。贴纸按角色专属，领队不对就不能开箱，故显式清空。
        CCChessboard.set_leader(None)
        # box 的中心就是点击点，故用 10x10 的小框包住该点
        return CustomRecognition.AnalyzeResult(box=[point[0] - 5, point[1] - 5, 10, 10], detail={"fallback": True})


@AgentServer.custom_recognition("CCPickEncounterRec")
class CCPickEncounterRec(CustomRecognition):
    """「本次奇遇」弹窗：名字不在白名单就点左上返回，再由 pipeline 放弃这局重开。

    为什么要按奇遇门控：**棋子池由「奇遇 → 卡包」决定**（`auto_chess_master_library`
    → `auto_chess_cardpack.chessPool`），领队只影响技能。实机 20 分钟实测：按「领队=30027」
    重摇 15 次只中 1 次（~7%）；而非目标奇遇的对局是纯浪费 —— 白名单卡一张都不出，
    机器人只能刷新+开战，4 分钟打空场。奇遇名是弹窗上的大号文字，OCR 3/3 命中、负对照 miss。

    重摇是**两步**（2026-10-17 实机修正）：这里点返回只是回到主菜单，**这一局还压着** ——
    再点「箱中对决」会原样回到同一局同名奇遇（连摇 4 次都是「大鱼吃小鱼」）。真正换奇遇
    要靠 pipeline 里的 CCStop：点「箱中对决」右上角的 ✕ 放弃这局 → 清确认框 → 再点「箱中对决」。
    所以这个识别只负责「点返回」，放弃与重开由 pipeline 的 next 链接着走（CCStop → CCRerollConfirm
    → CCStart）。

    返回约定：命中优先棋手那种「要点了才有进展」的语义不适用于这里 ——
      · 名字可接受 / 不在门控范围 / 不在奇遇弹窗 → 返回 miss（交给 pipeline 的 CCNext 翻页）；
      · 名字不可接受且还有额度 → 返回返回键的 box（Click 点它回主菜单，pipeline 接着放弃重开）；
      · 额度用尽 → 返回 miss（认了，直接开打）。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        encounters = CCChessboard.strategy.encounters
        if encounters is None or not encounters.accept:
            return CustomRecognition.AnalyzeResult(box=None, detail={})

        # 门控：必须真在奇遇弹窗上（「下一步」按钮在），否则不要抢别的界面的 next
        if not is_hit(context.run_recognition("CCNext", argv.image)):
            return CustomRecognition.AnalyzeResult(box=None, detail={})

        name = ""
        reco = context.run_recognition("CCEncounterNameRec", argv.image)
        if is_hit(reco):
            name = ocr_text(reco)
        if encounters.accepts(name):
            logger.debug(f"奇遇「{name}」在名单内，直接开打")
            return CustomRecognition.AnalyzeResult(box=None, detail={"encounter": name, "accepted": True})

        if CCChessboard.consume_reroll("encounter", encounters.max_reroll):
            point = encounters.back_point()
            logger.debug(f"奇遇「{name}」不在名单内，退出重摇（点返回 {point}）")
            return CustomRecognition.AnalyzeResult(box=[point[0] - 5, point[1] - 5, 10, 10], detail={"reroll": True})

        logger.debug(f"奇遇「{name}」不在名单内，但重摇额度用尽，直接开打")
        return CustomRecognition.AnalyzeResult(box=None, detail={"encounter": name, "accepted": False})


@AgentServer.custom_recognition("CCBuyCardRec")
class CCBuyCardRec(CustomRecognition):
    """
    翻斗棋：识别可购买卡牌

    如果判断需要后续进行购买，则识别成功，此时 box 返回卡牌位置，
    detail 返回 1.购买类型：奖励区/粘贴处 2.附带卡牌后续操作（部署/升级）

    奖励区认不出或安放不了的卡一律**跳过**（返回 miss），让 pipeline 的 next 走到
    CCStartCombat 开战：4.0 的奖励区卡片拖不动（实测同形态拖商店卡会立刻回「缪斯币不足」、
    拖奖励卡两种形态都零反应），原来的「拖上棋盘再卖掉」整套是空转，见 action 侧 CCBuyCard。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        # 检查奖励框是否为空
        reco_detail = context.run_recognition("CCBuyCardAwardEmptyRec", argv.image)
        if is_hit(reco_detail):
            # 识别到奖励框不为空，按策略表给定的优先级逐个试
            for card_name in CCChessboard.strategy.card_names():
                reco_detail1 = context.run_recognition(
                    "CCBuyCardAwardRec_Template",
                    argv.image,
                    {"CCBuyCardAwardRec_Template": {"template": f"CritterCrash/Cards/{card_name}.png"}},
                )
                if is_hit(reco_detail1):
                    # 识别到目标卡片，查询是否可部署/能升级的棋子，有则进行
                    if CCChessboard.find_empty_position(card_name):
                        detail = {"type": 1, "action": 0, "name": card_name}
                        return CustomRecognition.AnalyzeResult(box=reco_detail1.box, detail=detail)
                    elif CCChessboard.can_upgrade_existing(card_name):
                        detail = {"type": 1, "action": 1, "name": card_name}
                        return CustomRecognition.AnalyzeResult(box=reco_detail1.box, detail=detail)
                    # 既不能部署也不能升级：这张卡用不上，换下一张试
            logger.debug("奖励区的卡认不出或无处安放，跳过（不卖卡）")
            return CustomRecognition.AnalyzeResult(box=None, detail={})
        else:
            # 奖励框为空，检查剩余缪斯币是否足够购买
            reco_detail = context.run_recognition("CCRemainMoney", argv.image)
            if is_hit(reco_detail):
                # 钱够了
                pass
            else:
                # 不够，退出
                logger.debug("当前剩余缪斯币不足")
                return CustomRecognition.AnalyzeResult(box=None, detail={})
            # 钱够了，先动态识别所有可能的卡牌，然后根据优先级选择
            upgrade_candidates = []
            for card_name in CCChessboard.strategy.card_names():
                # 本回合已确认买不动的卡（钱不够/棋盘满/状态分叉）别再反复命中：
                # CCBuyCard 是 [JumpBack]，它每轮都会命中一次，不跳过就会一直空转。
                if CCChessboard.is_buy_skipped(card_name):
                    continue
                # 动态识别当前卡牌
                reco_detail = context.run_recognition(
                    "CCBuyCardRec_Template",
                    argv.image,
                    {"CCBuyCardRec_Template": {"template": f"CritterCrash/Cards/{card_name}.png"}},
                )
                if is_hit(reco_detail):
                    # 识别成功，检查是否有空位
                    if CCChessboard.find_empty_position(card_name):
                        # 有空位，直接返回
                        logger.debug(f"找到有空位的卡牌: {card_name}")
                        detail = {"type": 0, "action": 0, "name": card_name}
                        return CustomRecognition.AnalyzeResult(box=reco_detail.box, detail=detail)
                    # 没有空位，检查是否能升级
                    elif CCChessboard.can_upgrade_existing(card_name):
                        # 能升级，记录为候选
                        upgrade_candidates.append((reco_detail, card_name))

            # 如果有升级候选，返回第一个
            if upgrade_candidates:
                reco_detail, card_name = upgrade_candidates[0]
                logger.debug(f"选择能升级的卡牌: {card_name}")
                detail = {"type": 0, "action": 1, "name": card_name}
                return CustomRecognition.AnalyzeResult(box=reco_detail.box, detail=detail)

            # 没有找到合适的卡牌
            logger.debug("没有找到合适的卡牌")
            return CustomRecognition.AnalyzeResult(box=None, detail={})


@AgentServer.custom_recognition("CCRemainMoney")
class CCRemainMoney(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:

        type = parse_params(argv.custom_recognition_param, "type")["type"]

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
        # 创建一个全黑图像
        processed_img = np.zeros_like(img, dtype=np.uint8)
        # 保留匹配目标颜色的像素
        processed_img[color_mask] = img[color_mask]

        reco_detail = None
        if type == 0:
            reco_detail = context.run_recognition("CCRemainMoney_rec", processed_img)
        elif type == 1:
            reco_detail = context.run_recognition("CCRemainMoney_rec_refresh", processed_img)

        if is_hit(reco_detail):
            money = ocr_text(reco_detail)
            logger.debug(f"识别到剩余缪斯币: {money}")
            if int(money) >= 3:
                return CustomRecognition.AnalyzeResult(box=reco_detail.box, detail=reco_detail.raw_detail)
        return CustomRecognition.AnalyzeResult(box=None, detail={})
