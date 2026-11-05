# 从 answer.md 里挑出「证据图片」引用。两个模式：
#
#   -v mode=refs   逐个打印被引用的 evidence 目标（去掉开头的 `./`，按出现顺序去重），交给发布
#                  步骤校验后缀、体积与路径，再拼成 `--attach`。inline 图片和 reference-style
#                  定义都算：`gh --attach` 两种都会改写（前者改目的地，后者改定义行）。
#   -v mode=plain  把证据图片降级成 alt 文本 —— inline 图片换成 alt，reference-style 删掉定义行并
#                  把用到它的 `![alt][id]` 一并换成 alt。附件发不出去时发这一份，正文里不会留
#                  指向本地路径的引用。降级完仍残留 `…](…evidence/…)` 的行直接丢掉并退出 4。
#
# 围栏代码块按 CommonMark 规则跳过：开围栏记字符和长度，只有同字符、长度不短于开围栏、其后只剩
# 空白的行才结束它。代码块里的图片语法是示例，既不算引用，也不该被改写。

function norm(dest) {
    sub(/^\.\//, "", dest)
    return dest
}

function emit(target) {
    if (!(target in seen)) {
        seen[target] = 1
        print target
    }
}

# 行首围栏？返回它的字符重复数，0 表示不是。
function fence_open(line,   i, c, n, rest) {
    i = 1
    while (substr(line, i, 1) == " " || substr(line, i, 1) == "\t") i++
    c = substr(line, i, 1)
    if (c != "`" && c != "~") return 0
    n = 0
    while (substr(line, i + n, 1) == c) n++
    if (n < 3) return 0
    rest = substr(line, i + n)
    # backtick 围栏的信息串里不能再有 backtick，否则这行根本不是围栏
    if (c == "`" && index(rest, "`") > 0) return 0
    fence_char = c
    return n
}

function fence_close(line,   i, n, rest) {
    i = 1
    while (substr(line, i, 1) == " " || substr(line, i, 1) == "\t") i++
    if (substr(line, i, 1) != fence_char) return 0
    n = 0
    while (substr(line, i + n, 1) == fence_char) n++
    if (n < fence_len) return 0
    rest = substr(line, i + n)
    return rest ~ /^[ \t]*$/
}

# `[id]: ./evidence/x.png "title"` ？命中时把 label / 目标写进 dl / dd。
function parse_def(line,   i, j, rest, dest, k) {
    if (line !~ /^[ \t]*\[/) return 0
    i = index(line, "[")
    rest = substr(line, i + 1)
    j = index(rest, "]:")
    if (j == 0) return 0
    dl = tolower(substr(rest, 1, j - 1))
    dest = substr(rest, j + 2)
    sub(/^[ \t]+/, "", dest)
    if (substr(dest, 1, 1) == "<") {
        k = index(dest, ">")
        if (k == 0) return 0
        dest = substr(dest, 2, k - 2)
    } else {
        k = 0
        while (k < length(dest) && substr(dest, k + 1, 1) !~ /[ \t]/) k++
        dest = substr(dest, 1, k)
    }
    dd = dest
    return 1
}

# 处理一行里的图片：inline 的收集/降级，reference-style 的降级。mode=refs 时只收集。
# alt 里可能有成对的方括号（`![候选区域[1]](…)`），所以不能用第一个 `]` 当结尾 ——
# 用 `](` / `][` 这一对分隔符找图片的结束位置。
function rewrite(line,   out, i, rest, jp, jb, j, alt, tail, k, label, target, path, end) {
    out = ""
    while ((i = index(line, "![")) > 0) {
        out = out substr(line, 1, i - 1)
        rest = substr(line, i + 2)
        jp = index(rest, "](")
        jb = index(rest, "][")
        if (jp > 0 && (jb == 0 || jp < jb)) {
            tail = substr(rest, jp + 2)
            k = index(tail, ")")
            if (k == 0) return out substr(line, i)
            alt = substr(rest, 1, jp - 1)
            target = substr(tail, 1, k - 1)
            split(target, parts, /[ \t]/)
            path = norm(parts[1])
            end = i + jp + k + 2
            if (path ~ /^evidence\//) {
                if (mode == "refs") {
                    emit(path)
                } else {
                    out = out alt
                }
            } else {
                out = out substr(line, i, end - i + 1)
            }
            line = substr(line, end + 1)
            continue
        }
        if (jb > 0) {
            tail = substr(rest, jb + 2)
            k = index(tail, "]")
            if (k == 0) return out substr(line, i)
            alt = substr(rest, 1, jb - 1)
            label = substr(tail, 1, k - 1)
            if (label == "") label = alt
            end = i + jb + k + 2
            if (mode == "plain" && (tolower(label) in ref_label)) {
                out = out alt
            } else {
                out = out substr(line, i, end - i + 1)
            }
            line = substr(line, end + 1)
            continue
        }
        # `![label]` 这种 shortcut 形态：没有紧跟的目标，按首个 `]` 结尾
        j = index(rest, "]")
        if (j == 0) return out substr(line, i)
        alt = substr(rest, 1, j - 1)
        if (mode == "plain" && (tolower(alt) in ref_label)) {
            out = out alt
        } else {
            out = out substr(line, i, j + 2)
        }
        line = substr(line, i + j + 2)
    }
    return out line
}

{ pending[++total] = $0 }

END {
    # 第一遍：找 evidence 的 reference-style 定义行，记下 label 与目标。
    fence = 0
    for (i = 1; i <= total; i++) {
        line = pending[i]
        if (fence) {
            if (fence_close(line)) fence = 0
            continue
        }
        fence_len = fence_open(line)
        if (fence_len > 0) {
            fence = 1
            continue
        }
        if (!parse_def(line)) continue
        if (index(dd, "evidence/") == 0) continue
        def_line[i] = 1
        ref_label[dl] = 1
        if (mode == "refs") emit(norm(dd))
    }

    # 第二遍：refs 只收集 inline 引用；plain 输出降级后的正文。
    fence = 0
    for (i = 1; i <= total; i++) {
        line = pending[i]
        if (fence) {
            if (fence_close(line)) fence = 0
            if (mode == "plain") print line
            continue
        }
        fence_len = fence_open(line)
        if (fence_len > 0) {
            fence = 1
            if (mode == "plain") print line
            continue
        }
        if (mode == "refs") {
            rewrite(line)
            continue
        }
        if (def_line[i]) continue
        result = rewrite(line)
        if (result ~ /\]\([^)]*evidence\//) {
            residual = 1
            continue
        }
        print result
    }

    if (mode == "plain" && residual) exit 4
}
