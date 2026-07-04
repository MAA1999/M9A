import time
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.account_store import get_account_bucket, load_json_object, save_json_object
from utils.params import parse_params
from utils.time import is_current_period

from .record_id import RecordID

CONFIG_PATH = Path("config/m9a_data.json")
DEFAULT_TIMESTAMP_MS = 1058306766000


@AgentServer.custom_action("BankPurchaseRecord")
class BankPurchaseRecord(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        item = parse_params(argv.custom_action_param, "item")["item"]
        data = load_json_object(CONFIG_PATH, {"bank": {}})
        bank_store = get_account_bucket(data, "bank", RecordID.current_account_id())
        bank_store[item] = int(time.time() * 1000)
        save_json_object(CONFIG_PATH, data)

        logger.info(f"{item}检查时间已记录")

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ModifyBankTaskList")
class ModifyBankTaskList(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        tasks: dict[str, str] = {
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
        resource = parse_params(argv.custom_action_param, "resource")["resource"]

        if resource in {"cn", "tw"}:
            timezone = "Asia/Shanghai"
        elif resource == "en":
            timezone = "America/New_York"
        else:
            timezone = "Asia/Tokyo"

        data = load_json_object(CONFIG_PATH, {"bank": {}})
        bank_store = get_account_bucket(data, "bank", RecordID.current_account_id())
        save_json_object(CONFIG_PATH, data)

        for task, period_type in tasks.items():
            is_current_week, is_current_month = is_current_period(
                bank_store.get(task, DEFAULT_TIMESTAMP_MS), timezone
            )
            if period_type == "week" and is_current_week:
                context.override_pipeline({task: {"enabled": False}})
                logger.info(f"{task} 本周已完成，跳过")
            elif period_type == "month" and is_current_month:
                context.override_pipeline({task: {"enabled": False}})
                logger.info(f"{task} 本月已完成，跳过")

        return CustomAction.RunResult(success=True)
