#!/usr/bin/env bash
# 把已经校验过的证据图推上隐藏 ref，探活 raw URL，再改写 answer.md。
# stdout 只打一行：该拿去发帖的正文路径（改写成功是 urls.md，否则是 plain.md）。
#
# 用法：rewrite-evidence-body.sh <分析目录> <answer.md> <plain.md> <urls.md> <相对路径>...
# 环境：GITHUB_REPOSITORY；真推送要 GH_TOKEN。测试可设 BOT_EVIDENCE_REMOTE，
#       BOT_EVIDENCE_SKIP_PROBE=1 跳过 raw 探活。
#
# 失败一律降级、退出 0：附图是结论的补充，不能挡住发帖。
#
# urls_rc 必须在 awk 之前置 0，再用 `|| urls_rc=$?` 接失败。初值写成 1 时成功路径
# 的 `||` 不会跑，下面 `[ "$urls_rc" -eq 0 ]` 永远为假，图已经推上去却仍发 plain。
set -euo pipefail

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=${1:-}
answer=${2:-}
plain=${3:-}
urls=${4:-}

if [ -z "$root" ] || [ -z "$answer" ] || [ -z "$plain" ] || [ -z "$urls" ] || [ "$#" -lt 5 ]; then
    echo "rewrite-evidence-body.sh: usage: rewrite-evidence-body.sh <analysis-dir> <answer.md> <plain.md> <urls.md> <rel>..." >&2
    if [ -n "$plain" ]; then
        printf '%s\n' "$plain"
        exit 0
    fi
    exit 1
fi
shift 4

fallback() {
    printf '%s\n' "$plain"
    exit 0
}

publish() {
    # GNU timeout 才认 `timeout 90 cmd`。Windows 的 timeout.exe 同名但语义不同，
    # `--version` 能把两者分开。本地裸仓测试也不套 —— 没有 HTTPS 可挂。
    if [ -z "${BOT_EVIDENCE_REMOTE:-}" ] && timeout --version >/dev/null 2>&1; then
        # 短于 post job 的 10 分钟，卡住也能回到 plain 把评论发出去。
        timeout 90 bash "$here/publish-evidence.sh" "$root" "$@"
    else
        bash "$here/publish-evidence.sh" "$root" "$@"
    fi
}

sha=$(publish "$@") || {
    echo "::warning::could not publish evidence images; posting without them" >&2
    fallback
}
sha=${sha//$'\r'/}
sha=${sha##*$'\n'}
if [[ ! "$sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "::warning::could not publish evidence images; posting without them" >&2
    fallback
fi

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY 未设}"
prefix="https://github.com/${GITHUB_REPOSITORY}/raw/${sha}"

urlenc_path() {
    local py
    py=$(command -v python3 || command -v python) || return 1
    "$py" -c 'import urllib.parse,sys; print("/".join(urllib.parse.quote(p, safe="") for p in sys.argv[1].split("/")))' "$1"
}

reachable=0
if [ "${BOT_EVIDENCE_SKIP_PROBE:-}" = "1" ]; then
    reachable=1
else
    for _try in 1 2 3; do
        reachable=1
        for rel in "$@"; do
            enc=$(urlenc_path "$rel") || enc="$rel"
            if ! curl -fsI -L --max-time 15 -o /dev/null "$prefix/$enc"; then
                reachable=0
                break
            fi
        done
        if [ "$reachable" -eq 1 ]; then
            break
        fi
        sleep 2
    done
fi

if [ "$reachable" -ne 1 ]; then
    enc=$(urlenc_path "$1") || enc="$1"
    echo "::warning::$prefix/$enc is not reachable; posting without evidence images" >&2
    fallback
fi

urls_rc=0
LC_ALL=C awk -v mode=urls -v prefix="$prefix" \
    -f "$here/answer-evidence.awk" "$answer" \
    > "$urls" || urls_rc=$?

if [ "$urls_rc" -eq 0 ]; then
    echo "published $# evidence image(s) at $sha" >&2
    printf '%s\n' "$urls"
else
    echo "::warning::could not rewrite evidence image URLs; posting without them" >&2
    fallback
fi
