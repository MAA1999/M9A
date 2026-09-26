/**
 * 解析 Android 打包流程要用的版本与命名参数，供 `.github/workflows/android.yml` 使用。
 *
 * 1. MaaFW 版本与桌面同源固定：agent 项目看 requirements.txt 的 `maafw==X`，纯 pipeline 项目看
 *    maa-project.json 的 maafw 字段。Android 的 Python 绑定只随内核（MaaAgentCoreAndroid）
 *    发布（公开索引没有 Android 版 maafw 轮子），所以按 X 去内核 repo 挑 `*-maafwX` 配对的
 *    release，client 原生库（jniLibs）铺同版本 MaaFramework，保证 APK 里前后端一致；
 * 2. release 资产前缀：取 maa-project.json 的显示名（不可用时退回 slug），于是同一份 workflow
 *    可以给别的项目直接用；
 * 3. 有没有 agent：纯 pipeline 项目不涉及 Python 绑定，workflow 据此跳过内核缓存与运行时构建。
 *    Android 的 agent 运行时目前只支持 Python（内核 MaaAgentCoreAndroid 就是 CPython +
 *    maa 绑定）；Go/Rust 等 ELF agent 理论上可走外壳的 nativeLibs 路线，真出现时这里再扩。
 *
 * 用法：`node tools/android-packaging.mjs [项目根目录]`，结果既打印也追加到 `$GITHUB_OUTPUT`。
 * 测试 / 离线可用 `ANDROID_PACKAGING_RELEASES_FIXTURE` 指向 `{core: [...], maafw: [...]}` 的
 * JSON 文件代替 GitHub API；`AGENT_CORE_TAG` 可应急钉内核（偏离固定版本时会打 warning）。
 */
import {appendFileSync, existsSync, readFileSync} from "node:fs";
import {join} from "node:path";

const PROJECT_CONFIG = "maa-project.json";
const INTERFACE = "interface.json";
const REQUIREMENTS = "requirements.txt";

// 内核 repo：Android 绑定随它的 release 发布，tag 形如 "3.13.15-maafw5.12.3"
const CORE_REPO = "Aliothmoon/MaaAgentCoreAndroid";
// 纯 pipeline 项目没有 requirements 固定时，按 maa-project.json 的通道从这里取最新
const MAAFW_REPO = "MaaXYZ/MaaFramework";

const CORE_TAG_ENV = "AGENT_CORE_TAG";
const RELEASES_FIXTURE_ENV = "ANDROID_PACKAGING_RELEASES_FIXTURE";
const CORE_MAAFW_PATTERN = /^(\d[\w.]*)-maafw([\w.]+)$/;
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

function compareVersions(a, b) {
    const left = a.split(".").map(Number);
    const right = b.split(".").map(Number);
    for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
        const diff = (left[i] ?? 0) - (right[i] ?? 0);
        if (diff !== 0) return diff;
    }
    return 0;
}

function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function envTrim(name) {
    return (process.env[name] ?? "").trim();
}

async function githubReleases(repo, perPage = 100) {
    const headers = {
        Accept: "application/vnd.github+json",
        "User-Agent": "android-packaging-resolver",
    };
    if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
    const response = await fetch(`https://api.github.com/repos/${repo}/releases?per_page=${perPage}`, {headers});
    if (!response.ok) {
        const hint = response.status === 403 ? "（可能是 API 限流，确认 GITHUB_TOKEN 已传入）" : "";
        throw new Error(`查询 ${repo} 的 releases 失败：HTTP ${response.status}${hint}`);
    }
    return response.json();
}

async function loadFixture() {
    const path = process.env[RELEASES_FIXTURE_ENV];
    if (path === undefined || path === "") return null;
    return JSON.parse(readFileSync(path, "utf8"));
}

async function fetchCoreTags() {
    const fixture = await loadFixture();
    if (fixture !== null) return fixture.core ?? [];
    return (await githubReleases(CORE_REPO)).map((release) => release.tag_name);
}

async function fetchMaafwReleases() {
    const fixture = await loadFixture();
    if (fixture !== null) return fixture.maafw ?? [];
    return (await githubReleases(MAAFW_REPO, 30)).map((release) => ({
        tag: release.tag_name,
        prerelease: release.prerelease === true,
    }));
}

/** 内核 repo 现有的全部 maafw 配对版本，从新到旧，给报错信息指路 */
function availablePairings(coreTags) {
    const versions = new Set();
    for (const tag of coreTags) {
        const match = CORE_MAAFW_PATTERN.exec(tag);
        if (match !== null) versions.add(match[2]);
    }
    return [...versions].sort(compareVersions).reverse();
}

/** 挑 maafwX 的配对内核：绑定与原生库必须同版本，只收精确配对，同配对取最新内核 */
function pickPairedCore(coreTags, maafwVersion) {
    const pattern = new RegExp(`^(\\d[\\w.]*)-maafw${escapeRegExp(maafwVersion)}$`);
    const candidates = coreTags
        .map((tag) => pattern.exec(tag))
        .filter((match) => match !== null)
        .map((match) => match[1])
        .sort(compareVersions);
    if (candidates.length === 0) {
        throw new Error(
            `内核（${CORE_REPO}）还没有 maafw${maafwVersion} 配对的 release；` +
                `现有配对：${availablePairings(coreTags).join("、") || "无"}。` +
                `等内核发布即可，救急可用 ${CORE_TAG_ENV} 指定别的内核 release`,
        );
    }
    return `${candidates[candidates.length - 1]}-maafw${maafwVersion}`;
}

function declaredSection(project) {
    const maafw = project.maafw ?? {};
    return {
        version: typeof maafw.version === "string" ? maafw.version.trim() : "",
        channel: typeof maafw.channel === "string" ? maafw.channel.trim() : "",
    };
}

function describeDeclared(project) {
    const {version, channel} = declaredSection(project);
    if (version !== "") return version;
    return `${channel === "" ? "stable" : channel} 通道最新`;
}

/** 纯 pipeline 项目按通道取最新：beta 收 prerelease，stable 不收 */
function channelLatest(releases, channel) {
    const effective = channel === "" ? "stable" : channel;
    const latest = effective === "stable" ? releases.find((release) => !release.prerelease) : releases[0];
    if (latest === undefined) {
        throw new Error(`${MAAFW_REPO} 解析不到 ${effective} 通道最新版`);
    }
    return latest.tag.replace(/^v/, "");
}

function artifactPrefix(project) {
    const section = project.project ?? {};
    for (const key of [
        "displayName",
        "slug",
    ]) {
        const candidate = section[key];
        if (typeof candidate === "string" && SAFE_PREFIX_PATTERN.test(candidate.trim())) {
            return candidate.trim();
        }
    }
    throw new Error("maa-project.json 里没有可用的 project.displayName / project.slug");
}

function agentDeclared(interfaceConfig) {
    return Array.isArray(interfaceConfig.agent) && interfaceConfig.agent.length > 0;
}

/** Android 的 agent 运行时目前只支持 Python（内核自带 CPython 与 maa 绑定），
 * 所以 agent 项目必须 requirements.txt 钉 maafw==X，与桌面 pip 装的绑定一致 */
function pinnedMaafw(root, hasAgent) {
    const pin = parseRequirementPin(readText(join(root, REQUIREMENTS)));
    if (hasAgent && pin === undefined) {
        throw new Error(
            "Android 的 agent 运行时目前只支持 Python，需要在 requirements.txt 精确固定 maafw==X 以配对内核",
        );
    }
    return pin;
}

function parseRequirementPin(text) {
    if (text === undefined) return undefined;
    const match = REQUIREMENT_PIN_PATTERN.exec(text);
    return match === null ? undefined : match[1];
}

async function resolvePackaging(root) {
    const project = readObject(join(root, PROJECT_CONFIG));
    const hasAgent = agentDeclared(readObject(join(root, INTERFACE)));
    const prefix = artifactPrefix(project);
    const {version: declaredVersion, channel: declaredChannel} = declaredSection(project);
    const warnings = [];

    let maafwVersion;
    const requirementPin = pinnedMaafw(root, hasAgent);
    if (requirementPin !== undefined) {
        maafwVersion = requirementPin;
        if (declaredVersion !== "" && declaredVersion !== requirementPin) {
            warnings.push(
                `maa-project.json 固定 ${declaredVersion}，与 requirements 的 maafw==${requirementPin} 不一致；` +
                    `Android 以 requirements 为准（GUI 运行时与 agent 绑定的漂移 PC 侧同样存在）`,
            );
        }
    } else if (declaredVersion !== "") {
        maafwVersion = declaredVersion;
    } else {
        maafwVersion = await channelLatest(await fetchMaafwReleases(), declaredChannel);
    }

    // 内核（绑定载体）只在 agent 项目里用；纯 pipeline 项目 client 库直接从 MaaFramework release 铺
    let coreTag = "";
    if (hasAgent) {
        const override = envTrim(CORE_TAG_ENV);
        if (override !== "") {
            const match = CORE_MAAFW_PATTERN.exec(override);
            if (match === null) {
                throw new Error(`${CORE_TAG_ENV}=${override} 里解析不到 -maafw 版本段`);
            }
            coreTag = override;
            if (match[2] !== maafwVersion) {
                warnings.push(
                    `${CORE_TAG_ENV} 钉的内核绑定是 ${match[2]}，与固定的 maafw${maafwVersion} 不一致；` +
                        `这是应急通道，client 原生库会跟着内核走，出包前记得撤掉`,
                );
                maafwVersion = match[2];
            }
        } else {
            coreTag = pickPairedCore(await fetchCoreTags(), maafwVersion);
        }
    }

    return {
        coreTag,
        maafwTag: `v${maafwVersion}`,
        artifactPrefix: prefix,
        requirementPin,
        declaredTarget: describeDeclared(project),
        hasAgent,
        warnings,
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

async function main() {
    const root = process.argv[2] ?? process.cwd();
    let packaging;
    try {
        packaging = await resolvePackaging(root);
    } catch (error) {
        console.log(`::error::${error instanceof Error ? error.message : String(error)}`);
        return 1;
    }

    for (const warning of packaging.warnings) console.log(`::warning::${warning}`);

    const coreVersion = packaging.maafwTag.replace(/^v/, "");
    console.log(`agent core tag   : ${packaging.coreTag}`);
    console.log(`client MaaFW tag : ${packaging.maafwTag}（与内核绑定 ${coreVersion} 一致）`);
    console.log(`artifact prefix  : ${packaging.artifactPrefix}`);
    console.log(`maa-project.json : ${packaging.declaredTarget}`);
    console.log(`requirements pin : ${packaging.requirementPin ?? "（未钉 maafw==X，纯 pipeline 项目）"}`);
    console.log(`has agent        : ${packaging.hasAgent}`);

    writeOutputs({
        core_tag: packaging.coreTag,
        maafw_tag: packaging.maafwTag,
        artifact_prefix: packaging.artifactPrefix,
        has_agent: String(packaging.hasAgent),
    });
    return 0;
}

// 不能用 process.exit()：Windows 上它与 fetch 留下的 libuv 句柄析构竞争会断言崩溃、
// 退出码非零。改设 exitCode 让事件循环排空后自然退出（保持连接会在几秒内被 undici 回收）
main()
    .then((code) => {
        process.exitCode = code;
    })
    .catch((error) => {
        console.log(`::error::${error instanceof Error ? error.message : String(error)}`);
        process.exitCode = 1;
    });
