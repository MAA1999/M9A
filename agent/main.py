import os
import sys

if sys.version_info < (3, 13) or sys.version_info >= (3, 14):
    raise SystemExit("Python >=3.13,<3.14 is required, got " + sys.version.split()[0])

try:
    sys.stdout.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
except AttributeError:
    pass

current_file_path = os.path.abspath(__file__)
agent_dir = os.path.dirname(current_file_path)
project_root_dir = os.path.dirname(agent_dir)

# PI_USER_DATA_DIR 被设置时以它为工作目录：macOS .app 里 project_root 在只读包内，
# 按 cwd 读写的相对路径（libs/drop_core.pyd 的 data/combat/*.json、遗漏的裸
# open("config/...")）必须落进可写的用户数据目录；agent_runtime 启动时用
# seed_work_root() 把包内基线播种过去，cwd 与 RuntimePaths.resolve() 指向同一份。
# 环境变量名与 utils.runtime_paths.ENV_USER_DATA_DIR 同步——这里不能 import utils
# （utils 包初始化会连带 import maa，ensure_maafw_binary_path 之后库目录就定死了）。
user_data_dir = os.environ.get("PI_USER_DATA_DIR", "").strip()
work_root_dir = user_data_dir if user_data_dir else project_root_dir
if os.path.realpath(os.getcwd()) != os.path.realpath(work_root_dir):
    os.makedirs(work_root_dir, exist_ok=True)
    os.chdir(work_root_dir)

if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

from maafw_paths import ensure_maafw_binary_path  # noqa: E402

# 必须早于 agent_runtime：utils 包在导入时就连带 import maa，那之后库目录已经定死
ensure_maafw_binary_path(project_root_dir)

from agent_runtime import run_agent  # noqa: E402


def main() -> int:
    return run_agent(project_root_dir=project_root_dir)


if __name__ == "__main__":
    sys.exit(main())
