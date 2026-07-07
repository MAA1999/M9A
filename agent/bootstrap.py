from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import runpy
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PYTHON_MIN = (3, 13)
PYTHON_MAX = (3, 14)
VENV_NAME = ".venv"
REQUIREMENTS_MARKER = ".create-maa-project-requirements.sha256"
DEFAULT_PIP_CONFIG = {
    "enable_pip_install": True,
    "mirror": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "backup_mirror": "https://mirrors.ustc.edu.cn/pypi/simple",
}


def main() -> None:
    project_root = find_project_root()
    log(project_root, "bootstrap started")
    ensure_runtime_config(project_root)
    if should_use_linux_project_venv():
        ensure_venv_and_relaunch(project_root)
    if sys.version_info < PYTHON_MIN or sys.version_info >= PYTHON_MAX:
        log(project_root, "unsupported Python version: " + sys.version.split()[0])
        raise SystemExit("Python >=3.13,<3.14 is required")
    log(project_root, "Python " + sys.version.split()[0])
    requirements = check_requirements(project_root)
    if requirements is not None:
        ensure_requirements_installed(project_root, requirements[0], requirements[1])
    check_maafw(project_root)
    runpy.run_path(str(Path(__file__).with_name("main.py")), run_name="__main__")


def find_project_root() -> Path:
    path = Path(__file__).resolve()
    if path.parent.name == "agent" and path.parent.parent.name == "python":
        return path.parent.parent.parent
    return path.parent.parent


def should_use_linux_project_venv() -> bool:
    return sys.platform.startswith("linux") and not is_running_in_venv()


def is_running_in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def is_running_in_project_venv(project_root: Path) -> bool:
    if not is_running_in_venv():
        return False
    try:
        return Path(sys.prefix).resolve() == venv_dir(project_root).resolve()
    except OSError:
        return False


def venv_dir(project_root: Path) -> Path:
    return project_root / VENV_NAME


def ensure_venv_and_relaunch(project_root: Path) -> None:
    if sys.version_info >= PYTHON_MIN and sys.version_info < PYTHON_MAX:
        python_exe = Path(sys.executable)
    else:
        python_exe = find_compatible_python()
        if python_exe is None:
            warn(project_root, "Python >=3.13,<3.14 is required but no compatible version was found")
            raise SystemExit(1)

    target_venv = venv_dir(project_root)
    if not target_venv.exists():
        log(project_root, "creating virtual environment: " + str(target_venv))
        try:
            subprocess.run(
                [str(python_exe), "-m", "venv", str(target_venv)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
            )
        except subprocess.CalledProcessError as error:
            warn(project_root, "failed to create .venv: " + command_output(error))
            raise SystemExit(1) from error

    python = venv_python(target_venv)
    if not python.exists():
        warn(project_root, "Python executable is missing in .venv: " + str(python))
        raise SystemExit(1)

    log(project_root, "relaunching with virtual environment Python: " + str(python))
    result = subprocess.run(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=str(project_root),
        check=False,
    )
    raise SystemExit(result.returncode)


def venv_python(target_venv: Path) -> Path:
    if sys.platform.startswith("win"):
        return target_venv / "Scripts" / "python.exe"
    python3 = target_venv / "bin" / "python3"
    if python3.exists():
        return python3
    return target_venv / "bin" / "python"


def check_requirements(project_root: Path) -> tuple[Path, str] | None:
    requirements = find_requirements_file(project_root)
    if not requirements.exists():
        warn(
            project_root,
            "requirements.txt is missing; run create-maa-project --update python-deps",
        )
        return None
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    log(project_root, "requirements sha256=" + digest)
    return requirements, digest


def find_requirements_file(project_root: Path) -> Path:
    packaged = project_root / "python" / "requirements.txt"
    if packaged.exists():
        return packaged
    return project_root / "requirements.txt"


def ensure_requirements_installed(project_root: Path, requirements: Path, digest: str) -> None:
    if not needs_requirement_install(project_root, digest):
        return

    pip_config = read_pip_config(project_root)
    if not pip_config.get("enable_pip_install", True):
        warn(project_root, "pip install is disabled by config/pip_config.json")
        return

    if install_from_local_wheels(project_root, requirements) or install_from_indexes(
        project_root,
        requirements,
        pip_config,
    ):
        write_requirements_marker(project_root, digest)
        return

    warn(project_root, "Python dependencies were not installed successfully")


def needs_requirement_install(project_root: Path, digest: str) -> bool:
    if is_package_installed("maafw") and not is_running_in_project_venv(project_root):
        log(project_root, "maafw is already installed in current Python")
        return False

    marker = requirements_marker(project_root)
    if marker.exists() and marker.read_text(encoding="utf8").strip() == digest:
        if is_package_installed("maafw"):
            log(project_root, "Python requirements are already installed")
            return False
    return True


def requirements_marker(project_root: Path) -> Path:
    if is_running_in_project_venv(project_root):
        return venv_dir(project_root) / REQUIREMENTS_MARKER
    return project_root / "debug" / REQUIREMENTS_MARKER


def write_requirements_marker(project_root: Path, digest: str) -> None:
    marker = requirements_marker(project_root)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(digest + "\n", encoding="utf8")
    except OSError as error:
        warn(project_root, "failed to write requirements marker: " + str(error))


def install_from_local_wheels(project_root: Path, requirements: Path) -> bool:
    deps_dir = project_root / "deps"
    if not deps_dir.exists() or not any(deps_dir.glob("*.whl")):
        log(project_root, "local deps wheels are not present")
        return False
    return run_pip(
        project_root,
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-U",
            "--no-warn-script-location",
            "--requirement",
            str(requirements),
            "--find-links",
            str(deps_dir),
            "--no-index",
        ],
        "installing Python dependencies from local wheels",
    )


def install_from_indexes(project_root: Path, requirements: Path, pip_config: dict[str, Any]) -> bool:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-U",
        "--no-warn-script-location",
        "--requirement",
        str(requirements),
    ]
    mirror = str(pip_config.get("mirror") or "").strip()
    backup_mirror = str(pip_config.get("backup_mirror") or "").strip()
    if mirror:
        command.extend(["-i", mirror])
    if backup_mirror:
        command.extend(["--extra-index-url", backup_mirror])
    return run_pip(project_root, command, "installing Python dependencies from indexes")


def run_pip(project_root: Path, command: list[str], label: str) -> bool:
    log(project_root, label + ": " + " ".join(command))
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf8",
            errors="replace",
        )
    except OSError as error:
        warn(project_root, label + " failed: " + str(error))
        return False

    if result.stdout.strip():
        log(project_root, label + " stdout:\n" + result.stdout.strip())
    if result.stderr.strip():
        log(project_root, label + " stderr:\n" + result.stderr.strip())
    if result.returncode != 0:
        warn(project_root, label + f" failed with exit code {result.returncode}")
        return False
    log(project_root, label + " completed")
    return True


def read_pip_config(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "config" / "pip_config.json"
    if not config_path.exists():
        return DEFAULT_PIP_CONFIG
    try:
        with config_path.open(encoding="utf8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        warn(project_root, "failed to read config/pip_config.json: " + str(error))
        return DEFAULT_PIP_CONFIG
    return value if isinstance(value, dict) else DEFAULT_PIP_CONFIG


def ensure_runtime_config(project_root: Path) -> None:
    config_dir = project_root / "config"
    config_path = config_dir / "pip_config.json"
    if config_path.exists():
        return
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(DEFAULT_PIP_CONFIG, indent=4, ensure_ascii=False) + "\n",
            encoding="utf8",
        )
        log(project_root, "created config/pip_config.json")
    except OSError as error:
        warn(project_root, "failed to create config/pip_config.json: " + str(error))


def check_maafw(project_root: Path) -> None:
    try:
        version = importlib.metadata.version("maafw")
    except importlib.metadata.PackageNotFoundError:
        warn(project_root, "Python package maafw is not installed")
        return
    log(project_root, "maafw " + version)


def is_package_installed(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def command_output(error: subprocess.CalledProcessError) -> str:
    output = []
    if error.stdout:
        output.append(str(error.stdout).strip())
    if error.stderr:
        output.append(str(error.stderr).strip())
    return "\n".join(item for item in output if item) or str(error)


def warn(project_root: Path, message: str) -> None:
    log(project_root, "WARN " + message)
    print("[WARN] " + message, file=sys.stderr)


def log(project_root: Path, message: str) -> None:
    debug_dir = project_root / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    with (debug_dir / "agent-bootstrap.log").open("a", encoding="utf8") as handle:
        handle.write(f"{timestamp} {message}\n")


def find_compatible_python() -> Path | None:
    candidates = (
        "python3.13",
        "python313",
        "python3.12",
        "python312",
        "python3.11",
        "python311",
        "python3",
        "python",
    )
    for name in candidates:
        path = shutil.which(name)
        if path is None:
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        version_str = (result.stdout or result.stderr).strip()
        m = re.search(r"(\d+)\.(\d+)", version_str)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            if (major, minor) >= PYTHON_MIN and (major, minor) < PYTHON_MAX:
                return Path(path)
    return None


if __name__ == "__main__":
    main()
