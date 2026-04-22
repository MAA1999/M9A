import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger

CONFIG_PATH = Path("config/m9a_data.json")
DATA_DIR = Path("resource/data/redeem_code")

RESOURCE_TIMEZONES = {
    "cn": "Asia/Shanghai",
    "tw": "Asia/Shanghai",
    "en": "America/New_York",
    "jp": "Asia/Tokyo",
    "kr": "Asia/Seoul",
}


@dataclass(frozen=True)
class RedeemCodeItem:
    code: str
    source: str


def _load_json_object(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default.copy()

    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid json file {path}, reinitializing: {e}")
        return default.copy()

    if not isinstance(data, dict):
        logger.warning(f"Invalid json root in {path}, reinitializing")
        return default.copy()

    return data


def _save_json_object(path: Path, data: dict[str, Any]) -> None:
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def _get_timezone(resource: str):
    return pytz.timezone(RESOURCE_TIMEZONES.get(resource, "Asia/Shanghai"))


def _split_custom_codes(codes: Any) -> list[RedeemCodeItem]:
    if isinstance(codes, list):
        raw_codes = [str(code).strip() for code in codes]
    else:
        raw_codes = re.split(r"[\s,，;；]+", str(codes or ""))

    return [
        RedeemCodeItem(code=code.strip(), source="custom")
        for code in raw_codes
        if code and code.strip()
    ]


def _load_resource_codes(resource: str) -> list[RedeemCodeItem]:
    path = DATA_DIR / f"{resource}.txt"
    if not path.exists():
        logger.debug(f"Redeem code data file not found: {path}")
        return []

    tz = _get_timezone(resource)
    now = datetime.now(tz)
    items: list[RedeemCodeItem] = []

    with open(path, encoding="utf-8") as file:
        for line_no, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.rsplit(maxsplit=2)
            if len(parts) != 3:
                logger.warning(f"Invalid redeem code data at {path}:{line_no}: {line}")
                continue

            code, date_text, time_text = parts
            try:
                deadline = datetime.strptime(
                    f"{date_text} {time_text}", "%Y-%m-%d %H:%M"
                )
            except ValueError:
                logger.warning(
                    f"Invalid redeem code deadline at {path}:{line_no}: {line}"
                )
                continue

            deadline = tz.localize(deadline)
            if now >= deadline:
                logger.debug(f"Skip expired redeem code: {code}")
                continue

            items.append(RedeemCodeItem(code=code.strip(), source=str(path)))

    return items


def _dedupe_codes(items: list[RedeemCodeItem]) -> list[RedeemCodeItem]:
    result: list[RedeemCodeItem] = []
    seen: set[str] = set()

    for item in items:
        if item.code in seen:
            continue
        seen.add(item.code)
        result.append(item)

    return result


def _get_redeem_code_store(data: dict[str, Any]) -> dict[str, Any]:
    store = data.get("redeem_code")
    if not isinstance(store, dict):
        store = {}
        data["redeem_code"] = store
    return store


def _get_used_codes(data: dict[str, Any], resource: str) -> set[str]:
    store = _get_redeem_code_store(data)
    resource_store = store.get(resource, {})

    if isinstance(resource_store, dict):
        return {str(code) for code in resource_store.keys()}

    if isinstance(resource_store, list):
        return {str(code) for code in resource_store}

    return set()


def _mark_code_used(data: dict[str, Any], resource: str, code: str) -> None:
    store = _get_redeem_code_store(data)
    resource_store = store.get(resource)
    if not isinstance(resource_store, dict):
        resource_store = {}
        store[resource] = resource_store

    resource_store[code] = int(time.time() * 1000)


def _pipeline_override_for_code(code: str) -> dict[str, Any]:
    return {
        "redeem_codeClickInputBoxCompleted": {
            "action": {
                "param": {
                    "input_text": code,
                }
            }
        },
        "redeem_codeInputCompleted": {
            "recognition": {
                "param": {
                    "expected": [
                        re.escape(code),
                    ]
                }
            }
        },
    }


@AgentServer.custom_action("RedeemCode")
class RedeemCode(CustomAction):
    """
    Submit all configured redeem codes.

    custom_action_param:
    {
        "check": true
    }

    redeem_codeStart.attach:
    {
        "codes": "code1 code2",
        "resource": "cn"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            params = json.loads(argv.custom_action_param or "{}")
        except json.JSONDecodeError:
            logger.exception("RedeemCode failed to parse custom_action_param")
            return CustomAction.RunResult(success=False)

        check_used = bool(params.get("check", True))
        node_data = context.get_node_data(argv.node_name) or {}
        attach = node_data.get("attach", {}) if isinstance(node_data, dict) else {}
        if not isinstance(attach, dict):
            attach = {}

        resource = str(attach.get("resource", "cn") or "cn")
        custom_codes = _split_custom_codes(attach.get("codes", ""))
        resource_codes = _load_resource_codes(resource)
        codes = _dedupe_codes(custom_codes + resource_codes)

        if not codes:
            logger.info("No redeem code to submit")
            return CustomAction.RunResult(success=True)

        data = _load_json_object(CONFIG_PATH, {"bank": {}, "redeem_code": {}})
        if check_used:
            used_codes = _get_used_codes(data, resource)
            pending_codes = [item for item in codes if item.code not in used_codes]
        else:
            pending_codes = codes

        if not pending_codes:
            logger.info("All redeem codes have been used, skipping")
            return CustomAction.RunResult(success=True)

        logger.info(f"Submitting {len(pending_codes)} redeem code(s)")

        has_failure = False
        completed_codes: list[str] = []

        for item in pending_codes:
            logger.info(f"Submit redeem code: {item.code}")
            task_detail = context.run_task(
                "redeem_codeSubTask",
                _pipeline_override_for_code(item.code),
            )

            if task_detail is None or task_detail.status.failed:
                logger.error(f"Redeem code task failed: {item.code}")
                has_failure = True
                break

            completed_codes.append(item.code)
            _mark_code_used(data, resource, item.code)

        if completed_codes:
            _save_json_object(CONFIG_PATH, data)
            logger.info(f"Recorded {len(completed_codes)} used redeem code(s)")

        return CustomAction.RunResult(success=not has_failure)
