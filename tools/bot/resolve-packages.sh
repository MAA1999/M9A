#!/usr/bin/env bash
# 解析 `setup.json` 里每个包在 registry 上的实际版本，并把工具链缓存的 key 拼出来。
#
# 两个 workflow 共用这一份：`bot.yml` 只能 restore，`.github/workflows/bot-cache.yml` 负责 save。
# 两边必须算出逐字节相同的 key —— 只要有一处格式不一致，warm 那边存进去的树就永远对不上 bot 这边
# 要找的键，而失败形态是静默的：评论照发，只是每次都退回冷装。
#
# `cacheKey` 是「版本一动就让整棵缓存树失效」的标记，只有贵包该标：小包升版本进了 key，会让
# `install-toolchain.sh` 里的版本检查连带丢掉整棵树，而它本来只会重装那一个包。
set -euo pipefail

# key 里的哈希是 workflow 里 `hashFiles('tools/bot/setup.json')` 的结果（actions/runner 在 YAML
# 求值时算的），bash 这边复刻不了，只能由调用方传进来。
: "${SETUP_HASH:?SETUP_HASH 未设 —— workflow 里应为 hashFiles('tools/bot/setup.json')}"

cfg=tools/bot/setup.json
tag=""
# jq 坏掉时下面那个进程替换只是「没有输入」：循环正常结束，key 照样拼得出来，只是少了 `cacheKey` 那一
# 段 —— 那种 key 仍然能用，但 `next` 移动后不再失效，而这层退化没有任何地方会喊出来。所以先让 jq 在
# 一条普通的命令替换里跑一次：它坏就当场退出，不必等那个静默的空循环。
want_rows="$(jq -r '.packages | length' "$cfg")"
got_rows=0
# `install-toolchain.sh` 靠它把「想要哪个版本」和「装完之后核对什么」对上，两个脚本必须读同一份。
: > "$RUNNER_TEMP/versions.txt"

while read -r key name spec inKey; do
    version="$(npm view "$name@$spec" version)"
    echo "$key $version" >> "$RUNNER_TEMP/versions.txt"
    echo "  $name@$spec -> $version"
    if [ "$inKey" = "true" ]; then
        tag="$tag$key-$version-"
    fi
    got_rows=$((got_rows + 1))
done < <(jq -r '.packages[] | "\(.key) \(.name) \(.spec) \(.cacheKey // false)"' "$cfg")

# 行数对不上就一个字符都不写：key 缺少 `cacheKey` 段不会让任何一步失败，只会让缓存悄悄不再随版本失效。
if [ "$got_rows" != "$want_rows" ]; then
    echo "::error::setup.json 里有 $want_rows 个包，只解析出 $got_rows 个"
    exit 1
fi

echo "cache_key=bot-${RUNNER_OS}-${SETUP_HASH}-${tag%-}" >> "$GITHUB_OUTPUT"
