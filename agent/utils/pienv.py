from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

ENV_INTERFACE_VERSION = "PI_INTERFACE_VERSION"
ENV_CLIENT_NAME = "PI_CLIENT_NAME"
ENV_CLIENT_VERSION = "PI_CLIENT_VERSION"
ENV_CLIENT_LANGUAGE = "PI_CLIENT_LANGUAGE"
ENV_CLIENT_MAAFW_VERSION = "PI_CLIENT_MAAFW_VERSION"
ENV_VERSION = "PI_VERSION"
ENV_CONTROLLER = "PI_CONTROLLER"
ENV_RESOURCE = "PI_RESOURCE"


@dataclass(frozen=True)
class Controller:
    name: str = ""
    type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Resource:
    name: str = ""
    path: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PiEnv:
    interface_version: str = ""
    client_name: str = ""
    client_version: str = ""
    client_language: str = ""
    client_maafw_version: str = ""
    version: str = ""
    controller: Controller | None = None
    resource: Resource | None = None
    controller_raw: str = ""
    resource_raw: str = ""


def read_env() -> PiEnv:
    controller_raw = os.getenv(ENV_CONTROLLER, "")
    resource_raw = os.getenv(ENV_RESOURCE, "")
    return PiEnv(
        interface_version=os.getenv(ENV_INTERFACE_VERSION, ""),
        client_name=os.getenv(ENV_CLIENT_NAME, ""),
        client_version=os.getenv(ENV_CLIENT_VERSION, ""),
        client_language=os.getenv(ENV_CLIENT_LANGUAGE, ""),
        client_maafw_version=os.getenv(ENV_CLIENT_MAAFW_VERSION, ""),
        version=os.getenv(ENV_VERSION, ""),
        controller=parse_controller(controller_raw),
        resource=parse_resource(resource_raw),
        controller_raw=controller_raw,
        resource_raw=resource_raw,
    )


def parse_controller(raw: str) -> Controller | None:
    data = parse_json_object(raw)
    if data is None:
        return None
    return Controller(name=str(data.get("name", "")), type=str(data.get("type", "")), raw=data)


def parse_resource(raw: str) -> Resource | None:
    data = parse_json_object(raw)
    if data is None:
        return None
    path = data.get("path", [])
    paths = [str(item) for item in path] if isinstance(path, list) else []
    return Resource(name=str(data.get("name", "")), path=paths, raw=data)


def parse_json_object(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
