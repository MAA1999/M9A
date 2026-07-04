import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .logger import logger

DEFAULT_ACCOUNT_KEY = "__default__"


def normalize_account_id(account_id: str | None) -> str:
    return str(account_id or "").strip()


def load_json_object(path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    path = Path(path)

    if not path.exists():
        return deepcopy(default)

    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid json file {path}, reinitializing: {e}")
        return deepcopy(default)
    except OSError as e:
        logger.warning(f"Failed to read json file {path}, reinitializing: {e}")
        return deepcopy(default)

    if not isinstance(data, dict):
        logger.warning(f"Invalid json root in {path}, reinitializing")
        return deepcopy(default)

    return data


def save_json_object(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    os.makedirs(path.parent, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def get_account_bucket(
    data: dict[str, Any], key: str, account_id: str | None
) -> dict[str, Any]:
    normalized_account_id = normalize_account_id(account_id)
    store = data.get(key)

    if not isinstance(store, dict):
        store = {}
        data[key] = store

    if normalized_account_id:
        bucket = store.get(normalized_account_id)
        if isinstance(bucket, dict):
            return bucket

        if store and not any(isinstance(value, dict) for value in store.values()):
            legacy_bucket = dict(store)
            store.clear()
            store[normalized_account_id] = legacy_bucket
            return legacy_bucket

        bucket = {}
        store[normalized_account_id] = bucket
        return bucket

    if any(isinstance(value, dict) for value in store.values()):
        bucket = store.get(DEFAULT_ACCOUNT_KEY)
        if not isinstance(bucket, dict):
            bucket = {}
            store[DEFAULT_ACCOUNT_KEY] = bucket
        return bucket

    return store


def get_account_scalar(
    data: dict[str, Any], key: str, account_id: str | None
) -> Any | None:
    normalized_account_id = normalize_account_id(account_id)
    value = data.get(key)

    if isinstance(value, dict):
        lookup_key = normalized_account_id or DEFAULT_ACCOUNT_KEY
        return value.get(lookup_key)

    if normalized_account_id and value is not None:
        data[key] = {normalized_account_id: value}

    return value


def set_account_scalar(
    data: dict[str, Any], key: str, account_id: str | None, value: Any
) -> None:
    normalized_account_id = normalize_account_id(account_id)
    current_value = data.get(key)

    if not normalized_account_id and not isinstance(current_value, dict):
        data[key] = value
        return

    if not isinstance(current_value, dict):
        current_value = {}
        data[key] = current_value

    current_value[normalized_account_id or DEFAULT_ACCOUNT_KEY] = value
