import time
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.account_store import (
    get_account_scalar,
    load_json_object,
    save_json_object,
    set_account_scalar,
)
from utils.params import parse_params
from utils.time import is_current_period

from .record_id import RecordID

CONFIG_PATH = Path("config/m9a_data.json")


@AgentServer.custom_action("JudgeDepthsOfMythWeekly")
class JudgeDepthsOfMythWeekly(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        resource = parse_params(argv.custom_action_param, "resource")["resource"]

        if resource in {"cn", "tw"}:
            timezone = "Asia/Shanghai"
        elif resource == "en":
            timezone = "America/New_York"
        else:
            timezone = "Asia/Tokyo"

        now_ms = int(time.time() * 1000)
        data = load_json_object(CONFIG_PATH, {})
        account_id = RecordID.current_account_id()
        timestamp_ms = get_account_scalar(data, "DepthsOfMyth", account_id)

        if timestamp_ms is None:
            set_account_scalar(data, "DepthsOfMyth", account_id, now_ms)
            save_json_object(CONFIG_PATH, data)
            logger.info("无时间记录，跳过时间检查")
            return CustomAction.RunResult(success=True)

        is_current_week, _ = is_current_period(timestamp_ms, timezone)

        if is_current_week:
            set_account_scalar(data, "DepthsOfMyth", account_id, timestamp_ms)
            save_json_object(CONFIG_PATH, data)
            context.override_next("JudgeDepthsOfMythWeekly", [])
            logger.info("本周已完成迷思海扫荡，跳过")
        else:
            set_account_scalar(data, "DepthsOfMyth", account_id, now_ms)
            save_json_object(CONFIG_PATH, data)
            logger.info("本周尚未执行迷思海")

        return CustomAction.RunResult(success=True)
