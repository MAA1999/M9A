from __future__ import annotations

from typing import Any


def is_hit(detail: Any) -> bool:
    return detail is not None and getattr(detail, "box", None) is not None


def ocr_text(detail: Any) -> str:
    if detail is None:
        return ""
    raw_detail = getattr(detail, "detail", None)
    if isinstance(raw_detail, str):
        return raw_detail
    if isinstance(raw_detail, dict):
        for key in ("text", "recognized", "content"):
            value = raw_detail.get(key)
            if isinstance(value, str):
                return value
    return str(raw_detail or "")
