import os
import sys

# utf-8
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

# 获取当前main.py路径并设置上级目录为工作目录
current_file_path = os.path.abspath(__file__)
current_script_dir = os.path.dirname(current_file_path)  # 包含此脚本的目录
project_root_dir = os.path.dirname(current_script_dir)  # 假定的项目根目录

# 更改CWD到项目根目录
if os.getcwd() != project_root_dir:
    os.chdir(project_root_dir)
print(f"set cwd: {os.getcwd()}")

# 将脚本自身的目录添加到sys.path，以便导入utils、maa等模块
if current_script_dir not in sys.path:
    sys.path.insert(0, current_script_dir)

from agent_runtime import run_agent
from bootstrap import (
    check_and_install_dependencies,
    configure_initial_runtime_paths,
    ensure_venv_and_relaunch_if_needed,
    read_interface_version,
    switch_to_dev_work_root,
)

configure_initial_runtime_paths(project_root_dir)


def main():
    current_version = read_interface_version()
    is_dev_mode = current_version == "DEBUG"

    # 如果是Linux系统或开发模式，启动虚拟环境
    if sys.platform.startswith("linux") or is_dev_mode:
        ensure_venv_and_relaunch_if_needed(current_file_path)

    check_and_install_dependencies()

    if is_dev_mode:
        switch_to_dev_work_root(project_root_dir)

    run_agent(project_root_dir=project_root_dir, is_dev_mode=is_dev_mode)


if __name__ == "__main__":
    main()
