import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AWK = PROJECT_ROOT / "tools" / "bot" / "answer-evidence.awk"
PUBLISH = PROJECT_ROOT / "tools" / "bot" / "publish-evidence.sh"
PREFIX = "https://github.com/MAA1999/M9A/raw/abc123"

# 1x1 transparent PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        pytest.skip(f"{binary} is not on PATH")
    return path


def run_awk(mode: str, source: str, prefix: str | None = None) -> subprocess.CompletedProcess[str]:
    awk = _require("awk")
    cmd = [awk, "-v", f"mode={mode}"]
    if prefix is not None:
        cmd.extend(["-v", f"prefix={prefix}"])
    cmd.extend(["-f", str(AWK)])
    return subprocess.run(
        cmd,
        input=source,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def test_refs_collects_inline_and_reference_style() -> None:
    source = """# head

![HomeFlag 未命中](./evidence/home.png)

See also ![other][shot]

```
![example](evidence/in-fence.png)
```

[shot]: evidence/other.webp "title"
![https stays](https://example.com/evidence/remote.png)
"""
    result = run_awk("refs", source)
    assert result.returncode == 0, result.stderr
    # 第一遍先吐 reference-style 定义，第二遍才扫 inline，所以 other.webp 会排在前面。
    assert result.stdout.splitlines() == ["evidence/other.webp", "evidence/home.png"]


def test_plain_downgrades_images_to_alt() -> None:
    source = "未命中：![HomeFlag](./evidence/home.png)\n"
    result = run_awk("plain", source)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "未命中：HomeFlag\n"


def test_urls_rewrites_inline_and_keeps_fences() -> None:
    source = """![HomeFlag 未命中](./evidence/home.png)

```md
![example](evidence/in-fence.png)
```

![remote](https://example.com/evidence/remote.png)
"""
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout
        == """![HomeFlag 未命中](https://github.com/MAA1999/M9A/raw/abc123/evidence/home.png)

```md
![example](evidence/in-fence.png)
```

![remote](https://example.com/evidence/remote.png)
"""
    )


def test_urls_rewrites_reference_style_and_keeps_title() -> None:
    source = '![shot][id]\n\n[id]: ./evidence/other.webp "title"\n'
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        '![shot][id]\n\n[id]: https://github.com/MAA1999/M9A/raw/abc123/evidence/other.webp "title"\n'
    )


def test_urls_requires_prefix() -> None:
    result = run_awk("urls", "![x](evidence/x.png)\n")
    assert result.returncode == 2
    assert "prefix" in result.stderr


def test_urls_rewrites_angle_bracket_definition() -> None:
    source = "![shot][id]\n\n[id]: <./evidence/home.png>\n"
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("![shot][id]\n\n[id]: <https://github.com/MAA1999/M9A/raw/abc123/evidence/home.png>\n")


def test_urls_exits_if_non_image_evidence_link_remains() -> None:
    source = "见 [原图](./evidence/home.png)\n"
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 4


def test_publish_evidence_pushes_hidden_ref(tmp_path: Path) -> None:
    bash = _require("bash")
    _require("git")
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    image = analysis / "evidence" / "home.png"
    image.write_bytes(PNG)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)

    result = subprocess.run(
        [
            bash,
            str(PUBLISH),
            str(analysis.as_posix()),
            "evidence/home.png",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GITHUB_REPOSITORY": "MAA1999/M9A",
            "TARGET": "1029",
            "BOT_EVIDENCE_REMOTE": str(remote.as_posix()),
            "GH_TOKEN": "unused",
            "GIT_TERMINAL_PROMPT": "0",
            # 模拟 actions/checkout 注入的全局 extraheader，发布脚本必须剥掉。
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic leftover",
        },
    )
    assert result.returncode == 0, result.stderr
    sha = result.stdout.strip()
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)

    listed = subprocess.run(
        ["git", "--git-dir", str(remote), "show-ref"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"refs/bot-evidence/{sha}" in listed.stdout
    blob = subprocess.run(
        ["git", "--git-dir", str(remote), "show", f"{sha}:evidence/home.png"],
        capture_output=True,
        check=True,
    )
    assert blob.stdout == PNG


def test_publish_evidence_pushes_multiple_files(tmp_path: Path) -> None:
    bash = _require("bash")
    _require("git")
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    (analysis / "evidence" / "home.png").write_bytes(PNG)
    (analysis / "evidence" / "other.webp").write_bytes(PNG)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)

    result = subprocess.run(
        [bash, str(PUBLISH), str(analysis.as_posix()), "evidence/home.png", "evidence/other.webp"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GITHUB_REPOSITORY": "MAA1999/M9A",
            "BOT_EVIDENCE_REMOTE": str(remote.as_posix()),
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    assert result.returncode == 0, result.stderr
    sha = result.stdout.strip()
    listed = subprocess.run(
        ["git", "--git-dir", str(remote), "ls-tree", "-r", "--name-only", sha],
        capture_output=True,
        text=True,
        check=True,
    )
    assert listed.stdout.splitlines() == ["evidence/home.png", "evidence/other.webp"]


def test_publish_evidence_refuses_parent_escape(tmp_path: Path) -> None:
    bash = _require("bash")
    result = subprocess.run(
        [bash, str(PUBLISH), str(tmp_path.as_posix()), "evidence/../secret.png"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "GITHUB_REPOSITORY": "MAA1999/M9A",
            "BOT_EVIDENCE_REMOTE": str((tmp_path / "remote.git").as_posix()),
        },
    )
    assert result.returncode == 1
    assert "refused path" in result.stderr
