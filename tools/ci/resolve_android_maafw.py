"""解析 Android 打包流程要用的版本与命名参数。

CI 的 `android.yml` 靠它决定两件事：

1. client 侧（APK 里的 `jniLibs`）铺哪个 MaaFramework release —— Android 的 Python 绑定就是
   内核（MaaAgentCoreAndroid）自带的那份，公开索引又没有 Android 版 `maafw` 轮子，所以原生库
   必须与内核同版本，否则 APK 里前后端版本不一致；
2. release 资产前缀 —— 取 `maa-project.json` 的显示名（不可用时退回 slug），
   于是同一份 workflow 可以给别的项目直接用。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

CORE_SCRIPT = Path("Android/MaaFwApp/scripts/build_agent_bundle.py")
REQUIREMENTS = Path("requirements.txt")
PROJECT_CONFIG = Path("maa-project.json")

# CORE_TAG 形如 "3.13.15-maafw5.12.3"，只取 maafw 后面那段版本号
CORE_TAG_PATTERN = re.compile(r'CORE_TAG\s*=\s*"[^"]*?maafw([0-9][^"]*)"')
REQUIREMENT_PIN_PATTERN = re.compile(r"^maafw==([0-9][^\s;]*)", re.MULTILINE)
SAFE_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class AndroidPackaging:
    """android.yml 需要的解析结果。"""

    maafw_tag: str
    """拿去传给 `setup_maa_framework.py --tag` 的 release tag，形如 `v5.12.3`。"""

    artifact_prefix: str
    """release 资产前缀，形如 `M9A`，最终名字是 `<前缀>-<tag>-<universal|abi>.apk`。"""

    requirement_pin: str
    """requirements.txt 里的 maafw pin；与内核不一致时只用于提示。"""

    declared_target: str
    """maa-project.json 声明的 MaaFW 目标，同样只用于提示。"""


def parse_core_version(text: str) -> str:
    """取出内核构建脚本自带的 maafw 版本。"""
    match = CORE_TAG_PATTERN.search(text)
    if match is None:
        raise ValueError("解析不到内核 CORE_TAG 里的 maafw 版本")
    return match.group(1)


def parse_requirement_pin(text: str) -> str:
    """取出 requirements.txt 里的 maafw==X。"""
    match = REQUIREMENT_PIN_PATTERN.search(text)
    if match is None:
        raise ValueError("requirements.txt 里没有 maafw== 的精确 pin")
    return match.group(1)


def _string_field(container: Mapping[str, object], key: str) -> str:
    value = container.get(key)
    return value.strip() if isinstance(value, str) else ""


def _object_field(container: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = container.get(key)
    return value if isinstance(value, Mapping) else {}


def declared_target(project: Mapping[str, object]) -> str:
    """maa-project.json 声明的 MaaFW 目标：显式 version 优先，否则按通道描述。"""
    maafw = _object_field(project, "maafw")
    version = _string_field(maafw, "version")
    if version:
        return version
    return f"{_string_field(maafw, 'channel') or 'stable'} 通道最新"


def artifact_prefix(project: Mapping[str, object]) -> str:
    """release 资产前缀：显示名能进文件名就用它，否则退回 slug。"""
    section = _object_field(project, "project")
    for key in ("displayName", "slug"):
        candidate = _string_field(section, key)
        if SAFE_PREFIX_PATTERN.match(candidate):
            return candidate
    raise ValueError("maa-project.json 里没有可用的 project.displayName / project.slug")


def resolve(root: Path) -> AndroidPackaging:
    """读齐三份配置，得出 CI 需要的打包参数。"""
    core_version = parse_core_version((root / CORE_SCRIPT).read_text(encoding="utf-8"))
    requirement_pin = parse_requirement_pin((root / REQUIREMENTS).read_text(encoding="utf-8"))
    raw_project: object = json.loads((root / PROJECT_CONFIG).read_text(encoding="utf-8"))
    if not isinstance(raw_project, Mapping):
        raise ValueError("maa-project.json 的顶层必须是对象")
    project: Mapping[str, object] = raw_project
    return AndroidPackaging(
        maafw_tag=f"v{core_version}",
        artifact_prefix=artifact_prefix(project),
        requirement_pin=requirement_pin,
        declared_target=declared_target(project),
    )


def write_outputs(path: Path, values: Mapping[str, str]) -> None:
    """把结果追加到 $GITHUB_OUTPUT。"""
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path.cwd()
    try:
        packaging = resolve(root)
    except (OSError, ValueError) as error:
        print(f"::error::{error}")
        return 1

    core_version = packaging.maafw_tag.removeprefix("v")
    if packaging.requirement_pin != core_version:
        print(
            f"::warning::Android 绑定暂时只能跟内核 {core_version}（没有公开的 Android 版 maafw 轮子）；"
            f"requirements 的 maafw=={packaging.requirement_pin}、maa-project.json 的 "
            f"{packaging.declared_target} 待内核更新后自动跟进"
        )

    print(f"client MaaFW tag : {packaging.maafw_tag}（与内核绑定 {core_version} 一致）")
    print(f"artifact prefix  : {packaging.artifact_prefix}")
    print(f"maa-project.json : {packaging.declared_target}")
    print(f"requirements pin : {packaging.requirement_pin}")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        write_outputs(
            Path(output),
            {"maafw_tag": packaging.maafw_tag, "artifact_prefix": packaging.artifact_prefix},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
