# 从 answer.md 里挑出「证据图片」引用。两个模式：
#
#   -v mode=refs   逐个打印被引用的 evidence 目标（去掉开头的 `./`，按出现顺序去重），
#                  交给发布步骤去校验体积、后缀并拼 `--attach`；读到 reference-style 定义时
#                  退出 3，让调用方知道这份正文不能按 inline 引用处理。
#   -v mode=plain  把证据图片降级成它的 alt 文本，并删掉指向 evidence/ 的 reference-style
#                  定义行 —— 附件发不出去时发这一份，正文里不会留指向本地路径的引用。
#                  降级之后仍带 `…](…evidence/…)` 的残行直接丢掉并退出 4：调用方据此关掉附图，
#                  否则 `$answer` 里那条认不出的引用会以本地路径出现在公开评论里。
#
# 跳过围栏代码块（``` / ~~~）：那是示例，不是引用，降级它会把示例改坏。
# 行内代码（`...`）不特殊对待：证据图片引用落在行内代码里的概率远低于把解析器写复杂的代价。
#
# `gh --attach` 只改写 inline 图片引用（`![alt](path)`），reference-style（`![x][id]` +
# `[id]: ./evidence/x.png`）即使传了附件也只会留下一张断图，所以这里把它们当成不支持：
# refs 模式报出来，由调用方回退到纯文本，plain 模式把定义行删掉。

function emit(target) {
    if (!(target in seen)) {
        seen[target] = 1
        print target
    }
}

# 处理一行里的 inline 图片。mode=refs 时只收集，返回什么都不用；
# mode=plain 时返回把证据图片换成 alt 文本后的那一行。
function rewrite(line,   out, i, rest, j, alt, tail, k, target, target_path, end) {
    out = ""
    while ((i = index(line, "![")) > 0) {
        out = out substr(line, 1, i - 1)
        rest = substr(line, i + 2)
        j = index(rest, "](")
        if (j == 0) return out substr(line, i)
        alt = substr(rest, 1, j - 1)
        tail = substr(rest, j + 2)
        k = index(tail, ")")
        if (k == 0) return out substr(line, i)
        target = substr(tail, 1, k - 1)
        # 目标后面可能跟着 `"title"`，只取第一段
        split(target, parts, /[ \t]/)
        target_path = parts[1]
        sub(/^\.\//, "", target_path)
        end = i + j + k + 2
        if (target_path ~ /^evidence\//) {
            if (mode == "refs") {
                emit(target_path)
            } else {
                out = out alt
            }
        } else {
            out = out substr(line, i, end - i + 1)
        }
        line = substr(line, end + 1)
    }
    return out line
}

BEGIN {
    fence = 0
    reference_style = 0
}

{
    line = $0
    if (line ~ /^[ \t]*(```|~~~)/) {
        fence = !fence
        if (mode == "plain") print line
        next
    }
    if (fence) {
        if (mode == "plain") print line
        next
    }
    # reference-style 定义行：`[id]: ./evidence/x.png`
    if (line ~ /^[ \t]*\[[^]]+\]:[ \t]*<?(\.\/)?evidence\//) {
        if (mode == "refs") reference_style = 1
        next
    }
    result = rewrite(line)
    if (mode == "plain") {
        if (result ~ /\]\([^)]*evidence\//) {
            residual = 1
            next
        }
        print result
    }
}

END {
    if (mode == "plain" && residual) {
        exit 4
    }
    if (mode == "refs" && reference_style) {
        # 走管道而不是 /dev/stderr：Windows 上的 gawk 没有这个设备文件，本仓库的开发机就是 Windows
        print "answer.md uses reference-style image references pointing at evidence/; --attach can only rewrite inline images" | "cat 1>&2"
        close("cat 1>&2")
        exit 3
    }
}
