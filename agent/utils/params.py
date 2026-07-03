from __future__ import annotations

import json
from typing import Any


def parse_params(raw: str | None, *required_keys: str) -> dict[str, Any]:
    if not raw:
        if required_keys:
            raise ValueError(f"missing required params: {list(required_keys)}")
        return {}

    try:
        params = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON params: {error}") from error

    if not isinstance(params, dict):
        raise ValueError(f"params must be an object, got {type(params).__name__}")

    missing = [key for key in required_keys if key not in params]
    if missing:
        raise ValueError(f"missing required params: {missing}")
    return params
