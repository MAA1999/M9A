#!/usr/bin/env bash
# 把校验过的证据图片做成孤立 commit，推到 `refs/bot-evidence/<sha>`，把 SHA 打到 stdout。
#
# 为什么不走 `gh --attach`：GitHub 的 user-attachments 上传端点对 GitHub App installation
# token 一律 404（cli/cli#14309），而 bot 发帖身份就是 App。post 已经有 `contents: write`
#（`resolveReviewThread` 需要），推一个不在 `refs/heads` 下的隐藏 ref 是同一把权限能做、
# 且 GitHub 会把 `https://github.com/<repo>/raw/<sha>/…` 当图片渲染的路。隐藏 ref 不会进普通
# clone，也不会当成 branch 去触发 push workflow。
#
# 用法：publish-evidence.sh <分析目录> <相对路径>...
# 环境：GH_TOKEN、GITHUB_REPOSITORY；测试可设 BOT_EVIDENCE_REMOTE 指向本地裸仓库（此时不需要真 token）。
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY 未设}"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR || true
# actions/checkout 有时会把认证写进 GIT_CONFIG_COUNT；那是工作区仓库的 header，
# 套到这个临时仓库会变成两份 Authorization。
if [ -n "${GIT_CONFIG_COUNT:-}" ]; then
    i=0
    while [ "$i" -lt "$GIT_CONFIG_COUNT" ]; do
        unset "GIT_CONFIG_KEY_$i" "GIT_CONFIG_VALUE_$i"
        i=$((i + 1))
    done
    unset GIT_CONFIG_COUNT
fi
export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME="m9abot[bot]"
export GIT_AUTHOR_EMAIL="m9abot[bot]@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
# 远端 HTTPS 挂起时让 git 自己放弃，好让上层降级发纯文本，而不是吃掉整个 post job。
export GIT_HTTP_LOW_SPEED_LIMIT=1000
export GIT_HTTP_LOW_SPEED_TIME=30

root="${1:-}"
shift || true
if [ -z "$root" ] || [ ! -d "$root" ]; then
    echo "publish-evidence.sh: first argument must be the analysis directory" >&2
    exit 1
fi
if [ "$#" -eq 0 ]; then
    echo "publish-evidence.sh: no files to publish" >&2
    exit 1
fi

empty_config=$(mktemp)
work=$(mktemp -d)
export GIT_CONFIG_GLOBAL="$empty_config"
cleanup() { rm -rf "$work" "$empty_config"; }
trap cleanup EXIT

git config --file "$empty_config" --add safe.directory '*'
git config --file "$empty_config" credential.helper ""
GIT_TEMPLATE_DIR= git init --quiet "$work"
git -C "$work" config core.autocrlf false
git -C "$work" config commit.gpgsign false

# 解析后的路径必须落在分析目录里。`-f` 会跟随符号链接，相对路径没有 `..` 也可以
# 指到目录外；只 `cd dirname && pwd -P` 也跟不过文件本身的软链。
# 不用 python：Windows 上 PATH 里的 python 经常是商店安装桩，一调就失败。
canon() {
    local p
    # 优先 readlink -f：Git Bash / GNU 都给正斜杠。Windows 上 PATH 里的 realpath.exe
    # 会吐反斜杠，后面的前缀匹配就对不上。
    if p=$(readlink -f -- "$1" 2>/dev/null) && [ -n "$p" ]; then
        printf '%s\n' "${p//\\//}"
        return 0
    fi
    p=$(realpath -- "$1") || return 1
    printf '%s\n' "${p//\\//}"
}
resolve_inside() {
    local root_real src_real
    root_real=$(canon "$1") || return 1
    src_real=$(canon "$2") || return 1
    case "$src_real" in
        "$root_real"/*) printf '%s\n' "$src_real" ;;
        *) return 1 ;;
    esac
}

for rel in "$@"; do
    case "$rel" in
        "" | *..* | /* | [A-Za-z]:*)
            echo "publish-evidence.sh: refused path $rel" >&2
            exit 1
            ;;
    esac
    src="$root/$rel"
    if [ ! -e "$src" ]; then
        echo "publish-evidence.sh: missing $rel" >&2
        exit 1
    fi
    src_real=$(resolve_inside "$root" "$src") || {
        echo "publish-evidence.sh: refused path $rel" >&2
        exit 1
    }
    if [ ! -f "$src_real" ]; then
        echo "publish-evidence.sh: missing $rel" >&2
        exit 1
    fi
    dest="$work/$rel"
    mkdir -p "$(dirname "$dest")"
    cp -- "$src_real" "$dest"
    git -C "$work" add -- "$rel"
done

msg="bot evidence for ${GITHUB_REPOSITORY}"
if [ -n "${TARGET:-}" ]; then
    msg="$msg#${TARGET}"
fi
if [ -n "${GITHUB_RUN_ID:-}" ]; then
    msg="$msg run ${GITHUB_RUN_ID}"
fi
GIT_TERMINAL_PROMPT=0 git -C "$work" commit --quiet -m "$msg"
sha=$(git -C "$work" rev-parse HEAD)
ref="refs/bot-evidence/${sha}"

if [ -n "${BOT_EVIDENCE_REMOTE:-}" ]; then
    GIT_TERMINAL_PROMPT=0 git -C "$work" push --quiet "$BOT_EVIDENCE_REMOTE" "HEAD:${ref}"
else
    : "${GH_TOKEN:?GH_TOKEN 未设}"
    # git-over-https 要 Basic，不要 Bearer。写法跟 actions/checkout 一样：
    # `x-access-token:<token>` 再 base64。App installation token 也能这么推。
    auth=$(printf 'x-access-token:%s' "$GH_TOKEN" | openssl base64 -A 2>/dev/null \
        || printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')
    GIT_TERMINAL_PROMPT=0 git -C "$work" \
        -c "http.https://github.com/.extraheader=AUTHORIZATION: basic ${auth}" \
        push --quiet "https://github.com/${GITHUB_REPOSITORY}.git" "HEAD:${ref}"
fi

printf '%s\n' "$sha"
