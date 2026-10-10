# Print the "path<TAB>new-side line" pair of every line the current diff contains.
#
# GitHub only accepts an inline review comment anchored to a line the diff actually shows. A position
# that outlived its revision is rejected, and a single rejected entry fails the whole review, so the
# payload is filtered against this set before it is posted.
#
# Reads a unified diff on stdin. Prints added and context lines; deleted lines have no new-side number.
#
# git 把含非 ASCII 的路径写成八进制转义的引号形式（`core.quotePath` 默认开）：
#     +++ "b/resource/\344\270\255\346\226\207.json"
# 光剥引号不够 —— 不把这些字节还原，路径就和 review.json 里的对不上，那条评论被静默丢弃。
# 另外 `\\` 与 `\"` 也是转义，按"反斜杠后取一个字面字符"处理。
function unescape(s,    out, i, c, oct, n, k) {
    out = ""
    i = 1
    while (i <= length(s)) {
        c = substr(s, i, 1)
        if (c == "\\" && substr(s, i + 1, 1) ~ /[0-7]/ && substr(s, i + 2, 1) ~ /[0-7]/ && substr(s, i + 3, 1) ~ /[0-7]/) {
            oct = substr(s, i + 1, 3)
            n = 0
            for (k = 1; k <= 3; k++) n = n * 8 + substr(oct, k, 1)
            out = out sprintf("%c", n)
            i += 4
        } else if (c == "\\" && i < length(s)) {
            out = out substr(s, i + 1, 1)
            i += 2
        } else {
            out = out c
            i++
        }
    }
    return out
}
#
# `+++ ` 只有在**不在 hunk 里**时才是文件头：一个内容以 `++ ` 开头的新增行，在 diff 里同样写成
# `+++ …`，认成文件头会让这个 hunk 后面所有行的路径映射全错，那条评论最终被静默丢弃。
# git 的 diff 每个文件都以 `diff --git` 开头、`@@` 之前必然是头部，所以用这两个标记定位足够。
/^diff --git / {
    in_hunk = 0
    next
}
/^\+\+\+ / {
    if (in_hunk) next
    rest = substr($0, 5)
    gsub(/^"|"$/, "", rest)
    sub(/^b\//, "", rest)
    rest = unescape(rest)
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
