#!/usr/bin/env bash
# 我们自己在这个 PR 上还没被 resolve 的行内意见，JSON 数组输出到 stdout。
#
# 两个调用方，用途不同，别合并：
#   - `analyze` 把结果写进 $ANALYSIS_DIR 交给 agent，让它判断哪些已经被这次增量修掉；
#   - `post` 拿它当**权威**白名单，在真正 resolve 之前校验 agent 报上来的 id。
#
# post 必须自己去取，不能读 artifact 里那份：agent 对 $ANALYSIS_DIR 有写权限（沙箱根就是仓库根），
# 它能改写那份文件来放宽白名单 —— 而伪造的 id 用只读 token 就查得到。
#
# `last: 100` 而不是 `first: 100`：这个 connection 按时间正序返回，`first` 取到的是最旧的一批，
# 超过 100 条之后最近留下的线程反而进不来，也就永远收不起来，而且是静默的。
set -euo pipefail

: "${REVIEW_AUTHOR_SLUG:?REVIEW_AUTHOR_SLUG 未设}"
: "${TARGET:?TARGET 未设}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY 未设}"

gh api graphql \
    -F owner="${GITHUB_REPOSITORY%%/*}" -F name="${GITHUB_REPOSITORY##*/}" -F number="$TARGET" \
    -f query='
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) {
            reviewThreads(last: 100) {
              nodes {
                id
                isResolved
                path
                line
                comments(first: 1) { nodes { author { login } body } }
              }
            }
          }
        }
      }' \
    --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
           | select(.isResolved == false)
           | select(.comments.nodes[0].author.login == env.REVIEW_AUTHOR_SLUG)
           | {id, path, line, body: (.comments.nodes[0].body[0:300])}]'
