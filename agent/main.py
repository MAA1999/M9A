import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
except AttributeError:
    pass

current_file_path = os.path.abspath(__file__)
agent_dir = os.path.dirname(current_file_path)
project_root_dir = os.path.dirname(agent_dir)

if os.getcwd() != project_root_dir:
    os.chdir(project_root_dir)

if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

from agent_runtime import run_agent  # noqa: E402


def main() -> int:
    return run_agent(project_root_dir=project_root_dir)


if __name__ == "__main__":
    sys.exit(main())
