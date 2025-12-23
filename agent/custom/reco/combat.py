import re
from typing import Any, Dict, Union, Optional

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType

from utils import logger


def parse_valid_period_to_hours(text: str) -> float:
    """
    解析有效期文本，转换为小时数。
    支持格式："X分钟"、"X小时"、"X天"
    如果只有数字没有单位，默认当作分钟处理
    返回 -1 表示无限期或无法解析
    """
    if not text:
        return -1

    # 匹配数字
    match = re.search(r"(\d+)", text)
    if not match:
        return -1
    num = int(match.group(1))

    if "分钟" in text or "分" in text:
        return num / 60.0
    elif "小时" in text or "时" in text:
        return float(num)
    elif "天" in text:
        # 游戏内显示"X天"实际上表示剩余时间超过 X*24 小时
        # 例如"1天"可能是25小时、30小时等，为了正确判断需要略大于 X*24
        return num * 24.0 + 0.1
    else:
        # 无法识别，可能是无限期
        return -1


def get_valid_period_threshold(period_option: str) -> float:
    """
    根据用户选择的有效期选项，返回对应的小时数阈值。
    24h -> 24小时
    7d -> 168小时
    14d -> 336小时
    infinite -> -1（只吃无限期的）
    """
    thresholds = {
        "24h": 24.0,
        "7d": 7 * 24.0,
        "14d": 14 * 24.0,
        "infinite": -1,
    }
    return thresholds.get(period_option, 24.0)


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


@AgentServer.custom_recognition("CandyPageRecord")
class CandyPageRecord(CustomRecognition):
    """
    糖果页面记录当前糖果数量，并根据用户设置的有效期判断要吃哪些糖。

    糖果类型：
    - MiniCandy（小熊糖）：每次5活性，需要全部吃完
    - OverflowCandy（苦目糖）：单次使用
    - SmallCandy（小糖）：单次使用
    - BigCandy（大糖）：单次使用

    有效期格式："X分钟"、"X小时"、"X天"
    """

    # 糖果名称列表（顺序对应下面的 ROI 列表）
    candy_names = ["MiniCandy", "OverflowCandy", "SmallCandy", "BigCandy"]

    # 数量识别区域
    count_rois = [
        [1052, 322, 36, 24],  # 小熊糖
        [456, 128, 36, 24],  # 苦目糖
        [885, 204, 36, 24],  # 小糖
        [933, 542, 36, 24],  # 大糖
    ]

    # 有效期识别区域
    valid_period_rois = [
        [1030, 364, 78, 49],
        [451, 177, 59, 31],
        [904, 270, 68, 31],
        [936, 609, 71, 31],
    ]

    # 点击区域（与 eat_candy.json 中的 EatXxxCandy 节点 roi 对应）
    click_rois = [
        [1045, 272, 28, 25],  # 小熊糖
        [457, 80, 28, 26],  # 苦目糖
        [889, 149, 28, 26],  # 小糖
        [941, 486, 27, 26],  # 大糖
    ]

    # 各糖果每次恢复的活性值
    candy_restore_values = {
        "MiniCandy": 5,  # 小熊糖每次5活性
        "OverflowCandy": 60,  # 苦目糖
        "SmallCandy": 60,  # 小糖
        "BigCandy": 120,  # 大糖
    }

    candies = {"MiniCandy": {}, "OverflowCandy": {}, "SmallCandy": {}, "BigCandy": {}}

    # 非快速模式下，记录是否已经吃过一次糖
    _has_eaten_once = False
    # 记录上次各糖果数量，用于验证是否真的吃了
    _last_candy_counts: Dict[str, int] = {}

    @classmethod
    def reset_eaten_flag(cls):
        """重置吃糖标记（由 ResetEatCandyFlag action 调用）"""
        cls._has_eaten_once = False
        cls._last_candy_counts = {}
        logger.debug("已重置吃糖标记")

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        # 先确认在吃糖界面
        reco_detail = context.run_recognition("EatCandyPage", argv.image)
        if not reco_detail or not reco_detail.hit:
            return None

        # 获取当前体力及上限（默认值：体力0，上限240）
        remaining_ap = 0
        max_ap = 240

        reco_remaining = context.run_recognition(
            "CandyRecognizeRemainingAp", argv.image
        )
        if reco_remaining and reco_remaining.hit:
            best = getattr(reco_remaining, "best_result", None)
            if best:
                text = getattr(best, "text", "")
                digits = "".join(ch for ch in (text or "") if ch.isdigit())
                if digits:
                    remaining_ap = int(digits)

        reco_max = context.run_recognition("CandyRecognizeMaxAp", argv.image)
        if reco_max and reco_max.hit:
            best = getattr(reco_max, "best_result", None)
            if best:
                text = getattr(best, "text", "")
                digits = "".join(ch for ch in (text or "") if ch.isdigit())
                if digits:
                    max_ap = int(digits)

        recorded_candies: Dict[str, Dict[str, Any]] = {
            name: {"index": idx} for idx, name in enumerate(self.candy_names)
        }

        # 记录各糖果当前有效期，以及数量
        for idx, count_roi in enumerate(self.count_rois):
            candy_name = self.candy_names[idx]
            # 识别数量
            reco_detail = context.run_recognition(
                "EatCandyPageCountRecord",
                argv.image,
                {"EatCandyPageCountRecord": {"roi": count_roi}},
            )

            count = 0
            best_result = (
                getattr(reco_detail, "best_result", None) if reco_detail else None
            )
            if reco_detail and reco_detail.hit and best_result:
                text_attr = getattr(best_result, "text", "")
                raw_text = (text_attr or "").strip()
                digits = "".join(ch for ch in raw_text if ch.isdigit())
                if digits:
                    count = int(digits)

            recorded_candies[candy_name]["count"] = count

            # 识别有效期
            reco_detail1 = context.run_recognition(
                "EatCandyPageValidPeriodRecord",
                argv.image,
                {"EatCandyPageValidPeriodRecord": {"roi": self.valid_period_rois[idx]}},
            )
            best_result = (
                getattr(reco_detail1, "best_result", None) if reco_detail1 else None
            )
            valid_period_text = ""
            if reco_detail1 and reco_detail1.hit and best_result:
                text_attr = getattr(best_result, "text", "")
                valid_period_text = (text_attr or "").strip()

            recorded_candies[candy_name]["valid_period_text"] = valid_period_text
            recorded_candies[candy_name]["valid_period_hours"] = (
                parse_valid_period_to_hours(valid_period_text)
            )

        # 获取用户设置
        node_obj = context.get_node_object("EatCandyStart")
        attach = getattr(node_obj, "attach", {}) if node_obj else {}
        user_period_option = attach.get("valid_period", "24h") if attach else "24h"
        fast_mode = attach.get("fast", 0) if attach else 0  # 快速吃糖模式
        threshold_hours = get_valid_period_threshold(user_period_option)

        # 计算可恢复的体力空间
        ap_space = max_ap - remaining_ap

        logger.debug(
            f"用户设置：有效期={user_period_option}, 阈值={threshold_hours}小时, "
            f"快速模式={fast_mode}"
        )
        logger.debug(f"当前体力：{remaining_ap}/{max_ap}, 可恢复空间：{ap_space}")

        # 快速模式：体力已满则不吃糖
        if fast_mode == 1 and ap_space <= 0:
            logger.debug("快速模式：体力已满，跳过吃糖")
            return None

        # 非快速模式：检查是否已经吃过糖
        if fast_mode == 0 and CandyPageRecord._has_eaten_once:
            # 获取当前各糖果数量
            current_counts = {
                name: recorded_candies[name].get("count", 0)
                for name in self.candy_names
            }
            # 比较数量是否有变化（排除 MiniCandy，因为它由单独节点处理）
            counts_changed = False
            for name in ["OverflowCandy", "SmallCandy", "BigCandy"]:
                last_count = CandyPageRecord._last_candy_counts.get(name, -1)
                curr_count = current_counts.get(name, 0)
                if last_count != -1 and curr_count < last_count:
                    counts_changed = True
                    logger.debug(f"{name} 数量变化：{last_count} -> {curr_count}")
                    break

            if counts_changed:
                # 数量确实减少了，说明吃糖成功，跳过
                logger.debug("非快速模式：已吃过一次糖，跳过")
                return None
            else:
                # 数量没变，说明上次吃糖失败，重置标记重试
                logger.warning("非快速模式：上次吃糖未生效，重试")
                CandyPageRecord._has_eaten_once = False

        # 判断每种糖是否符合吃的条件
        # 规则：小熊糖由 EatMiniCandy 单独处理，这里只处理其他糖，按顺序最多吃一个
        candies_to_eat = []
        found_candy = False  # 是否已找到符合条件的糖

        for candy_name in self.candy_names:
            candy_info = recorded_candies[candy_name]
            idx = candy_info["index"]
            count = candy_info.get("count", 0)
            period_hours = candy_info.get("valid_period_hours", -1)

            # 存储点击区域
            candy_info["click_roi"] = self.click_rois[idx]

            # 小熊糖由 EatMiniCandy 节点单独处理，这里跳过
            if candy_name == "MiniCandy":
                candy_info["should_eat"] = False
                candy_info["eat_count"] = 0
                continue

            if count <= 0:
                candy_info["should_eat"] = False
                candy_info["eat_count"] = 0
                continue

            should_eat = False
            if user_period_option == "infinite":
                # 选择无限期：只吃无限期的糖（period_hours == -1 表示无限期）
                should_eat = period_hours == -1
            else:
                # 选择有时限的：吃有效期在阈值内的糖
                if period_hours > 0 and period_hours <= threshold_hours:
                    should_eat = True

            # 已有符合条件的糖，不再添加
            if should_eat and found_candy:
                should_eat = False

            candy_info["should_eat"] = should_eat

            if should_eat:
                candy_info["eat_count"] = 1
                candy_info["total_restore"] = self.candy_restore_values.get(
                    candy_name, 60
                )
                candy_info["counts_as_eat"] = True
                found_candy = True
                candies_to_eat.append(candy_name)
            else:
                candy_info["eat_count"] = 0

        CandyPageRecord.candies = recorded_candies

        logger.debug(f"吃糖页面糖果记录：{recorded_candies}")
        logger.debug(f"符合条件的糖果：{candies_to_eat}")

        # 如果没有符合条件的糖，返回 None（让流水线跳到下一个节点）
        if not candies_to_eat:
            logger.debug("没有符合条件的糖果")
            return None

        # 取第一个要吃的糖
        current_candy_name = candies_to_eat[0]
        current_candy_info = recorded_candies[current_candy_name]
        current_idx = current_candy_info["index"]

        # 检查要吃的糖的恢复体力是否超过可恢复空间
        total_restore = current_candy_info["total_restore"]
        if total_restore > ap_space:
            logger.debug(
                f"糖果 {current_candy_name} 恢复体力 {total_restore} 超过可恢复空间 {ap_space}，跳过吃糖"
            )
            return None

        # 非快速模式：标记已吃过一次糖，并记录当前数量
        if fast_mode == 0:
            CandyPageRecord._has_eaten_once = True
            CandyPageRecord._last_candy_counts = {
                name: recorded_candies[name].get("count", 0)
                for name in self.candy_names
            }

        return CustomRecognition.AnalyzeResult(
            box=self.click_rois[current_idx],
            detail={
                "candies": recorded_candies,
                "candies_to_eat": candies_to_eat,
                # 当前要吃的糖的详细信息
                "current_candy": {
                    "name": current_candy_name,
                    "index": current_idx,
                    "click_roi": self.click_rois[current_idx],
                    "count": current_candy_info["count"],
                    "eat_count": current_candy_info["eat_count"],
                    "total_restore": current_candy_info["total_restore"],
                },
                "user_period_option": user_period_option,
                "fast_mode": fast_mode,
                "remaining_ap": remaining_ap,
                "max_ap": max_ap,
                "ap_space": ap_space,
            },
        )
