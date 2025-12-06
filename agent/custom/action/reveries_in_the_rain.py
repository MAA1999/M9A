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


@AgentServer.custom_action("JudgeDepthsOfMythWeekly")
class JudgeDepthsOfMythWeekly(CustomAction):
    """
    记录在雨中悬想每周扫荡的时间戳

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

        resource = json.loads(argv.custom_action_param)["resource"]

        if resource == "cn" or resource == "tw":
            timezone = "Asia/Shanghai"
        elif resource == "en":
            timezone = "America/New_York"
        else:
            timezone = "Asia/Tokyo"

        file_path = "config/m9a_data.json"
        default_data = {"DepthsOfMyth": int(time.time() * 1000)}

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

        if "DepthsOfMyth" not in data:
            data["DepthsOfMyth"] = int(time.time() * 1000)
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
            logger.info("无时间记录，跳过时间检查")

            return CustomAction.RunResult(success=True)

        timestamp_ms = data["DepthsOfMyth"]
        is_current_week, _ = is_current_period(timestamp_ms, timezone)

        if is_current_week:
            context.override_next("JudgeDepthsOfMythWeekly", [])
            logger.info("本周已完成迷思海扫荡，跳过")
        else:
            # 更新时间戳为当前时间
            data["DepthsOfMyth"] = int(time.time() * 1000)
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
            logger.info("本周尚未执行迷思海")

        return CustomAction.RunResult(success=True)
