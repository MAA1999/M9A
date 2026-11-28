#!/usr/bin/env bash
# 把 `setup.json` 里的 dsh bundle 装进 headless profile。
#
# 不走工具链缓存：profile 在 `$DSH_HOME`（工作树里），每次 checkout 都是空的；plugin add
# 只拉一个小包，比再给 profile 的 node_modules 开一条 cache 划算。
#
# 必须用 `dsh plugin --profile headless add`，不能直接 `pnpm add`：前者才会把包写进
# `dsh.profile.bundles`，否则只是普通依赖，headless 启动时不会加载那一层补丁
# （`searchProvider` 也就不会切到 exa）。
set -euo pipefail

: "${DSH_HOME:?DSH_HOME 未设}"
: "${RUNNER_TEMP:?RUNNER_TEMP 未设}"

cfg=tools/bot/setup.json
profile="$DSH_HOME/profiles/headless"

if ! command -v dsh >/dev/null; then
    echo "::error::dsh 不在 PATH 上 —— install-toolchain.sh 没跑过？"
    exit 1
fi
if ! command -v pnpm >/dev/null; then
    echo "::error::pnpm 不在 PATH 上 —— install-toolchain.sh 应当已经装好"
    exit 1
fi

# pnpm 在无 TTY 时会为清空 node_modules 卡住（ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY）。
# Actions 本来就有 CI=true，这里再钉死一次，免得哪天 job env 把它摘掉。
export CI=true

want_rows="$(jq -r '(.plugins // []) | length' "$cfg")"
if [ "$want_rows" = "0" ]; then
    echo "no profile plugins declared"
    exit 0
fi

got_rows=0
# 第三列是 setup.json 里的浮动标签，安装用的是 versions.txt 的精确版本，所以丢掉。
while read -r key name _; do
    want="$(awk -v k="$key" '$1 == k {print $2}' "$RUNNER_TEMP/versions.txt")"
    # 缺条目就报错，不要落进「看起来已经装好」：`want` 空时 `dsh plugin add pkg@` 会装成
    # 浮动标签，和 versions.txt 对不上，失败形态是搜到 DeepSeek 默认源或直接不可用。
    if [ -z "$want" ]; then
        echo "::error::$key 不在 $RUNNER_TEMP/versions.txt 里 —— resolve-packages.sh 没解析 plugins？"
        exit 1
    fi
    echo "dsh plugin --profile headless add $name@$want"
    dsh plugin --profile headless add "$name@$want"
    got_rows=$((got_rows + 1))

    if [ ! -f "$profile/package.json" ]; then
        echo "::error::plugin add 之后 $profile/package.json 仍不存在"
        exit 1
    fi
    if ! jq -e --arg n "$name" '(.dsh.profile.bundles // []) | index($n) != null' "$profile/package.json" >/dev/null; then
        echo "::error::$name 不在 headless profile 的 dsh.profile.bundles 里 —— 联网搜索不会走 Exa"
        exit 1
    fi
    got="$(jq -r --arg n "$name" '.dependencies[$n] // empty' "$profile/package.json")"
    case "$got" in
        "$want" | "^$want" | "~$want") ;;
        *)
            echo "::error::$name 装进 profile 的版本是 '$got'，期望 $want"
            exit 1
            ;;
    esac
done < <(jq -r '(.plugins // [])[] | "\(.key) \(.name) \(.spec)"' "$cfg")

if [ "$got_rows" != "$want_rows" ]; then
    echo "::error::setup.json 里有 $want_rows 个插件，只装了 $got_rows 个"
    exit 1
fi

echo "headless bundles: $(jq -r '.dsh.profile.bundles | join(", ")' "$profile/package.json")"
