# Print the "path<TAB>new-side line" pair of every line the current diff contains.
#
# GitHub only accepts an inline review comment anchored to a line the diff actually shows. A position
# that outlived its revision is rejected, and a single rejected entry fails the whole review, so the
# payload is filtered against this set before it is posted.
#
# Reads a unified diff on stdin. Prints added and context lines; deleted lines have no new-side number.
/^\+\+\+ / {
    rest = substr($0, 5)
    sub(/^b\//, "", rest)
    gsub(/^"|"$/, "", rest)
    path = (rest == "/dev/null") ? "" : rest
    next
}
/^@@/ {
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
