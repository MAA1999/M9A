#!/usr/bin/env bash
# Runs the Agent inside a read-only copy of M9A.app, the way it lives under /Applications: the
# bundle cannot be written to, so config, debug and the manifest cache must land in the directory
# the client hands over through PI_USER_DATA_DIR. macOS only.
#
# Usage: smoke-macos-app.sh <M9A.app> <scratch-dir>
set -euo pipefail

app="${1:?usage: smoke-macos-app.sh <M9A.app> <scratch-dir>}"
scratch="${2:?usage: smoke-macos-app.sh <M9A.app> <scratch-dir>}"

rm -rf "$scratch"
mkdir -p "$scratch/bundle" "$scratch/user-data"
cp -R "$app" "$scratch/bundle/M9A.app"
# A user-installed app is owned by root/admin; a standard account cannot write inside it.
chmod -R a-w "$scratch/bundle/M9A.app"

contents="$scratch/bundle/M9A.app/Contents"
macos_dir="$contents/MacOS"
failures=0

fail() {
    echo "[ERR] $1"
    failures=$((failures + 1))
}

# The MaaFW runtime and the embedded interpreter are reached through the symlinks in Contents/MacOS,
# so loading them from there proves the bundle layout resolves the way the Agent expects.
if (cd "$macos_dir" && ./python/bin/python3 -I -c 'import sys; sys.path.insert(0, "agent"); import maafw_paths; resolved = maafw_paths.ensure_maafw_binary_path(); assert resolved, "client MaaFW runtime was not resolved"; from maa.library import Library; print("bundle import smoke passed:", Library.version(), Library.framework_libpath)'); then
    echo "[OK] bundle import smoke"
else
    fail "the Agent cannot import MaaFW from inside the bundle"
fi

set +e
(
    cd "$macos_dir"
    PI_USER_DATA_DIR="$scratch/user-data" ./python/bin/python3 -u agent/main.py 0123456789abcdef \
        > "$scratch/agent.stdout.log" 2>&1 &
    echo $! > "$scratch/agent.pid"
)
pid="$(cat "$scratch/agent.pid")"
sleep 25
agent_alive=0
kill -0 "$pid" 2>/dev/null && agent_alive=1
kill "$pid" 2>/dev/null
set -e

# Whatever the socket handshake does, the run has to reach the point where logs and config are set
# up — that is the part a read-only bundle used to break.
if [ -d "$scratch/user-data/debug/custom" ]; then
    echo "[OK] Agent logs go to PI_USER_DATA_DIR: $(ls "$scratch/user-data/debug/custom" | head -n 3 | tr '\n' ' ')"
else
    fail "the Agent did not write its logs into PI_USER_DATA_DIR"
fi

# debug/custom 在 utils.logger import 时就会创建，光看目录证明不了 Agent 真的起来了：
# 要么 stdout 里出现 AgentServer 就绪，要么 25s 后进程还活着，二者都没有说明它死在启动阶段。
if grep -q 'AgentServer started.' "$scratch/agent.stdout.log" || [ "$agent_alive" -eq 1 ]; then
    echo "[OK] Agent process reached startup inside the bundle"
else
    fail "the Agent exited before AgentServer startup (see $scratch/agent.stdout.log)"
fi

for unexpected in debug config data; do
    if [ -e "$macos_dir/$unexpected" ] && [ ! -L "$macos_dir/$unexpected" ]; then
        fail "the Agent wrote $unexpected/ into the bundle"
    fi
done

if [ "$failures" -ne 0 ]; then
    echo "[ERR] $failures macOS bundle check(s) failed"
    exit 1
fi
echo "[OK] macOS bundle runs with a read-only app and an external data directory"

chmod -R u+w "$scratch/bundle" 2>/dev/null || true
