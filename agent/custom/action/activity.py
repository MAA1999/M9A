import json
import time
from typing import Any

from custom.reco.activity import SailingRecordBoatRecord, SailingRecordSelectTarget
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger, ms_timestamp_diff_to_dhm
from utils.maa_types import ocr_text
from utils.params import parse_params

# 活动数据由热更新下发，可能比代码更旧或缺少字段，因此下面所有字段访问都容错：
# 缺字段应表现为"该活动不可用"，而不是抛异常带崩整条流程。
# 复刻流程曾在数据缺少 name 字段时抛 KeyError，而 MaaFW 的 ctypes 回调不会把
# Python 异常当作失败（节点仍记为成功），复刻识别因此拿到空别名、误点了当期活动的卡片。


def _load_activity_data(resource: str) -> dict[str, Any]:
    """读取活动数据文件，只保证顶层是对象。"""
    path = f"data/activity/{resource}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"活动数据格式错误（顶层应为对象）: {path}")
    return data


def _version_info(data: dict[str, Any], key: str) -> tuple[str, int | float | None]:
    """版本的展示名与结束时间（仅用于日志）。"""
    item = data.get(key)
    if not isinstance(item, dict):
        return "", None
    name = item.get("version_name")
    end = item.get("end_time")
    return (name if isinstance(name, str) else "", end if isinstance(end, int | float) else None)


def _active_section(data: dict[str, Any], now: int, section: str) -> tuple[str, dict[str, Any]] | None:
    """按版本倒序扫描，返回当前生效的 ``(版本, 板块)``；语义与旧实现一致。"""
    for key, item in reversed(list(data.items())):
        activity = item.get("activity") if isinstance(item, dict) else None
        block = activity.get(section) if isinstance(activity, dict) else None
        if not isinstance(block, dict) or not block:
            continue

        start = block.get("start_time")
        end = block.get("end_time")
        if not isinstance(start, int | float) or not isinstance(end, int | float):
            continue  # 时间字段缺失：按不可用处理
        if start < now < end:
            return key, block
        if now >= end:
            break

    return None


def _re_release_alias(block: dict[str, Any]) -> str | None:
    """复刻别名（``alias`` 优先，回落 ``name``）；两者都缺失时返回 None。"""
    for field in ("alias", "name"):
        value = block.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@AgentServer.custom_action("DuringAct")
class DuringAct(CustomAction):
    """
    判断当前是否在作战开放期间

    参数格式：
    {
        "resource": "cn/en/jp/tw"
    }
    """

    # 标记当前是否为主线版本
    is_main_story = False

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        resource = parse_params(argv.custom_action_param, "resource")["resource"]
        DuringAct.resource = resource

        data = _load_activity_data(resource)

        now = int(time.time() * 1000)
        active = _active_section(data, now, "combat")

        if active is None:
            DuringAct.is_main_story = False
            context.override_next("JudgeDuringAct", [])
            logger.info("当前不在活动时间内，跳过当前任务")
            return CustomAction.RunResult(success=True)

        key, combat = active
        name, version_end = _version_info(data, key)
        # 进行复刻时间判断节点的资源字段覆盖
        context.override_pipeline({"JudgeDuringRe_release": {"custom_action_param": {"resource": resource}}})

        # 若为主线版本，标记状态，但不直接跳过（让 CombatActivityOverride 根据 mode 决定）
        # 不复刻模式时，禁用 CombatActivityOverride 并跳过；复刻模式时，继续执行让复刻判断来处理
        if combat.get("event_type") == "MainStory":
            DuringAct.is_main_story = True
            logger.info(f"当前为主线版本：{key} {name}")
            if version_end is not None:
                logger.info(f"距离版本结束还剩 {ms_timestamp_diff_to_dhm(now, version_end)}")
            logger.info("如果您需要刷取主线关卡，请改用常规作战功能")
        else:
            DuringAct.is_main_story = False

        logger.info(f"当前版本：{key} {name}")
        logger.info(f"距离作战结束还剩 {ms_timestamp_diff_to_dhm(now, combat['end_time'])}")
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

        mode = parse_params(argv.custom_action_param, "mode")["mode"]

        # 如果主线版本且非复刻模式（mode=0），跳过任务
        if DuringAct.is_main_story and mode == 0:
            context.override_pipeline({"CombatActivityOverride": {"enabled": False}})
            context.override_next("CombatActivityOverride", [])
            logger.info("主线版本且未开启复刻模式，跳过当前任务")
            return CustomAction.RunResult(success=True)

        data = _load_activity_data(DuringAct.resource)

        now = int(time.time() * 1000)

        if mode == 1:
            active = _active_section(data, now, "re-release")
            if active is None:
                context.override_next("CombatActivityOverride", ["CombatActivityNoReRelease"])
                logger.info("当前未开放复刻活动，跳过活动代币刷取")
                return CustomAction.RunResult(success=True)

            _, block = active
            override = block.get("override")
            if isinstance(override, dict):
                context.override_pipeline(override)
            return CustomAction.RunResult(success=True)

        active = _active_section(data, now, "combat")
        if active is not None:
            _, block = active
            override = block.get("override")
            if isinstance(override, dict):
                context.override_pipeline(override)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DuringAnecdote")
class DuringAnecdote(CustomAction):
    """
    判断当前是否在轶事开放期间

    参数格式：
    {
        "resource": "cn/en/jp/tw"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        resource = parse_params(argv.custom_action_param, "resource")["resource"]

        data = _load_activity_data(resource)

        now = int(time.time() * 1000)
        active = _active_section(data, now, "anecdote")

        if active is None:
            context.override_next("JudgeDuringAnecdote", [])
            logger.info("当前不在轶事开放时间，跳过当前任务")
            return CustomAction.RunResult(success=True)

        key, block = active
        name, _ = _version_info(data, key)
        logger.info(f"当前版本：{key} {name}")
        logger.info(f"距离轶事结束还剩 {ms_timestamp_diff_to_dhm(now, block['end_time'])}")
        override = block.get("override")
        if isinstance(override, dict):
            context.override_pipeline(override)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DuringRe_release")
class DuringRe_release(CustomAction):
    """
    判断当前是否在版本复刻期间

    参数格式：
    {
        "resource": "cn/en/jp/tw"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        resource = parse_params(argv.custom_action_param, "resource")["resource"]

        data = _load_activity_data(resource)

        now = int(time.time() * 1000)
        active = _active_section(data, now, "re-release")

        if active is None:
            context.override_pipeline({"JudgeDuringRe_release": {"next": []}})
            logger.info("当前不在复刻作战开放时间，跳过当前任务")
            return CustomAction.RunResult(success=True)

        key, block = active
        # 数据缺 alias/name 时不能继续：空别名会让复刻识别"匹配一切"，误点当期活动卡片
        alias = _re_release_alias(block)
        if alias is None:
            logger.error(
                f"复刻活动数据缺少 alias/name 字段（{resource} {key}），无法定位复刻活动卡片；"
                "可能是活动数据未更新成功，请重启以重试资源更新或升级 M9A"
            )
            context.override_next("JudgeDuringRe_release", ["ActivityRe_releaseChapterError"])
            return CustomAction.RunResult(success=True)

        logger.info(f"当前复刻活动：{alias}")
        logger.info(f"距离复刻作战结束还剩 {ms_timestamp_diff_to_dhm(now, block['end_time'])}")
        # 当前为合法复刻作战时间，且复刻模式开启，进行相关覆盖
        context.override_pipeline(
            {
                "ActivityMainChapter": {"enabled": True},
                "ActivityRe_releaseChapter": {"custom_recognition_param": {"Re_release_name": alias}},
            }
        )
        override = block.get("override")
        if isinstance(override, dict):
            context.override_pipeline(override)
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

        context.override_image("ss_task_entry", roi_array)

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
    def calculate_optimal_dice_strategy(
        dices: list[list[int]], target_min: int, target_max: int
    ) -> tuple[tuple[int, int, int] | None, float]:
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
                    in_range_prob = sum(sum_probs.get(s, 0) for s in range(target_min, target_max + 1))

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
        best_choice, best_prob = self.calculate_optimal_dice_strategy(dices, target_min, target_max)

        SailingRecordDiceStrategy.best_choice = best_choice if best_choice else (0, 0, 0)

        logger.info(f"[DiceStrategy] 最佳选择: {best_choice}, 成功概率: {best_prob:.2%}")

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
                point = int(ocr_text(reco_detail))
                if best_choice.count(i) > point:
                    context.run_task(
                        "SailingRecordBoatOp",
                        {
                            "SailingRecordBoatOp": {
                                "template": "Sp01/Plus.png",
                                "roi": roi_plus_minus[i],
                            }
                        },
                    )
                elif best_choice.count(i) < point:
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
