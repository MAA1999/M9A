# Print the "path<TAB>new-side line" pair of every line the current diff contains.
#
# GitHub only accepts an inline review comment anchored to a line the diff actually shows. A position
# that outlived its revision is rejected, and a single rejected entry fails the whole review, so the
# payload is filtered against this set before it is posted.
#
# Reads a unified diff on stdin. Prints added and context lines; deleted lines have no new-side number.
#
# `+++ ` 只有在**不在 hunk 里**时才是文件头：一个内容以 `++ ` 开头的新增行，在 diff 里同样写成
# `+++ …`，认成文件头会让这个 hunk 后面所有行的路径映射全错，那条评论最终被静默丢弃。
# git 的 diff 每个文件都以 `diff --git` 开头，`@@` 之前必然是头部，所以用这两个标记定位足够。
/^diff --git / {
    in_hunk = 0
    next
}
/^\+\+\+ / {
    if (in_hunk) next
    rest = substr($0, 5)
    # 引号要先剥。git 对含非 ASCII、引号或控制字符的路径会写成 `+++ "b/…"`（`core.quotePath` 默认开），
    # 若先剥 `b/` 就匹配不上 —— 前缀留着，发布时和 review.json 的路径对不上，那条行内评论被静默丢弃。
    gsub(/^"|"$/, "", rest)
    sub(/^b\//, "", rest)
    path = (rest == "/dev/null") ? "" : rest
    next
}
/^@@/ {
    in_hunk = 1
    if (match($0, /\+[0-9]+/)) {
        n = substr($0, RSTART + 1, RLENGTH - 1) + 0
    } else {
        n = 0
    }
    next
}
path == "" { next }
/^\+/ { print path "\t" n; n++; next }
/^ / { print path "\t" n; n++; next }
