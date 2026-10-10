#!/usr/bin/env node
// 汇总 dsh 会话日志里的 token 用量。
//
// 会话是 zstd **多帧**文件（每次追加一帧，实测一个会话三万多帧），而 Node 的
// `zstdDecompressSync` 只解第一帧 —— 所以必须先按 frame magic 切开逐帧解，否则只能拿到
// 头部，看起来像「日志里没有用量」。
//
// 用量记在 `assistant/chunk` 事件里，形如：
//   {"type":"assistant/chunk","data":{"step":1,"chunk":{"type":"usage",
//     "usage":{"inputTokens":396,"outputTokens":6479,"cacheReadTokens":12352,"reasoningTokens":6317}}}}
//
// 用法：node session-usage.mjs <sessions 目录> [输出 json 路径]
import {readFileSync, readdirSync, statSync, writeFileSync} from "node:fs";
import {zstdDecompressSync} from "node:zlib";
import {join} from "node:path";

const MAGIC = Buffer.from([
    0x28,
    0xb5,
    0x2f,
    0xfd,
]);

/** 按 zstd frame magic 切开逐帧解压，坏帧跳过而不是整体失败。 */
function decompressFrames(buf) {
    const starts = [];
    for (let i = 0, k = buf.indexOf(MAGIC); k >= 0; k = buf.indexOf(MAGIC, i)) {
        starts.push(k);
        i = k + MAGIC.length;
    }
    const parts = [];
    for (let n = 0; n < starts.length; n++) {
        const end = n + 1 < starts.length ? starts[n + 1] : buf.length;
        try {
            parts.push(zstdDecompressSync(buf.subarray(starts[n], end)));
        } catch {
            // 尾部可能有一帧写了一半，忽略它，不要把整份统计丢掉。
        }
    }
    return {frames: starts.length, text: Buffer.concat(parts).toString("utf8")};
}

function walk(dir, out = []) {
    let entries;
    try {
        entries = readdirSync(dir, {withFileTypes: true});
    } catch {
        return out;
    }
    for (const e of entries) {
        const p = join(dir, e.name);
        if (e.isDirectory()) walk(p, out);
        else if (e.name.endsWith(".jsonl.zstd")) out.push(p);
    }
    return out;
}

const root = process.argv[2];
if (!root) {
    console.error("用法: node session-usage.mjs <sessions 目录> [输出 json 路径]");
    process.exit(2);
}

// 用量在两个地方出现过，取决于会话是怎么产生的：
//   - `assistant/chunk` → `data.chunk.usage`：流式增量，本机交互式会话走这条；
//   - `assistant/message` → `data.usage`：聚合后的整条消息，CI 的 headless 会话只有这条。
// 同一步两处都可能有值，所以按 (turn, step) 去重而不是直接相加 —— 相加会把用量翻倍。
function usageOf(ev) {
    if (ev.type === "assistant/chunk" && ev.data?.chunk?.type === "usage") {
        return {key: `${ev.data.turn}:${ev.data.step}`, usage: ev.data.chunk.usage, final: false};
    }
    if (ev.type === "assistant/message" && ev.data?.usage) {
        return {key: `${ev.data.turn}:${ev.data.step}`, usage: ev.data.usage, final: true};
    }
    return null;
}

const sessions = [];
const total = {inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, reasoningTokens: 0};
const rootTotal = {inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, reasoningTokens: 0};
let rootSteps = 0;
const unreadable = [];

for (const file of walk(root)) {
    let text;
    let frames = 0;
    try {
        ({text, frames} = decompressFrames(readFileSync(file)));
    } catch (e) {
        // 不静默跳过：读不到就说出来，否则「0 个会话」和「真的没有会话」分不开。
        unreadable.push(`${file}: ${e.message}`);
        continue;
    }
    const perStep = new Map();
    let id = null;
    let cwd = null;
    let parent = null;
    for (const line of text.split("\n")) {
        if (!line.trim()) continue;
        let ev;
        try {
            ev = JSON.parse(line);
        } catch {
            continue;
        }
        if (ev.type === "session") {
            id ??= ev.id;
            cwd ??= ev.cwd;
            parent ??= ev.parentSession ?? null;
            continue;
        }
        const hit = usageOf(ev);
        if (!hit) continue;
        // 聚合消息覆盖增量的值：同一步若两者都在，以聚合那条为准。
        if (hit.final || !perStep.has(hit.key)) perStep.set(hit.key, hit.usage);
    }
    if (perStep.size === 0) continue;

    const sum = {inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, reasoningTokens: 0};
    for (const u of perStep.values()) {
        for (const k of Object.keys(sum)) sum[k] += u[k] ?? 0;
    }
    const steps = perStep.size;
    for (const k of Object.keys(total)) total[k] += sum[k];
    // 子会话的日志里带着父会话的种子（同一个 session 内容会出现两次），把两者都算进去会重复计数 ——
    // 所以合计只取根会话。
    if (!parent) {
        for (const k of Object.keys(rootTotal)) rootTotal[k] += sum[k];
        rootSteps += steps;
    }
    sessions.push({id, parent, file: file.slice(root.length + 1), frames, steps, ...sum});
}

const report = {
    sessions: sessions.length,
    steps: sessions.reduce((n, s) => n + s.steps, 0),
    // 只含根会话 —— 这个才是实际消耗，另一个会把子会话里种入的父日志再算一遍。
    root: {sessions: sessions.filter((s) => !s.parent).length, steps: rootSteps, total: rootTotal},
    total,
    unreadable,
    detail: sessions.sort((a, b) => b.inputTokens + b.outputTokens - (a.inputTokens + a.outputTokens)),
};

const fmt = (n) => n.toLocaleString("en-US");
const line = (label, steps, t) =>
    `${label.padEnd(24)} ${String(steps).padStart(5)} 步  ` +
    `in ${fmt(t.inputTokens).padStart(11)}  out ${fmt(t.outputTokens).padStart(9)}  ` +
    `cache-read ${fmt(t.cacheReadTokens).padStart(11)}  reasoning ${fmt(t.reasoningTokens).padStart(9)}`;

console.log(line(`根会话 ${report.root.sessions} 个`, report.root.steps, report.root.total));
console.log(line(`全部 ${report.sessions} 个（含子会话）`, report.steps, report.total));
console.log("");
for (const s of report.detail) {
    console.log(
        `  ${(s.id ?? s.file).slice(0, 36).padEnd(38)}${s.parent ? " [子]" : "     "} ${String(s.steps).padStart(4)} 步  ` +
            `in ${fmt(s.inputTokens).padStart(9)}  out ${fmt(s.outputTokens).padStart(8)}  ` +
            `cache-read ${fmt(s.cacheReadTokens).padStart(9)}  reasoning ${fmt(s.reasoningTokens).padStart(8)}`,
    );
}

if (unreadable.length) {
    console.log(`\n读不到的会话 ${unreadable.length} 个：`);
    unreadable.slice(0, 5).forEach((u) => console.log(`  ${u}`));
}

if (process.argv[3]) {
    writeFileSync(process.argv[3], JSON.stringify(report, null, 4) + "\n");
    console.log(`已写出 ${process.argv[3]}`);
}
