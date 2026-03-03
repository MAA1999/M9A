from pathlib import Path

import shutil
import sys
import json
import os
import re

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from configure import configure_ocr_model
from generate_manifest_cache import generate_manifest_cache

working_dir = Path(__file__).parent.parent.parent
install_path = working_dir / Path("install-cli")
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"


def strip_html_tags(text: str) -> str:
    """移除字符串中的 HTML 标签，将 <br> 转换为换行符"""
    # 将 <br> 和 <br/> 转换为换行符
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # 移除所有其他 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    return text


def strip_html_from_interface(obj: dict | list) -> None:
    """递归处理 interface 中所有 description 字段，移除 HTML 标签（就地修改）"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "description" and isinstance(value, str):
                obj[key] = strip_html_tags(value)
            elif isinstance(value, (dict, list)):
                strip_html_from_interface(value)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                strip_html_from_interface(item)


def install_deps():
    shutil.copytree(
        working_dir / "deps" / "bin",
        install_path,
        ignore=shutil.ignore_patterns(
            "*MaaDbgControlUnit*",
            "*MaaThriftControlUnit*",
            "*MaaWin32ControlUnit*",
            "*MaaRpc*",
            "*MaaHttp*",
        ),
        dirs_exist_ok=True,
    )
    shutil.copytree(
        working_dir / "deps" / "share" / "MaaAgentBinary",
        install_path / "MaaAgentBinary",
        dirs_exist_ok=True,
    )


def install_resource():

    configure_ocr_model()

    shutil.copytree(
        working_dir / "assets" / "resource",
        install_path / "resource",
        dirs_exist_ok=True,
    )
    with open(working_dir / "assets" / "interface.json", "r", encoding="utf-8") as f:
        interface = json.load(f)

    interface["version"] = version
    interface["title"] = f"M9A {version} | 亿韭韭韭小助手"

    # CLI 版本需要移除 HTML 标签
    strip_html_from_interface(interface)

    with open(install_path / "interface.json", "w", encoding="utf-8") as f:
        json.dump(interface, f, ensure_ascii=False, indent=4)
        f.write("\n")

    # 处理 tasks 文件夹下所有 json 文件的 HTML 标签
    tasks_dir = install_path / "resource" / "tasks"
    for json_file in tasks_dir.rglob("*.json"):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        strip_html_from_interface(data)
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")


def install_chores():
    for file in ["README.md", "LICENSE", "CONTACT", "requirements.txt"]:
        shutil.copy2(
            working_dir / file,
            install_path,
        )
    # shutil.copytree(
    #     working_dir / "docs",
    #     install_path / "docs",
    #     dirs_exist_ok=True,
    #     ignore=shutil.ignore_patterns("*.yaml"),
    # )


def install_agent():
    shutil.copytree(
        working_dir / "agent",
        install_path / "agent",
        dirs_exist_ok=True,
    )

    with open(install_path / "interface.json", "r", encoding="utf-8") as f:
        interface = json.load(f)

    if sys.platform.startswith("win"):
        interface["agent"]["child_exec"] = r"./python/python.exe"
    elif sys.platform.startswith("darwin"):
        interface["agent"]["child_exec"] = r"./python/bin/python3"
    elif sys.platform.startswith("linux"):
        interface["agent"]["child_exec"] = r"python3"

    interface["agent"]["child_args"] = ["-u", r"./agent/main.py"]

    with open(install_path / "interface.json", "w", encoding="utf-8") as f:
        json.dump(interface, f, ensure_ascii=False, indent=4)


def install_manifest_cache():
    """生成初始 manifest 缓存，加速用户首次启动"""
    config_dir = install_path / "config"
    success = generate_manifest_cache(config_dir)
    if success:
        print("Manifest cache generated successfully.")
    else:
        print(
            "Warning: Manifest cache generation failed, users will do full check on first run."
        )


if __name__ == "__main__":
    install_deps()
    install_resource()
    install_chores()
    install_agent()
    install_manifest_cache()

    print(f"Install to {install_path} successfully.")
