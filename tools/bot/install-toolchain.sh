#!/usr/bin/env bash
# 按 `setup.json` 装工具链。版本已经对上的包直接跳过（0.1 s），所以这一步能不能整段免掉冷装的
# 193 s，取决于 `~/.npm-global` 是否已经被 `.github/workflows/bot-cache.yml` 填进缓存。
set -euo pipefail

cfg=tools/bot/setup.json

while read -r key name spec binary; do
    want="$(awk -v k="$key" '$1 == k {print $2}' "$RUNNER_TEMP/versions.txt")"
    # 缺条目就报错，不要落进下面那条「看起来已经装好」的路径：`want` 空、`got` 也空时两者相等，
    # 会静默跳过安装，之后每个调用方都在缺二进制的情况下继续跑。
    if [ -z "$want" ]; then
        echo "::error::$key 不在 $RUNNER_TEMP/versions.txt 里 —— resolve-packages.sh 没跑过？"
        exit 1
    fi
    # 各二进制的版本打印格式不同 —— dsh 只打 `0.2.0-rc.2`，maafw-live 打
    # `@windsland52/maafw-live 0.3.0` —— 所以取第一个长得像版本的 token 来比对。
    got="$("$binary" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^ ]*' | head -1 || true)"
    if [ "$got" = "$want" ]; then
        echo "$binary $want already present"
    else
        npm install --global "$name@$spec"
    fi
done < <(jq -r '.packages[] | "\(.key) \(.name) \(.spec) \(.binary)"' "$cfg")

while read -r binary; do echo "$binary $("$binary" --version)"; done \
    < <(jq -r '.packages[].binary' "$cfg")
