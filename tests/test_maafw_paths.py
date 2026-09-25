import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent.maafw_paths import (
    ENV_NAME,
    candidate_library_dirs,
    ensure_maafw_binary_path,
    find_maafw_library_dir,
    library_names,
    runtime_platform_tag,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_maafw_env() -> Iterator[None]:
    """每个用例都从"未设置"开始，结束后也不留下变量。

    ``ensure_maafw_binary_path`` 直接写 ``os.environ``，而 monkeypatch 只对"删除前已存在"的键记录还原项：
    变量原本不存在时，用例里写进去的值会活到整个测试会话结束，后面跑子进程的用例会连它一起继承，
    断言随之漂移。这里显式接管，顺带把开发机 shell 里原有的值还原回去。
    """
    original = os.environ.pop(ENV_NAME, None)
    yield
    os.environ.pop(ENV_NAME, None)
    if original is not None:
        os.environ[ENV_NAME] = original


def make_native_dir(root: Path, relative: str, names: tuple[str, ...]) -> Path:
    directory = root / relative
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"lib")
    return directory


def current_names() -> tuple[str, str]:
    names = library_names()
    if names is None:  # pragma: no cover - 只有 win/linux/macos 会跑测试
        pytest.skip(f"unsupported platform: {sys.platform}")
    return names


def current_native_relative() -> str:
    tag = runtime_platform_tag()
    assert tag is not None
    return f"runtimes/{tag}/native"


def test_helper_import_does_not_pull_in_maa() -> None:
    # utils 包在导入时就连带 import maa，会当场把库目录定死，所以这个模块不能挂在 utils 下
    code = (
        "import sys; sys.path.insert(0, 'agent'); "
        "import maafw_paths; "
        "maafw_paths.ensure_maafw_binary_path(); "
        "print('maa' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "导入 maafw_paths 不能把 maa 一起拖进来"


def test_main_resolves_native_runtime_before_importing_maa(tmp_path: Path) -> None:
    # 模拟瘦身后的发行包：客户端那份原生库在 runtimes/<tag>/native，agent 侧不再自带
    package = tmp_path
    shutil.copytree(PROJECT_ROOT / "agent", package / "agent", ignore=shutil.ignore_patterns("__pycache__"))
    native = make_native_dir(package, current_native_relative(), current_names())

    code = (
        "import os, runpy; "
        "runpy.run_path('agent/main.py', run_name='import_only'); "
        "from maa.library import Library; "
        "print('M9A_ENV=' + str(os.environ.get('MAAFW_BINARY_PATH'))); "
        "print('M9A_LIB=' + str(Library.framework_libpath))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=package,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    reported: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("M9A_"):
            key, _, value = line.partition("=")
            reported[key] = value

    # 断言子进程自己的环境与加载结果：父进程看子进程的 environ 永远看不出问题
    assert Path(reported["M9A_ENV"]) == native, "子进程应当把 MAAFW_BINARY_PATH 指到宿主那份"
    assert Path(reported["M9A_LIB"]) == native / current_names()[0]


def test_runtime_platform_tag_follows_platform_and_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        ("win32", "AMD64", "win-x64"),
        ("win32", "ARM64", "win-arm64"),
        ("linux", "x86_64", "linux-x64"),
        ("linux", "aarch64", "linux-arm64"),
        ("darwin", "arm64", "osx-arm64"),
        ("darwin", "x86_64", "osx-x64"),
    ]
    for platform_name, machine, expected in cases:
        monkeypatch.setattr(sys, "platform", platform_name)
        monkeypatch.setattr(platform, "machine", lambda machine=machine: machine)
        assert runtime_platform_tag() == expected


def test_runtime_platform_tag_rejects_unknown_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "freebsd")
    monkeypatch.setattr(platform, "machine", lambda: "riscv64")

    assert runtime_platform_tag() is None


def test_candidate_dirs_cover_all_package_layouts(tmp_path: Path) -> None:
    candidates = candidate_library_dirs(tmp_path)

    assert candidates[0] == tmp_path / current_native_relative()
    assert candidates[1] == tmp_path / "maafw"
    assert candidates[-1] == tmp_path


def test_find_maafw_library_dir_requires_both_libraries(tmp_path: Path) -> None:
    framework, agent_server = current_names()
    relative = current_native_relative()

    make_native_dir(tmp_path, relative, (framework,))
    assert find_maafw_library_dir(tmp_path) is None, "只有框架库时不该认定可用"

    make_native_dir(tmp_path, relative, (agent_server,))
    assert find_maafw_library_dir(tmp_path) == tmp_path / relative


def test_find_maafw_library_dir_prefers_runtimes_native_layout(tmp_path: Path) -> None:
    preferred = make_native_dir(tmp_path, current_native_relative(), current_names())
    make_native_dir(tmp_path, "maafw", current_names())

    assert find_maafw_library_dir(tmp_path) == preferred


def test_find_maafw_library_dir_falls_back_to_maafw_dir_layout(tmp_path: Path) -> None:
    expected = make_native_dir(tmp_path, "maafw", current_names())

    assert find_maafw_library_dir(tmp_path) == expected


def test_find_maafw_library_dir_falls_back_to_flat_root_layout(tmp_path: Path) -> None:
    # CLI 壳（MaaPiCli）的包：库平铺在包根
    make_native_dir(tmp_path, ".", current_names())

    assert find_maafw_library_dir(tmp_path) == tmp_path


def test_find_maafw_library_dir_prefers_client_layout_over_flat_root(tmp_path: Path) -> None:
    # 顺序保证：客户端布局（runtimes-native / maafw 子目录）命中在前，平铺根只在没有更优候选时兜底
    preferred = make_native_dir(tmp_path, current_native_relative(), current_names())
    make_native_dir(tmp_path, ".", current_names())

    assert find_maafw_library_dir(tmp_path) == preferred


def test_ensure_maafw_binary_path_points_at_packaged_runtime(tmp_path: Path) -> None:
    expected = make_native_dir(tmp_path, current_native_relative(), current_names())

    assert ensure_maafw_binary_path(tmp_path) == expected
    assert os.environ[ENV_NAME] == str(expected)


def test_ensure_maafw_binary_path_ignores_empty_packaged_dir(tmp_path: Path) -> None:
    # 开发机现状：runtimes/<tag>/native 存在但是空的（要 pnpm sync:runtime 才有内容）。
    # 指过去要到第一次建 Tasker 时才炸 Could not find module，必须在 import maa 之前就放弃。
    (tmp_path / current_native_relative()).mkdir(parents=True)

    assert ensure_maafw_binary_path(tmp_path) is None
    assert ENV_NAME not in os.environ


def test_ensure_maafw_binary_path_keeps_injected_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Android runner 把变量指向 APK 的 nativeLibraryDir，与桌面的 runtimes/ 布局无关
    injected = tmp_path / "nativeLibraryDir"
    monkeypatch.setenv(ENV_NAME, str(injected))
    make_native_dir(tmp_path, "maafw", current_names())

    assert ensure_maafw_binary_path(tmp_path) == injected
    assert os.environ[ENV_NAME] == str(injected)


def test_ensure_maafw_binary_path_accepts_str_project_root(tmp_path: Path) -> None:
    expected = make_native_dir(tmp_path, current_native_relative(), current_names())

    assert ensure_maafw_binary_path(str(tmp_path)) == expected


def test_ensure_maafw_binary_path_returns_none_without_any_runtime(tmp_path: Path) -> None:
    assert ensure_maafw_binary_path(tmp_path) is None
    assert ENV_NAME not in os.environ
