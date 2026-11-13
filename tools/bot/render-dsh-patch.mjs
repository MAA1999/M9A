#!/usr/bin/env node
// 把仓库变量 `BOT_LLM_CONFIG` 渲染成 dsh 的 `--patch` 文件。
//
// 为什么单独渲染而不是把 provider 写死在仓库里：中转站可能是裸 IP，地址不该进 git。整段 provider
// 配置（provider 名、模型、baseURL、模型目录）都从 Settings → Secrets and variables → Actions 的
// `BOT_LLM_CONFIG` 读（普通用 Variable，想连设置页都不显示就用 Secret）。仓库里不保存任何 provider
// 配置；两者都没配就直接报错并提示去哪配。日志只打 provider / api / 模型，不打 baseURL，免得到处是裸 IP。
//
// 配置形状（JSON；顶层字段）：
//   provider         string  必填，选中 `providers` 里的哪个键
//   model            string  必填，默认模型 id，必须出现在选中 provider 的 models[].id 里
//   reasoningEffort  string  可选，透传给 agent-default-model
//   providers        object  必填，形如 { "<名字>": { api?, baseURL, defaultContextWindow?,
//                                                         defaultMaxTokens?, models[] } }
//
// `api` 是协议，只有三种：`openai-completions`（默认，绝大多数中转站）、`openai-responses`、
// `anthropic-messages`。不写就按 openai-completions —— 这不是自动探测，协议不对会连不上，
// 按中转站文档填；写错值这里直接报错。
//
// 密钥不在这份配置里：渲染时把每个 provider 的 `apiKeyEnv` 强制改成 `BOT_LLM_API_KEY`，工作流
// 再用 secret 填这个环境变量。换中转站只改地址/模型，不动密钥，也让“用哪个 env 名”这件事只有一处。
//
// 输出是 JSON 文本 —— JSON 是 YAML 的子集，dsh 的 `--patch` 按 YAML 读，所以两者都吃得下，
// 而 JSON 不必再引 YAML 序列化依赖（bot job 里没有 YAML 库）。
import {writeFileSync} from "node:fs";

const API_KEY_ENV = "BOT_LLM_API_KEY";
const out = process.argv[2];
if (!out) {
    console.error("usage: render-dsh-patch.mjs <output-path>");
    process.exit(2);
}

function fail(message) {
    // `::error::` 让 GitHub 在运行页上把它标成一条错误注解，比一行普通 stderr 更容易被抓到。
    console.error(`::error::${message}`);
    process.exit(1);
}

const raw = (process.env.BOT_LLM_CONFIG ?? "").trim();
if (!raw) {
    fail(
        "未配置 BOT_LLM_CONFIG —— 到 Settings → Secrets and variables → Actions 建一个 Secret（或 Variable）填整段 provider 配置 JSON",
    );
}

let cfg;
try {
    cfg = JSON.parse(raw);
} catch (error) {
    fail(`BOT_LLM_CONFIG 不是合法 JSON：${error.message}`);
}

if (typeof cfg !== "object" || cfg === null || Array.isArray(cfg)) {
    fail("BOT_LLM_CONFIG 必须是一个对象");
}
const {provider, model, reasoningEffort, providers} = cfg;
if (typeof provider !== "string" || provider.length === 0) {
    fail("BOT_LLM_CONFIG.provider 必须是非空字符串");
}
if (typeof model !== "string" || model.length === 0) {
    fail("BOT_LLM_CONFIG.model 必须是非空字符串");
}
if (typeof providers !== "object" || providers === null || Array.isArray(providers)) {
    fail("BOT_LLM_CONFIG.providers 必须是对象");
}
for (const name of Object.keys(providers)) {
    const entry = providers[name];
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
        fail(`BOT_LLM_CONFIG.providers["${name}"] 必须是对象`);
    }
}
const selected = providers[provider];
if (!selected) {
    fail(`providers 里没有名为 "${provider}" 的条目`);
}
if (typeof selected.baseURL !== "string" || !/^https?:\/\//i.test(selected.baseURL)) {
    fail(`providers["${provider}"].baseURL 必须是 http(s) 地址`);
}
if (!Array.isArray(selected.models) || !selected.models.some((m) => m && m.id === model)) {
    fail(`providers["${provider}"].models 里缺少 id 为 "${model}" 的条目`);
}

// 密钥统一走同一个 env 名：配置只决定“连哪、用哪个模型”，不决定“密钥放在哪个变量”。
// `api` 缺省按 OpenAI 兼容补上，常见的裸 IP 中转站都是这个协议，配置里可以省掉它。
const ALLOWED_APIS = [
    "openai-completions",
    "openai-responses",
    "anthropic-messages",
];
for (const name of Object.keys(providers)) {
    const entry = providers[name];
    if (entry.api !== undefined && !ALLOWED_APIS.includes(entry.api)) {
        fail(`providers["${name}"].api 只能是 ${ALLOWED_APIS.join(" / ")}`);
    }
    entry.apiKeyEnv = API_KEY_ENV;
    entry.api ??= "openai-completions";
}

// 顺序有意义：agent-default-model 先定默认模型，llm-pi-ai 再注入 provider 表，tool-web 最后关搜索。
// 搜索关掉是结构性的：证据是日志与源码，MaaFW 事实走 MaaLLMWiki、游戏事实在 data/，不需要发现机制；
// `fetch` 留着，知道出处的 URL 照样能取。
const patch = [
    {
        id: "agent-default-model",
        config: {provider, model, ...(reasoningEffort ? {reasoningEffort} : {})},
    },
    {id: "llm-pi-ai", config: {providers}},
    {id: "tool-web", config: {search: false, fetch: true}},
];

writeFileSync(out, `${JSON.stringify(patch, null, 2)}\n`, "utf8");
console.error(`llm provider="${provider}" api="${selected.api}" model="${model}"`);
