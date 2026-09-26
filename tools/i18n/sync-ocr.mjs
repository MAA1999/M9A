// OCR expected 五语展开与校验（契约见 docs/*/develop/runtime-text-i18n.md）。
//
//   node tools/i18n/sync-ocr.mjs            原地写回 resource/base/pipeline
//   node tools/i18n/sync-ocr.mjs --check    dry-run：有未展开/未收录文本则失败（pnpm check 用）
//
// 映射表 tools/i18n/ocr_text.json：texts 以归一化简中原文为键，值为 tw/en/jp/kr
//（每种语言可为字符串或候选数组，展开时全部进入 expected）；node_overrides 按节点
// 覆盖整行；untranslatable 是刻意保留单语的正则/截断片段。英文在展开时统一转为
// (?i) + 词间 \s* 的宽松正则。JSONC 感知：经 jsonc-parser 语法树偏移原位替换，
// 注释与排版保留，重复运行幂等。
import {readFileSync, writeFileSync, readdirSync} from "node:fs";
import {join} from "node:path";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {parseTree} = require("jsonc-parser");

const CHECK = process.argv.includes("--check");
const PIPELINE_DIR = "resource/base/pipeline";
const MAPPING_FILE = "tools/i18n/ocr_text.json";
const SCREEN_WIDTH = 1280;
const SKIP_MARKER = "@i18n-skip";
const CJK = /[Ⅰ-ⅿ⺀-⻿　-〿㐀-䶿一-鿿豈-﫿＀-￯]/;

// ---------------------------------------------------------------- 映射表

const mapping = JSON.parse(readFileSync(MAPPING_FILE, "utf8"));
const {texts, node_overrides: nodeOverrides, untranslatable} = mapping;
const untranslatableSet = new Set(untranslatable);

function normalizeText(text) {
    return text.replace(/\r\n?/g, "\n").trim().replace(/\s+/g, " ");
}

function escapeRegexLiteral(text) {
    return text.replace(/[\\.^$*+?{}[\]|()]/g, "\\$&");
}

// 英文转 (?i) 忽略大小写、词间空格放宽为 \s* 的宽松正则
function englishOcrRegex(text) {
    const tokens = text.match(/[A-Za-z0-9]+|[^A-Za-z0-9\s]+/g);
    return tokens ? `(?i)${tokens.map(escapeRegexLiteral).join("\\s*")}` : "";
}

function asList(value) {
    if (value === undefined || value === null || value === "") return [];
    return Array.isArray(value) ? value.filter((v) => v) : [value];
}

// 一行映射 -> expected 五语数组（zh 即键本身，跨语种去重，缺失语种跳过）
function expandRow(zh, row, raw = false) {
    const out = [];
    const seen = new Set();
    const push = (value) => {
        if (value && !seen.has(value)) {
            seen.add(value);
            out.push(value);
        }
    };
    push(zh);
    // MaaFW 把 expected 项按正则校验/匹配，映射值来自官方纯文本，统一转义；
    // 英文另走 (?i) 宽松正则（内部已转义）。raw=true 用于识别历史版本的产物。
    for (const value of asList(row.tw)) push(raw ? value : escapeRegexLiteral(value));
    for (const value of asList(row.en)) push(englishOcrRegex(value));
    for (const value of asList(row.jp)) push(raw ? value : escapeRegexLiteral(value));
    for (const value of asList(row.kr)) push(raw ? value : escapeRegexLiteral(value));
    return out;
}

function lookupRow(nodeName, zh) {
    const override = nodeOverrides[nodeName];
    const rows = Array.isArray(override) ? override : override ? [override] : [];
    for (const row of rows) {
        if (row.zh === zh) return row;
    }
    return texts[zh] ?? null;
}

// ---------------------------------------------------------------- 显示宽度

// 宽字符（CJK/假名/谚文/全角）按 2 列计，近似 east_asian_width 的 W/F
const WIDE =
    /[\u1100-\u115F\u2E80-\u303E\u3041-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA000-\uA4CF\uA960-\uA97F\uAC00-\uD7A3\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/;

function displayWidth(text) {
    let width = 0;
    for (const ch of text) width += WIDE.test(ch) ? 2 : 1;
    return width;
}

// ---------------------------------------------------------------- JSONC 定位

function prop(objNode, key) {
    for (const member of objNode.children ?? []) {
        if (member.children?.[0]?.value === key) return member.children?.[1];
    }
    return undefined;
}

// 返回成员节点（含 key 与 value），prop() 只返回值节点
function propMember(objNode, key) {
    for (const member of objNode.children ?? []) {
        if (member.children?.[0]?.value === key) return member;
    }
    return undefined;
}

// expected 位置：recognition.param.expected -> recognition.expected -> 节点级
function locateExpected(root, nodeName, body) {
    const rec = prop(body, "recognition");
    let isOcr = false;
    let expectedMember;
    let param;
    if (rec?.type === "string" && rec.value === "OCR") {
        isOcr = true;
    } else if (rec?.type === "object") {
        if (prop(rec, "type")?.value === "OCR") {
            isOcr = true;
            param = prop(rec, "param");
            if (param?.type === "object") expectedMember = propMember(param, "expected");
            if (!expectedMember) expectedMember = propMember(rec, "expected");
        }
    }
    if (!expectedMember) expectedMember = propMember(body, "expected");
    const expected = expectedMember?.children?.[1];
    if (!isOcr || !expected || (expected.type !== "string" && expected.type !== "array")) {
        return {};
    }
    return {
        expected,
        expectedKey: expectedMember.children[0],
    };
}

// roi 生效值 =（roi 数字数组，或引用节点的生效 roi）叠加本节点 roi_offset。
// 返回 { values, offsetNode, anchorNode }：offsetNode 是本节点的 roi_offset 数组
// 成员（扩宽时原位重写）；没有 offsetNode 时用 anchorNode（本节点的 roi 成员，
// 在其值后插入 roi_offset）。字符串引用只借被引用节点的数值，编辑永远落在本节点，
// 否则会改坏共享引用的节点。
function resolveRoi(root, nodeName, body, visiting = new Set()) {
    if (visiting.has(nodeName)) return null;
    visiting.add(nodeName);
    const rec = prop(body, "recognition");
    const param = rec?.type === "object" ? prop(rec, "param") : undefined;
    let roiMember = param?.type === "object" ? prop(param, "roi") : undefined;
    let offsetMember = param?.type === "object" ? prop(param, "roi_offset") : undefined;
    if (!roiMember) {
        roiMember = prop(body, "roi");
        offsetMember = prop(body, "roi_offset");
    }
    if (!roiMember) return null;

    let base;
    if (roiMember.type === "string") {
        const ref = root.children?.find((member) => member.children?.[0]?.value === roiMember.value)?.children?.[1];
        if (ref?.type !== "object") return null;
        const resolved = resolveRoi(root, roiMember.value, ref, visiting);
        if (!resolved) return null;
        base = resolved.values;
    } else if (
        roiMember.type === "array" &&
        (roiMember.children?.length ?? 0) === 4 &&
        roiMember.children.every((n) => typeof n.value === "number")
    ) {
        base = roiMember.children.map((n) => n.value);
    } else {
        return null;
    }

    if (
        offsetMember?.type === "array" &&
        (offsetMember.children?.length ?? 0) === 4 &&
        offsetMember.children.every((n) => typeof n.value === "number")
    ) {
        const off = offsetMember.children.map((n) => n.value);
        return {values: base.map((v, i) => v + off[i]), offsetNode: offsetMember, anchorNode: roiMember};
    }
    return {values: base, offsetNode: undefined, anchorNode: roiMember};
}

function lineIndent(text, offset) {
    const lineStart = text.lastIndexOf("\n", offset - 1) + 1;
    const indent = text.slice(lineStart).match(/^[ \t]*/);
    return indent ? indent[0] : "";
}

function buildArrayText(values, indent) {
    const inner = values.map((v) => `${indent}    ${JSON.stringify(v)}`).join(",\n");
    return `[\n${inner}\n${indent}]`;
}

// ---------------------------------------------------------------- 展开

function* walkJsonFiles(dir) {
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) yield* walkJsonFiles(full);
        else if (entry.name.endsWith(".json")) yield full;
    }
}

// 展开块上方的作者意图标记：`// @i18n-src: ["原文", ...]`。
// 重跑时从标记重建 expected，映射变更留下的旧展开产物因此不会残留。
function findSrcMarker(text, keyOffset) {
    const m = text.slice(0, keyOffset).match(/\/\/\s*@i18n-src:\s*(\[[^\n]*\])\s*$/);
    if (!m) return null;
    try {
        const items = JSON.parse(m[1]);
        return Array.isArray(items) && items.every((v) => typeof v === "string") ? items : null;
    } catch {
        return null;
    }
}

// 无标记的已展开数组（历史版本产物）逆向还原作者意图：键保留，紧跟其后的
// 当前/历史两代展开产物跳过，其余是作者手写的 leftover。
function deExpand(nodeName, items) {
    const intent = [];
    let products = null;
    for (const item of items) {
        if (typeof item !== "string") {
            intent.push(item);
            continue;
        }
        const zh = normalizeText(item);
        const row = lookupRow(nodeName, zh);
        if (row) {
            intent.push(item);
            products = new Set([
                ...expandRow(zh, row),
                ...expandRow(zh, row, true),
            ]);
            continue;
        }
        if (products?.has(item)) continue;
        products = null;
        intent.push(item);
    }
    return intent;
}

const stats = {files: 0, ocrNodes: 0, skipped: 0, changedNodes: 0, changedFiles: new Set()};
const problemSet = new Set();

// roi 引用链上的多个 OCR 节点可能在同一轮里先后扩宽（引用方的基准宽含被引用方的
// offset），一轮写回后需要再算一轮才收敛——写回模式循环到不动点（上限 4 轮），
// check 模式单轮判定（有变更即失败）。
const MAX_PASSES = CHECK ? 1 : 4;
for (let pass = 1; pass <= MAX_PASSES; pass++) {
    stats.files = 0;
    stats.ocrNodes = 0;
    stats.skipped = 0;
    stats.changedNodes = 0;
    stats.changedFiles = new Set();

    for (const file of walkJsonFiles(PIPELINE_DIR)) {
        const text = readFileSync(file, "utf8");
        const root = parseTree(text);
        if (!root || root.type !== "object") continue;
        stats.files++;

        const edits = [];
        for (const nodeProp of root.children ?? []) {
            const nodeName = nodeProp.children?.[0]?.value;
            const body = nodeProp.children?.[1];
            if (typeof nodeName !== "string" || body?.type !== "object") continue;
            const {expected, expectedKey} = locateExpected(root, nodeName, body);
            if (!expected) continue;
            stats.ocrNodes++;
            if (text.slice(expected.offset, expected.offset + expected.length).includes(SKIP_MARKER)) {
                stats.skipped++;
                continue;
            }

            const current = expected.type === "string" ? [expected.value] : expected.children.map((n) => n.value);
            const marker = findSrcMarker(text, expectedKey.offset);
            const intent = marker ?? deExpand(nodeName, current);

            // 作者意图 -> 规范数组：键展开五语，非键项原样保留
            const canonical = [];
            const widths = []; // 每条被展开映射的 [旧宽, 新宽]
            for (const item of intent) {
                if (typeof item !== "string") {
                    canonical.push(item);
                    continue;
                }
                const zh = normalizeText(item);
                const row = lookupRow(nodeName, zh);
                if (!row) {
                    canonical.push(item);
                    if (CJK.test(zh) && !untranslatableSet.has(zh)) {
                        problemSet.add(
                            `${file}: ${nodeName} 的 expected「${zh}」不在映射表中（补 texts/node_overrides 或 untranslatable，或 @i18n-skip）`,
                        );
                    }
                    continue;
                }
                const expansion = expandRow(zh, row);
                canonical.push(...expansion);
                widths.push([
                    displayWidth(zh),
                    ...expansion.map(displayWidth),
                ]);
            }

            const arrayDiffers =
                canonical.length !== current.length || canonical.some((value, i) => value !== current[i]);
            const hasKey = intent.some((item) => typeof item === "string" && lookupRow(nodeName, normalizeText(item)));
            if (!hasKey) continue; // 与映射无关的节点：不动数组也不加标记（未收录问题已在上面上报）

            // ROI 扩宽：不改 roi，写/增 roi_offset 右边距，以 720p 屏宽截断。
            // 与数组是否变更无关、ensure-at-least 幂等：offset 右边距不足计算值时补足，
            // 已达标不动（数值读取类节点不产生翻译展开，天然不会走到这里）。
            let roiEdit = null;
            if (widths.length > 0) {
                const roi = resolveRoi(root, nodeName, body);
                if (roi) {
                    const oldWidth = Math.max(...widths.map(([w]) => w));
                    const newWidth = Math.max(
                        ...widths.flatMap(
                            ([
                                ,
                                ...ws
                            ]) => ws,
                        ),
                    );
                    const ownRight = roi.offsetNode ? roi.offsetNode.children[2].value : 0;
                    const baseW = roi.values[2] - ownRight; // 人工实测基准宽（不含本工具累计扩宽）
                    if (newWidth > oldWidth && oldWidth > 0 && baseW > 0) {
                        let desiredRight = Math.ceil((baseW * newWidth) / oldWidth) - baseW;
                        const maxRight = Math.floor(SCREEN_WIDTH - roi.values[0] - baseW);
                        if (maxRight > 0) desiredRight = Math.min(desiredRight, maxRight);
                        if (desiredRight > ownRight) roiEdit = {desiredRight};
                        const offsetNode = roi.offsetNode;
                        const anchorNode = roi.anchorNode;
                        if (roiEdit && offsetNode) {
                            roiEdit.edit = {
                                start: offsetNode.offset,
                                end: offsetNode.offset + offsetNode.length,
                                replacement: JSON.stringify(
                                    offsetNode.children.map((n, i) => (i === 2 ? desiredRight : n.value)),
                                ),
                            };
                        } else if (roiEdit && anchorNode) {
                            roiEdit.edit = {
                                start: anchorNode.offset + anchorNode.length,
                                end: anchorNode.offset + anchorNode.length,
                                replacement: `, "roi_offset": [0, 0, ${desiredRight}, 0]`,
                            };
                        }
                    }
                }
            }

            if (marker && !arrayDiffers && !roiEdit) continue; // 幂等：意图、数组、ROI 都已就位

            stats.changedNodes++;
            stats.changedFiles.add(file);

            const keyLineStart = text.lastIndexOf("\n", expectedKey.offset - 1) + 1;
            const indent = lineIndent(text, expectedKey.offset);
            if (!marker) {
                edits.push({
                    start: keyLineStart,
                    end: keyLineStart,
                    replacement: `// @i18n-src: ${JSON.stringify(intent)}\n${indent}`,
                });
            }
            if (arrayDiffers) {
                edits.push({
                    start: expected.offset,
                    end: expected.offset + expected.length,
                    replacement: buildArrayText(canonical, indent),
                });
            }
            if (roiEdit?.edit) edits.push(roiEdit.edit);
        }

        if (!CHECK) {
            edits.sort((a, b) => b.start - a.start);
            let result = text;
            for (const edit of edits) {
                result = result.slice(0, edit.start) + edit.replacement + result.slice(edit.end);
            }
            if (edits.length > 0) writeFileSync(file, result);
        }
    }
    if (CHECK) break;
    if (stats.changedNodes === 0) break;
    if (pass === MAX_PASSES) console.warn(`! 已达 ${MAX_PASSES} 轮上限仍未收敛，请人工检查 roi 引用链`);
}
const problems = [...problemSet];

// ---------------------------------------------------------------- 汇总

const changedFiles = stats.changedFiles.size;
if (CHECK) {
    if (stats.changedNodes > 0) {
        console.error(
            `x ${stats.changedNodes} 个 OCR 节点的 expected 与映射展开结果不一致，请运行: node tools/i18n/sync-ocr.mjs`,
        );
        process.exit(1);
    }
    if (problems.length > 0) {
        for (const problem of problems.slice(0, 20)) console.error("x " + problem);
        if (problems.length > 20) console.error(`x ... and ${problems.length - 20} more`);
        process.exit(1);
    }
    console.log(`[OK] ocr expected is consistent (${stats.ocrNodes} OCR nodes, ${stats.skipped} skipped by marker)`);
} else {
    console.log(
        `files: ${stats.files} | OCR nodes: ${stats.ocrNodes} | skipped: ${stats.skipped} | changed: ${stats.changedNodes} nodes in ${changedFiles} files`,
    );
    if (problems.length > 0) {
        for (const problem of problems.slice(0, 20)) console.warn("! " + problem);
        if (problems.length > 20) console.warn(`! ... and ${problems.length - 20} more`);
        console.warn("运行 pnpm format 归一化排版后提交");
    }
}
