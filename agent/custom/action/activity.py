import os
import time
import json

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from PIL import Image

from utils import logger
from utils import ms_timestamp_diff_to_dhm

from custom.reco.activity import SailingRecordBoatRecord, SailingRecordSelectTarget


@AgentServer.custom_action("DuringAct")
class DuringAct(CustomAction):
    """
    判断当前是否在作战开放期间

    参数格式：
    {
        "resource": "cn/en/jp"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        resource = json.loads(argv.custom_action_param)["resource"]
        DuringAct.resource = resource

        with open(f"resource/data/activity/{resource}.json", encoding="utf-8") as f:
            data = json.load(f)

        now = int(time.time() * 1000)

        for key in reversed(list(data.keys())):
            item = data[key]
            if now < item["activity"]["combat"]["end_time"]:
                if now > item["activity"]["combat"]["start_time"]:
                    # 进行复刻时间判断节点的资源字段覆盖
                    context.override_pipeline(
                        {
                            "JudgeDuringRe_release": {
                                "custom_action_param": {"resource": resource}
                            }
                        }
                    )
                    # 若为主线版本，将 next 设为不可用
                    if item["activity"]["combat"]["event_type"] == "MainStory":
                        context.override_pipeline(
                            {"CombatActivityOverride": {"enabled": False}}
                        )
                        logger.info(f"当前为主线版本：{key} {item['version_name']}")
                        logger.info(
                            f"距离版本结束还剩 {ms_timestamp_diff_to_dhm(now, item['end_time'])}"
                        )
                        logger.info("如果您需要刷取主线关卡，请改用常规作战功能")
                        return CustomAction.RunResult(success=True)
                    logger.info(f"当前版本：{key} {item['version_name']}")
                    logger.info(
                        f"距离作战结束还剩 {ms_timestamp_diff_to_dhm(now, item['activity']['combat']['end_time'])}"
                    )
                    return CustomAction.RunResult(success=True)
                continue
            break

        context.override_next("JudgeDuringAct", [])
        logger.info("当前不在活动时间内，跳过当前任务")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CombatActivityOverride")
class CombatActivityOverride(CustomAction):
    """
    数据中如有override字段，则进行覆盖
    参数格式：
    {
        "mode": 0 | 1
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        mode = json.loads(argv.custom_action_param)["mode"]

        with open(
            f"resource/data/activity/{DuringAct.resource}.json", encoding="utf-8"
        ) as f:
            data = json.load(f)

        now = int(time.time() * 1000)

        for key in reversed(list(data.keys())):
            item = data[key]
            if now < item["activity"]["combat"]["end_time"]:
                if now > item["activity"]["combat"]["start_time"]:
                    if mode == 0 and item["activity"]["combat"].get("override"):
                        context.override_pipeline(
                            item["activity"]["combat"].get("override")
                        )
                    elif mode == 1 and item["activity"]["re-release"].get("override"):
                        context.override_pipeline(
                            item["activity"]["re-release"].get("override")
                        )
                    return CustomAction.RunResult(success=True)

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DuringAnecdote")
class DuringAnecdote(CustomAction):
    """
    判断当前是否在轶事开放期间

    参数格式：
    {
        "resource": "cn/en/jp"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        resource = json.loads(argv.custom_action_param)["resource"]

        with open(f"resource/data/activity/{resource}.json", encoding="utf-8") as f:
            data = json.load(f)

        now = int(time.time() * 1000)

        for key in reversed(list(data.keys())):
            item = data[key]

            if not item["activity"].get("anecdote"):
                continue

            if now < item["activity"]["anecdote"]["end_time"]:
                if now > item["activity"]["anecdote"]["start_time"]:
                    logger.info(f"当前版本：{key} {item['version_name']}")
                    logger.info(
                        f"距离轶事结束还剩 {ms_timestamp_diff_to_dhm(now, item['activity']['anecdote']['end_time'])}"
                    )
                    if item["activity"]["anecdote"].get("override"):
                        context.override_pipeline(
                            item["activity"]["anecdote"].get("override")
                        )
                    return CustomAction.RunResult(success=True)
                continue
            break

        context.override_next("JudgeDuringAnecdote", [])
        logger.info("当前不在轶事开放时间，跳过当前任务")

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DuringRe_release")
class DuringRe_release(CustomAction):
    """
    判断当前是否在版本复刻期间

    参数格式：
    {
        "resource": "cn/en/jp"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        resource = json.loads(argv.custom_action_param)["resource"]

        with open(f"resource/data/activity/{resource}.json", encoding="utf-8") as f:
            data = json.load(f)

        now = int(time.time() * 1000)

        for key in reversed(list(data.keys())):
            item = data[key]
            if item["activity"].get("re-release"):
                if now < item["activity"]["re-release"]["end_time"]:
                    if now > item["activity"]["re-release"]["start_time"]:
                        logger.info(
                            f"当前复刻活动：{item['activity']['re-release']['name']}"
                        )
                        logger.info(
                            f"距离复刻作战结束还剩 {ms_timestamp_diff_to_dhm(now, item['activity']['re-release']['end_time'])}"
                        )
                        # 当前为合法复刻作战时间，且复刻模式开启，进行相关覆盖
                        context.override_pipeline(
                            {
                                "ActivityMainChapter": {"enabled": True},
                                "ActivityRe_releaseChapter": {
                                    "custom_recognition_param": {
                                        "Re_release_name": item["activity"][
                                            "re-release"
                                        ]["alias"]
                                    }
                                },
                            }
                        )
                        if item["activity"]["re-release"].get("override"):
                            context.override_pipeline(
                                item["activity"]["re-release"].get("override")
                            )
                        return CustomAction.RunResult(success=True)
                    continue
                break

        context.override_pipeline(
            {"JudgeDuringRe_release": {"next": [], "interrupt": []}}
        )
        logger.info("当前不在复刻作战开放时间，跳过当前任务")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SSTaskEntryGet")
class SSTaskEntryGet(CustomAction):
    """
    获取SS任务入口
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        screen_array = context.tasker.controller.post_screencap().wait().get()

        # 截取图片中 [1170,141,47,53] 区域
        x, y, w, h = 1170, 141, 47, 53
        roi_array = screen_array[y : y + h, x : x + w]

        # BGR2RGB
        rgb_array = roi_array[:, :, ::-1]

        # 转换为 PIL Image
        img = Image.fromarray(rgb_array)

        # 保存图片
        save_path = "tmp/ss_task_entry.png"
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        img.save(save_path)
        logger.info(f"已保存 SS 任务入口截图: {save_path}")

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SailingRecordDiceStrategy")
class SailingRecordDiceStrategy(CustomAction):
    """
    计算骰子选择的最优策略

    参数格式：
    {
        // 可以为空，将直接使用SailingRecordBoatRecord.dices中的骰子数据
    }
    """

    @staticmethod
    def calculate_optimal_dice_strategy(dices, target_min, target_max):
        """
        计算最优骰子选择策略，使得三次骰子点数之和落在目标范围内的概率最大

        Args:
            dices: 三个骰子的点数列表，每个骰子有六个面
            target_min: 目标范围的最小值
            target_max: 目标范围的最大值

        Returns:
            最优选择的骰子索引 (三次选择)和成功概率
        """
        # 统计每个骰子的概率分布
        dice_probs = []
        for dice in dices:
            # 计算每个值的出现概率
            values = {}
            for value in dice:
                values[value] = values.get(value, 0) + 1 / 6
            dice_probs.append(values)

        # 计算所有可能的三次选择组合的概率
        best_prob = 0
        best_choice = None

        # 尝试所有可能的骰子选择组合 (i,j,k表示选择的骰子索引)
        for i in range(3):  # 第一次选择
            for j in range(3):  # 第二次选择
                for k in range(3):  # 第三次选择
                    # 计算所有可能的点数和及其概率
                    sum_probs = {}

                    # 计算三个骰子选择的所有可能结果
                    for val1, prob1 in dice_probs[i].items():
                        for val2, prob2 in dice_probs[j].items():
                            for val3, prob3 in dice_probs[k].items():
                                total = val1 + val2 + val3
                                prob = prob1 * prob2 * prob3
                                sum_probs[total] = sum_probs.get(total, 0) + prob

                    # 计算和在目标范围内的总概率
                    in_range_prob = sum(
                        sum_probs.get(s, 0) for s in range(target_min, target_max + 1)
                    )

                    if in_range_prob > best_prob:
                        best_prob = in_range_prob
                        best_choice = (i, j, k)

        return best_choice, best_prob

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """
        计算最优骰子选择策略
        """
        # 获取骰子数据，使用SailingRecordBoatRecord中存储的数据
        dices = SailingRecordBoatRecord.dices

        # 获取目标范围
        target_min = SailingRecordSelectTarget.min
        target_max = SailingRecordSelectTarget.max

        logger.info(f"[DiceStrategy] 骰子数据: {dices}")
        logger.info(f"[DiceStrategy] 目标范围: {target_min}~{target_max}")

        # 计算最优选择策略
        best_choice, best_prob = self.calculate_optimal_dice_strategy(
            dices, target_min, target_max
        )

        SailingRecordDiceStrategy.best_choice = (
            best_choice if best_choice else (0, 0, 0)
        )

        logger.info(
            f"[DiceStrategy] 最佳选择: {best_choice}, 成功概率: {best_prob:.2%}"
        )

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SailingRecordBoatSelect")
class SailingRecordBoatSelect(CustomAction):
    """
    选择骰子
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """
        选择骰子
        """
        # 获取最佳选择
        best_choice = SailingRecordDiceStrategy.best_choice

        # 骰子数量 roi
        roi_dices = [[239, 541, 39, 26], [621, 541, 39, 26], [1001, 541, 39, 26]]
        # plus&minus roi
        roi_plus_minus = [[110, 520, 310, 66], [491, 521, 310, 66], [871, 522, 310, 66]]

        for i in range(3):
            flag = False
            while not flag:
                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition(
                    "SailingRecordBoatPointRecord",
                    img,
                    {"SailingRecordBoatPointRecord": {"roi": roi_dices[i]}},
                )
                if best_choice.count(i) > int(reco_detail.best_result.text):
                    context.run_task(
                        "SailingRecordBoatOp",
                        {
                            "SailingRecordBoatOp": {
                                "template": "Sp01/Plus.png",
                                "roi": roi_plus_minus[i],
                            }
                        },
                    )
                elif best_choice.count(i) < int(reco_detail.best_result.text):
                    context.run_task(
                        "SailingRecordBoatOp",
                        {
                            "SailingRecordBoatOp": {
                                "template": "Sp01/Minus.png",
                                "roi": roi_plus_minus[i],
                            }
                        },
                    )
                else:
                    flag = True

        return CustomAction.RunResult(success=True)
