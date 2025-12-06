import os
import time
import json
from datetime import datetime, timedelta

import pytz
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger
from utils.time import is_current_period


@AgentServer.custom_action("BankPurchaseRecord")
class BankPurchaseRecord(CustomAction):
    """
    记录在银行购买物品的时间戳

    参数格式:
    {
        "item": "物品名称"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        item = json.loads(argv.custom_action_param)["item"]

        with open("config/m9a_data.json") as f:
            data = json.load(f)

        data["bank"][item] = int(time.time() * 1000)

        with open("config/m9a_data.json", "w") as f:
            json.dump(data, f, indent=4)

        logger.info(f"{item}检查时间已记录")

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ModifyBankTaskList")
class ModifyBankTaskList(CustomAction):
    """
    这时的任务链在ui执行后已经禁止了不运行的任务，这步是通过读本地过往执行记录继续禁止不需要运行的任务。

    参数格式:
    {
        "resource": "cn/en/jp/tw"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        tasks: dict = {
            "FreeWeeklyGift": "week",
            "Rabbit": "month",
            "SmallGlobe": "month",
            "TinyGlobe": "month",
            "Gluttony": "month",
            "TinyGlobe(1)": "month",
            "ResonantCassette": "month",
            "GoldenMelonSeeds": "week",
            "OriginalChicken": "month",
            "Fries": "month",
        }
        resource = json.loads(argv.custom_action_param)["resource"]

        if resource == "cn" or resource == "tw":
            timezone = "Asia/Shanghai"
        elif resource == "en":
            timezone = "America/New_York"
        else:
            timezone = "Asia/Tokyo"

        file_path = "config/m9a_data.json"
        default_data = {"bank": {}}

        if not os.path.exists(file_path):

            logger.warning("config/m9a_data.json 不存在，正在初始化")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(default_data, file, indent=4)
            logger.info("初始化完成，跳过时间检查")

            return CustomAction.RunResult(success=True)

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"非标准json文件，正在初始化: {e}")
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(default_data, file, indent=4)
            logger.info("初始化完成，跳过时间检查")
            return CustomAction.RunResult(success=True)

        if "bank" not in data:
            data["bank"] = {}
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
            logger.info("无时间记录，跳过时间检查")

            return CustomAction.RunResult(success=True)

        for task, type in tasks.items():
            is_current_week, is_current_month = is_current_period(
                data["bank"].get(task, 1058306766000), timezone
            )
            if type == "week":
                if is_current_week:
                    context.override_pipeline({f"{task}": {"enabled": False}})
                    logger.info(f"{task} 本周已完成，跳过")
            elif type == "month":
                if is_current_month:
                    context.override_pipeline({f"{task}": {"enabled": False}})
                    logger.info(f"{task} 本月已完成，跳过")

        return CustomAction.RunResult(success=True)
