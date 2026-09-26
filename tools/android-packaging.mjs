/**
 * 解析 Android 打包流程要用的版本与命名参数，供 `.github/workflows/android.yml` 使用。
 *
 * 1. client 侧（APK 里的 jniLibs）铺哪个 MaaFramework release：Android 的 Python 绑定就是内核
 *    （MaaAgentCoreAndroid）自带那份，公开索引又没有 Android 版 maafw 轮子，所以原生库必须与内核
 *    同版本，否则 APK 里前后端版本不一致；
 * 2. release 资产前缀：取 maa-project.json 的显示名（不可用时退回 slug），于是同一份 workflow
 *    可以给别的项目直接用；
 * 3. 有没有 agent：纯 pipeline 项目不涉及 Python 绑定，workflow 据此跳过内核缓存与运行时构建。
 *
 * 用法：`node tools/android-packaging.mjs [项目根目录]`，结果既打印也追加到 `$GITHUB_OUTPUT`。
 */
import {appendFileSync, existsSync, readFileSync} from "node:fs";
import {join} from "node:path";

const CORE_SCRIPT = join("Android", "MaaFwApp", "scripts", "build_agent_bundle.py");
const PROJECT_CONFIG = "maa-project.json";
const INTERFACE = "interface.json";
const REQUIREMENTS = "requirements.txt";

// CORE_TAG 形如 "3.13.15-maafw5.12.3"；client 原生库版本取 maafw 后面那段
const CORE_TAG_PATTERN = /CORE_TAG\s*=\s*"([^"]*)"/;
const CORE_VERSION_PATTERN = /maafw([0-9].*)$/;
// 应急 / fork 用的内核覆盖（AGENT_CORE_TAG 环境变量）；不设就走子模块的默认值，
// 也就是换 Android/MaaFwApp 子模块 pointer 即可升内核，CI 的 tag 与缓存键都会跟着变
const CORE_TAG_ENV = "AGENT_CORE_TAG";
const REQUIREMENT_PIN_PATTERN = /^maafw==([0-9][^\s;]*)/m;
const SAFE_PREFIX_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

function readText(path) {
    return existsSync(path) ? readFileSync(path, "utf8") : undefined;
}

function readObject(path) {
    const text = readText(path);
    if (text === undefined) throw new Error(`${path} 不存在`);
    const parsed = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(`${path} 的顶层必须是对象`);
    }
    return parsed;
}

function resolveCoreTag(root) {
    const override = (process.env[CORE_TAG_ENV] ?? "").trim();
    if (override !== "") return override;
    const match = CORE_TAG_PATTERN.exec(readText(join(root, CORE_SCRIPT)) ?? "");
    if (match === null) throw new Error("解析不到子模块里的内核 CORE_TAG");
    return match[1];
}

function parseCoreVersion(coreTag) {
    const match = CORE_VERSION_PATTERN.exec(coreTag);
    if (match === null) throw new Error(`内核 tag ${coreTag} 里解析不到 maafw 版本`);
    return match[1];
}

function parseRequirementPin(text) {
    if (text === undefined) return undefined;
    const match = REQUIREMENT_PIN_PATTERN.exec(text);
    return match === null ? undefined : match[1];
}

function declaredTarget(project) {
    const maafw = project.maafw ?? {};
    const version = typeof maafw.version === "string" ? maafw.version.trim() : "";
    if (version !== "") return version;
    const channel = typeof maafw.channel === "string" ? maafw.channel.trim() : "";
    return `${channel === "" ? "stable" : channel} 通道最新`;
}

function artifactPrefix(project) {
    const section = project.project ?? {};
    for (const key of [
        "displayName",
        "slug",
    ]) {
        const candidate = section[key];
        if (typeof candidate === "string" && SAFE_PREFIX_PATTERN.test(candidate.trim())) return candidate.trim();
    }
    throw new Error("maa-project.json 里没有可用的 project.displayName / project.slug");
}

function agentDeclared(interfaceConfig) {
    return Array.isArray(interfaceConfig.agent) && interfaceConfig.agent.length > 0;
}

function resolvePackaging(root) {
    const project = readObject(join(root, PROJECT_CONFIG));
    const coreTag = resolveCoreTag(root);
    return {
        coreTag,
        maafwTag: `v${parseCoreVersion(coreTag)}`,
        artifactPrefix: artifactPrefix(project),
        requirementPin: parseRequirementPin(readText(join(root, REQUIREMENTS))),
        declaredTarget: declaredTarget(project),
        hasAgent: agentDeclared(readObject(join(root, INTERFACE))),
    };
}

function writeOutputs(pairs) {
    const output = process.env.GITHUB_OUTPUT;
    if (output === undefined || output === "") return;
    appendFileSync(
        output,
        Object.entries(pairs)
            .map(
                ([
                    key,
                    value,
                ]) => `${key}=${value}\n`,
            )
            .join(""),
        "utf8",
    );
}

function main() {
    const root = process.argv[2] ?? process.cwd();
    let packaging;
    try {
        packaging = resolvePackaging(root);
    } catch (error) {
        console.log(`::error::${error instanceof Error ? error.message : String(error)}`);
        return 1;
    }

    const coreVersion = packaging.maafwTag.replace(/^v/, "");
    if (packaging.requirementPin !== undefined && packaging.requirementPin !== coreVersion) {
        console.log(
            `::warning::Android 绑定暂时只能跟内核 ${coreVersion}（没有公开的 Android 版 maafw 轮子）；` +
                `requirements 的 maafw==${packaging.requirementPin}、maa-project.json 的 ${packaging.declaredTarget}` +
                `；要跟进就把 Android/MaaFwApp 子模块换到 CORE_TAG 带新版本的提交`,
        );
    }

    console.log(`agent core tag   : ${packaging.coreTag}`);
    console.log(`client MaaFW tag : ${packaging.maafwTag}（与内核绑定 ${coreVersion} 一致）`);
    console.log(`artifact prefix  : ${packaging.artifactPrefix}`);
    console.log(`maa-project.json : ${packaging.declaredTarget}`);
    console.log(`requirements pin : ${packaging.requirementPin ?? "（无 requirements.txt，纯 pipeline 项目）"}`);
    console.log(`has agent        : ${packaging.hasAgent}`);

    writeOutputs({
        core_tag: packaging.coreTag,
        maafw_tag: packaging.maafwTag,
        artifact_prefix: packaging.artifactPrefix,
        has_agent: String(packaging.hasAgent),
    });
    return 0;
}

process.exit(main());
