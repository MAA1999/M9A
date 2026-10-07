from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = PROJECT_ROOT / "tools" / "android-packaging.mjs"

FIXTURE_NAME = "releases-fixture.json"
CHAQUOPY_FIXTURE_NAME = "chaquopy-fixture.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_releases(root: Path, core: list[str], maafw: list[dict[str, object]] | None = None) -> None:
    """离线替身：resolver 改从该文件读 release 列表，不碰 GitHub API"""
    write_json(root / FIXTURE_NAME, {"core": core, "maafw": maafw or []})


def write_chaquopy(root: Path, packages: dict[str, list[str]]) -> None:
    """离线替身：resolver 改从该文件读 Chaquopy 索引的 wheel 列表，不碰网络；键缺省 = 不在索引上"""
    write_json(root / CHAQUOPY_FIXTURE_NAME, packages)


def write_repo(
    root: Path,
    *,
    pin: str | None = "5.12.3",
    declared_version: str | None = None,
    channel: str = "beta",
    display_name: str = "M9A",
    slug: str = "m9a",
    agent: bool = True,
) -> Path:
    if pin is not None:
        (root / "requirements.txt").write_text(f"# comment\nmaafw=={pin}\nloguru==0.7.3\n", encoding="utf-8")
    write_json(
        root / "maa-project.json",
        {
            "project": {"slug": slug, "displayName": display_name},
            "maafw": {"channel": channel, "version": declared_version or ""},
        },
    )
    interface: dict[str, object] = {"interface_version": 2, "name": slug, "label": display_name, "import": []}
    if agent:
        interface["agent"] = [{"child_exec": "uv", "child_args": ["run", "python", "agent/main.py"]}]
    write_json(root / "interface.json", interface)
    write_releases(
        root,
        core=[
            "3.13.14-maafw5.12.3",
            "3.13.15-maafw5.12.3",
            "3.13.15-maafw5.13.1",
            "3.12.0-maafw5.11.0",
        ],
    )
    # 默认所有包都不在索引上（= 纯 Python 包走 upstream），保证全部测试离线；
    # 需要 pillow 场景的测试自己覆写
    write_chaquopy(root, {})
    return root


def run_resolver(
    root: Path,
    output: Path | None = None,
    core_tag_env: str | None = None,
    with_fixture: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("AGENT_CORE_TAG", None)
    if core_tag_env is not None:
        env["AGENT_CORE_TAG"] = core_tag_env
    fixture = root / FIXTURE_NAME
    if with_fixture and fixture.exists():
        env["ANDROID_PACKAGING_RELEASES_FIXTURE"] = str(fixture)
    else:
        env.pop("ANDROID_PACKAGING_RELEASES_FIXTURE", None)
    chaquopy_fixture = root / CHAQUOPY_FIXTURE_NAME
    if chaquopy_fixture.exists():
        env["ANDROID_PACKAGING_CHAQUOPY_FIXTURE"] = str(chaquopy_fixture)
    else:
        env.pop("ANDROID_PACKAGING_CHAQUOPY_FIXTURE", None)
    if output is None:
        env.pop("GITHUB_OUTPUT", None)
    else:
        env["GITHUB_OUTPUT"] = str(output)
    return subprocess.run(
        ["node", str(RESOLVER)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
        timeout=60,
    )


def test_agent_project_picks_paired_core(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3")
    output = tmp_path / "github_output"

    result = run_resolver(tmp_path, output)

    assert result.returncode == 0, result.stdout + result.stderr
    written = output.read_text(encoding="utf-8")
    # 同一 maafw 配对取最新内核，client 原生库与绑定同版本
    assert "core_tag=3.13.15-maafw5.12.3" in written
    assert "maafw_tag=v5.12.3" in written
    assert "artifact_prefix=M9A" in written
    assert "has_agent=true" in written
    # fixture 的 maa-project.json 没有 ocr 段、requirements 没有 pillow
    assert "has_ocr=false" in written
    assert "chaquopy_index=https://chaquo.com/pypi-13.1/" in written
    # chaquopy fixture 为空 = 索引上没有 requirements 里的任何包，不产生降级参数
    assert "chaquopy_pins=\n" in written
    assert "::warning::" not in result.stdout


def test_requirements_bump_drives_maafw_tag(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.13.1")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "client MaaFW tag : v5.13.1" in result.stdout
    assert "agent core tag   : 3.13.15-maafw5.13.1" in result.stdout
    assert "::warning::" not in result.stdout


def test_missing_paired_core_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.14.0")

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert "maafw5.14.0" in result.stdout
    assert "5.13.1" in result.stdout  # 报错里列出现有配对


def test_agent_core_tag_override_wins(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.14.0")
    output = tmp_path / "github_output"

    # 不给 fixture：应急钉内核时不需要查 API
    result = run_resolver(tmp_path, output, core_tag_env="3.13.15-maafw5.13.0", with_fixture=False)

    assert result.returncode == 0, result.stdout + result.stderr
    written = output.read_text(encoding="utf-8")
    assert "core_tag=3.13.15-maafw5.13.0" in written
    # client 原生库跟着内核绑定走，固定版本被偏离要打 warning
    assert "maafw_tag=v5.13.0" in written
    assert "::warning::" in result.stdout


def test_broken_agent_core_tag_override_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path)

    result = run_resolver(tmp_path, core_tag_env="3.13.15", with_fixture=False)

    assert result.returncode == 1
    assert "::error::" in result.stdout


def test_declared_version_mismatch_warns_but_requirements_win(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3", declared_version="5.13.0")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "client MaaFW tag : v5.12.3" in result.stdout
    assert "::warning::" in result.stdout


def test_agent_project_requires_pinned_maafw(tmp_path: Path) -> None:
    write_repo(tmp_path, pin=None)

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert "maafw==" in result.stdout


def test_pipeline_project_uses_declared_version(tmp_path: Path) -> None:
    write_repo(tmp_path, pin=None, declared_version="5.13.0", agent=False)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "client MaaFW tag : v5.13.0" in result.stdout
    assert "has agent        : false" in result.stdout
    assert "chaquopy index   : （无 agent 运行时）" in result.stdout
    assert "::warning::" not in result.stdout


def test_pipeline_project_resolves_channel_latest(tmp_path: Path) -> None:
    maafw_releases: list[dict[str, object]] = [
        # GitHub releases 按新到旧返回，fixture 保持同序
        {"tag": "v5.15.0-beta.1", "prerelease": True},
        {"tag": "v5.14.0", "prerelease": False},
    ]

    write_repo(tmp_path, pin=None, channel="beta", agent=False)
    write_releases(tmp_path, core=[], maafw=maafw_releases)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    # beta 收 prerelease
    assert "client MaaFW tag : v5.15.0-beta.1" in result.stdout

    write_repo(tmp_path, pin=None, channel="stable", agent=False)
    write_releases(tmp_path, core=[], maafw=maafw_releases)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    # stable 不收 prerelease
    assert "client MaaFW tag : v5.14.0" in result.stdout


def test_unsafe_display_name_falls_back_to_slug(tmp_path: Path) -> None:
    write_repo(tmp_path, display_name="我的项目", slug="demo")

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "artifact prefix  : demo" in result.stdout


def test_chaquopy_pins_follow_requirements(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3")
    # requirements 里出现 pillow 才探测降级；uv export 的 --hash 续行不算新包
    (tmp_path / "requirements.txt").write_text(
        "# comment\nmaafw==5.12.3\npillow==12.3.0 \\\n    --hash=sha256:deadbeef\nloguru==0.7.3\n",
        encoding="utf-8",
    )
    # 桌面 pin 的 12.3.0 索引上没有，钉到 cp313 可用的最高版 11.0.0
    write_chaquopy(
        tmp_path,
        {
            "pillow": [
                "pillow-10.1.0-cp312-cp312-android_24_arm64_v8a.whl",
                "pillow-11.0.0-cp313-cp313-android_24_arm64_v8a.whl",
                "pillow-11.0.0-cp313-cp313-android_24_x86_64.whl",
            ],
        },
    )

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "chaquopy index   : https://chaquo.com/pypi-13.1/" in result.stdout
    assert "chaquopy pins    : --exclude pillow --require pillow==11.0.0" in result.stdout


def test_chaquopy_pins_silent_when_index_covers_pin(tmp_path: Path) -> None:
    # 桌面 pin 的版本索引上就有 cp 兼容构建时不动它——pin 只救索引装不上的版本差，
    # 索引追上桌面版本后降级行会自动消失，无需回来删表
    write_repo(tmp_path, pin="5.12.3")
    (tmp_path / "requirements.txt").write_text("maafw==5.12.3\npillow==11.0.0\n", encoding="utf-8")
    write_chaquopy(tmp_path, {"pillow": ["pillow-11.0.0-cp313-cp313-android_24_arm64_v8a.whl"]})

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "chaquopy pins    : （无需降级）" in result.stdout


def test_chaquopy_native_package_without_cp_build_fails_loudly(tmp_path: Path) -> None:
    # 索引有这个包但只有别的 CPython 线的构建：Android 上一定装不上，解析阶段就报错，
    # 不等构建中途 pip 炸。wheel 文件名里 dist 段的 - 转写成 _（PEP 427）
    write_repo(tmp_path, pin="5.12.3")
    (tmp_path / "requirements.txt").write_text("maafw==5.12.3\npydantic-core==2.20.0\n", encoding="utf-8")
    write_chaquopy(
        tmp_path,
        {"pydantic-core": ["pydantic_core-2.20.0-cp312-cp312-android_24_arm64_v8a.whl"]},
    )

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert "pydantic-core" in result.stdout
    assert "cp313" in result.stdout


def test_core_provided_packages_skip_chaquopy_probing(tmp_path: Path) -> None:
    # 内核自带包（maafw/numpy/strenum）由 build_agent_bundle.py 整包丢弃（core wins），不探测：
    # 索引上没有当前 CPython 的构建也不该报错，更不能 --require 把旧版塞回去和内核打架。
    # numpy 的 wheel 带 build tag（numpy-1.26.2-0-cp313），顺带覆盖该解析分支
    write_repo(tmp_path, pin="5.12.3")
    (tmp_path / "requirements.txt").write_text("maafw==5.12.3\nnumpy==2.5.3\npillow==12.3.0\n", encoding="utf-8")
    write_chaquopy(
        tmp_path,
        {
            "numpy": ["numpy-1.26.2-0-cp312-cp312-android_24_arm64_v8a.whl"],
            "pillow": ["pillow-11.0.0-cp313-cp313-android_24_arm64_v8a.whl"],
        },
    )

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "chaquopy pins    : --exclude pillow --require pillow==11.0.0" in result.stdout
    assert "--require numpy" not in result.stdout


def test_unknown_cpython_minor_fails_loudly(tmp_path: Path) -> None:
    # 内核换 CPython 线（如 3.14）时手维护索引表没有条目，必须报错而不是静默走错索引
    write_repo(tmp_path, pin="5.12.3")
    write_releases(tmp_path, core=["3.14.1-maafw5.12.3"])

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
    assert "Chaquopy 索引表" in result.stdout


def test_has_ocr_flag_reflects_project_config(tmp_path: Path) -> None:
    write_repo(tmp_path, pin="5.12.3")
    config = json.loads((tmp_path / "maa-project.json").read_text(encoding="utf-8"))
    config["ocr"] = {"source": "submodule"}
    write_json(tmp_path / "maa-project.json", config)

    result = run_resolver(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "has ocr (re-sync): true" in result.stdout


def test_missing_interface_fails_loudly(tmp_path: Path) -> None:
    write_repo(tmp_path)
    (tmp_path / "interface.json").unlink()

    result = run_resolver(tmp_path)

    assert result.returncode == 1
    assert "::error::" in result.stdout
