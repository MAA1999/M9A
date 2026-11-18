import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AWK = PROJECT_ROOT / "tools" / "bot" / "answer-evidence.awk"
PUBLISH = PROJECT_ROOT / "tools" / "bot" / "publish-evidence.sh"
REWRITE = PROJECT_ROOT / "tools" / "bot" / "rewrite-evidence-body.sh"
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
        encoding="utf-8",
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def _git_posix() -> str:
    return Path(_require("git")).resolve().as_posix()


def _run_publish(
    analysis: Path,
    files: list[str],
    remote: Path | None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bash = _require("bash")
    _require("git")
    merged = {
        **os.environ,
        "GITHUB_REPOSITORY": "MAA1999/M9A",
        "GIT_TERMINAL_PROMPT": "0",
        "GH_TOKEN": "unused",
    }
    if remote is not None:
        merged["BOT_EVIDENCE_REMOTE"] = str(remote.as_posix())
    if env:
        merged.update(env)
    return subprocess.run(
        [bash, str(PUBLISH), str(analysis.as_posix()), *files],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=merged,
    )


def _init_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return remote


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


def test_urls_keeps_quoted_title_with_parens() -> None:
    source = '![x](evidence/x.png "旧图 (A)") 还有正文\n'
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ('![x](https://github.com/MAA1999/M9A/raw/abc123/evidence/x.png "旧图 (A)") 还有正文\n')


def test_urls_encodes_hash_in_path() -> None:
    source = "![x](evidence/shot#2.png)\n"
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "![x](https://github.com/MAA1999/M9A/raw/abc123/evidence/shot%232.png)\n"


def test_urls_ignores_evidence_in_definition_title() -> None:
    source = '[id]: evidence/x.png "示例 ](evidence/example.png)"\n\n![x][id]\n'
    result = run_awk("urls", source, prefix=PREFIX)
    assert result.returncode == 0, result.stderr
    assert "https://github.com/MAA1999/M9A/raw/abc123/evidence/x.png" in result.stdout
    assert '"示例 ](evidence/example.png)"' in result.stdout


def test_publish_evidence_pushes_hidden_ref(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    (analysis / "evidence" / "home.png").write_bytes(PNG)
    remote = _init_remote(tmp_path)

    result = _run_publish(
        analysis,
        ["evidence/home.png"],
        remote,
        env={
            "TARGET": "1029",
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
        encoding="utf-8",
        check=True,
    )
    assert f"refs/bot-evidence/{sha}" in listed.stdout
    blob = subprocess.run(
        ["git", "--git-dir", str(remote), "show", f"{sha}:evidence/home.png"],
        capture_output=True,
        check=True,
    )
    assert blob.stdout == PNG


def test_publish_evidence_unsets_checkout_git_config(tmp_path: Path) -> None:
    bash = _require("bash")
    git = _git_posix()
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    (analysis / "evidence" / "home.png").write_bytes(PNG)
    remote = _init_remote(tmp_path)
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        'if [ -n "${GIT_CONFIG_COUNT:-}" ]; then\n'
        '  echo "GIT_CONFIG_COUNT leaked" >&2\n'
        "  exit 99\n"
        "fi\n"
        f'exec "{git}" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    result = subprocess.run(
        [bash, str(PUBLISH), str(analysis.as_posix()), "evidence/home.png"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={
            **os.environ,
            "PATH": str(wrapper_dir) + os.pathsep + os.environ["PATH"],
            "GITHUB_REPOSITORY": "MAA1999/M9A",
            "BOT_EVIDENCE_REMOTE": str(remote.as_posix()),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic leftover",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "GIT_CONFIG_COUNT leaked" not in result.stderr


def test_publish_evidence_pushes_multiple_files(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    (analysis / "evidence" / "home.png").write_bytes(PNG)
    (analysis / "evidence" / "other.webp").write_bytes(PNG)
    remote = _init_remote(tmp_path)

    result = _run_publish(analysis, ["evidence/home.png", "evidence/other.webp"], remote)
    assert result.returncode == 0, result.stderr
    sha = result.stdout.strip()
    listed = subprocess.run(
        ["git", "--git-dir", str(remote), "ls-tree", "-r", "--name-only", sha],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert listed.stdout.splitlines() == ["evidence/home.png", "evidence/other.webp"]


def test_publish_evidence_refuses_parent_escape(tmp_path: Path) -> None:
    _require("git")
    result = _run_publish(tmp_path, ["evidence/../secret.png"], tmp_path / "remote.git")
    assert result.returncode == 1
    assert "refused path" in result.stderr


def test_publish_evidence_refuses_symlink_outside(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    link = analysis / "evidence" / "home.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not permitted")
    remote = _init_remote(tmp_path)
    result = _run_publish(analysis, ["evidence/home.png"], remote)
    assert result.returncode == 1
    assert "refused path" in result.stderr


def _run_rewrite(
    analysis: Path,
    answer: Path,
    plain: Path,
    urls: Path,
    files: list[str],
    remote: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bash = _require("bash")
    _require("git")
    env = {
        **os.environ,
        "GITHUB_REPOSITORY": "MAA1999/M9A",
        "BOT_EVIDENCE_REMOTE": str(remote.as_posix()),
        "BOT_EVIDENCE_SKIP_PROBE": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GH_TOKEN": "unused",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            bash,
            str(REWRITE),
            str(analysis.as_posix()),
            str(answer.as_posix()),
            str(plain.as_posix()),
            str(urls.as_posix()),
            *files,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )


def test_rewrite_evidence_body_success_uses_urls(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    (analysis / "evidence" / "home.png").write_bytes(PNG)
    answer = analysis / "answer.md"
    answer.write_text("![HomeFlag](./evidence/home.png)\n", encoding="utf-8")
    plain = tmp_path / "plain.md"
    plain.write_text("HomeFlag\n", encoding="utf-8")
    urls = tmp_path / "urls.md"
    remote = _init_remote(tmp_path)

    result = _run_rewrite(analysis, answer, plain, urls, ["evidence/home.png"], remote)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(urls.as_posix())
    body = urls.read_text(encoding="utf-8")
    assert "https://github.com/MAA1999/M9A/raw/" in body
    assert "evidence/home.png" in body
    assert "HomeFlag" in body
    assert "published 1 evidence image(s)" in result.stderr


def test_rewrite_evidence_body_publish_failure_keeps_plain(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    answer = analysis / "answer.md"
    answer.write_text("![x](./evidence/home.png)\n", encoding="utf-8")
    plain = tmp_path / "plain.md"
    plain.write_text("x\n", encoding="utf-8")
    urls = tmp_path / "urls.md"
    remote = _init_remote(tmp_path)

    result = _run_rewrite(analysis, answer, plain, urls, ["evidence/missing.png"], remote)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(plain.as_posix())
    assert "could not publish" in result.stderr
    assert not urls.exists() or urls.read_text(encoding="utf-8") == ""


def test_rewrite_evidence_body_residual_link_keeps_plain(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis"
    (analysis / "evidence").mkdir(parents=True)
    (analysis / "evidence" / "home.png").write_bytes(PNG)
    answer = analysis / "answer.md"
    answer.write_text(
        "![x](./evidence/home.png)\n\n见 [原图](./evidence/home.png)\n",
        encoding="utf-8",
    )
    plain = tmp_path / "plain.md"
    plain.write_text("x\n见 原图\n", encoding="utf-8")
    urls = tmp_path / "urls.md"
    remote = _init_remote(tmp_path)

    result = _run_rewrite(analysis, answer, plain, urls, ["evidence/home.png"], remote)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(plain.as_posix())
    assert "could not rewrite" in result.stderr
