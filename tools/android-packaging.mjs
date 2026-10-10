/**
 * 解析 Android 打包流程要用的版本与命名参数，供 `.github/workflows/android-build.yml` 使用。
 *
 * 1. MaaFW 版本与桌面同源固定，来源链：requirements.txt 的 `maafw==X` > maa-project.json 的
 *    maafw.version（须精确）> 纯 pipeline 项目按 maafw.channel 取最新。agent 项目必须拿到精确
 *    版本：Android 的 Python 绑定只随内核（MaaAgentCoreAndroid）发布（公开索引没有 Android 版
 *    maafw 轮子），按 X 去内核 repo 挑 `*-maafwX` 配对的 release，client 原生库（jniLibs）铺同
 *    版本 MaaFramework，保证 APK 里前后端一致；上游发了补丁版而内核还没跟上时降级到不高于 X 的
 *    最高配对（打 warning 并给出降级前后版本）——前后端仍同版本，漂移的只是与固定版本的差距；
 * 2. release 资产前缀：取 maa-project.json 的显示名（不可用时退回 slug）。非 ASCII / 带空白的
 *    显示名会退回 slug——桌面资产名保留 Unicode，这里是刻意分叉：应用内更新按资产名选包，
 *    前缀必须 ASCII；
 * 3. 有没有 agent：纯 pipeline 项目不涉及 Python 绑定，workflow 据此跳过内核缓存与运行时构建。
 *    Android 的 agent 运行时目前只支持 Python（内核 MaaAgentCoreAndroid 就是 CPython + maa 绑定）；
 * 4. has_ocr：OCR 模型是否没入库、CI 需要重新铺（见 hasOcr 处注释）；
 * 5. chaquopy_index / chaquopy_pins：build_agent_bundle.py 的索引列表里 pypi-upstream 永远在
 *    （--extra-index-url 只是追加，不替换）。版本化索引 URL 由 CPython→URL 手维护表给出（无
 *    公式）；pins 不维护包清单——解析时逐包抓 Chaquopy 索引的 simple 页面，桌面 pin 版本在
 *    索引上没有 cp 兼容构建的包自动钉到索引最高可用版（wheel 文件名里的 python 标签即判据），
 *    索引上没有的包是纯 Python、走 upstream 不钉；索引有构建但没有当前 CPython 的直接报错；
 *    内核自带的包（CORE_PROVIDES）不探测——build_agent_bundle.py 会把它们整包丢弃（core wins）。
 *    CHAQUOPY_PIN_OVERRIDES 只作人工兜底，平时为空。
 *
 * 用法：`node tools/android-packaging.mjs [项目根目录]`，结果既打印也追加到 `$GITHUB_OUTPUT`。
 * 测试 / 离线可用 `ANDROID_PACKAGING_RELEASES_FIXTURE` 指向 `{core: [...], maafw: [...]}`
 * JSON、`ANDROID_PACKAGING_CHAQUOPY_FIXTURE` 指向 `{包名: [wheel 文件名]}` JSON，分别代替
 * GitHub API 与 Chaquopy 索引；`AGENT_CORE_TAG` 可应急钉内核（偏离固定版本时会打 warning）。
 *
 * 本文件与 create-maa-project 的 android addon 模板（templates/addons/android/tools/android-packaging.mjs）
 * 同源，改逻辑请同步两边。
 */
import {appendFileSync, existsSync, readFileSync} from "node:fs";
import {join} from "node:path";

const PROJECT_CONFIG = "maa-project.json";
const INTERFACE = "interface.json";
const REQUIREMENTS = "requirements.txt";

// 内核 repo：Android 绑定随它的 release 发布，tag 形如 "3.13.15-maafw5.12.3"（第一段是 CPython 版本）
const CORE_REPO = "AliothMoon/MaaAgentCoreAndroid";
// 纯 pipeline 项目没有 requirements / maa-project.json 固定时，按通道从这里取最新
const MAAFW_REPO = "MaaXYZ/MaaFramework";

const CORE_TAG_ENV = "AGENT_CORE_TAG";
const RELEASES_FIXTURE_ENV = "ANDROID_PACKAGING_RELEASES_FIXTURE";
const CHAQUOPY_FIXTURE_ENV = "ANDROID_PACKAGING_CHAQUOPY_FIXTURE";
const CORE_MAAFW_PATTERN = /^(\d[\w.]*)-maafw([\w.]+)$/;
const REQUIREMENT_PIN_PATTERN = /^maafw==([0-9][^\s;]*)/m;
const SAFE_PREFIX_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
// requirements 行首的「包名==精确版本」；uv export 的 --hash 续行（缩进 + --）、注释、-r / -e
// 与非精确行（比较符不是 ==）都不匹配。uv export 恒为精确钉版，非精确行没有比对的基准
const REQUIREMENT_ENTRY_PATTERN = /^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)/;

// Chaquopy 的版本化 PyPI 索引。键 = 内核 CPython 的 major.minor；"13.1" 是 Chaquopy 自己的
// 发布线编号，不是 CPython 版本，没有 CPython→URL 的公式，只能手维护（上游硬编码位置：
// MaaFwApp scripts/build_agent_bundle.py 的文档示例写死 pypi-13.1）。
// 注意 build_agent_bundle.py 的 pypi-upstream 永远在索引列表里，本表只是追加版本化索引。
const CHAQUOPY_INDEX_BY_CPYTHON = new Map([
    [
        "3.13",
        "https://chaquo.com/pypi-13.1/",
    ],
]);

// 人工兜底：自动探测的结果不对时（索引页面异常、要强制别的版本）在这里钉死版本。语义与自动
// pin 相同，仍只对 requirements 里实际出现的包生效；平时应为空——常规维护是修探测，不是加行
const CHAQUOPY_PIN_OVERRIDES = new Map([]);

// 内核自带的包（agent-core.json 的 provides，今天 = maafw 绑定 / numpy / StrEnum）：
// build_agent_bundle.py 会把 requirements 里这些包整包丢弃（core wins），它们不进 pip，
// 探测它们没有意义——对着索引降级内核自带的包，--require 会把旧版装回内核 site-packages
// 旁边跟内核打架。内核新增自带包时同步这张表（manifest 在内核 tarball 内，无轻量获取渠道）
const CORE_PROVIDES = new Set([
    "maafw",
    "numpy",
    "strenum",
]);

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

let chaquopyFixtureCache;

/** 测试 / 离线替身：`{归一化包名: [wheel 文件名]}`，键不存在 = 索引上没这个包 */
function chaquopyFixturePackages() {
    if (chaquopyFixtureCache === undefined) {
        const path = envTrim(CHAQUOPY_FIXTURE_ENV);
        chaquopyFixtureCache = path === "" ? null : JSON.parse(readFileSync(path, "utf8"));
    }
    return chaquopyFixtureCache;
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
    return [...versions].sort(compareMaafwVersions).reverse();
}

/** MaaFW 版本拆成「数字段 + 后缀」：数字段决定发布线（5.14.3 / 5.13.0b6 / 5.15.0-beta.1），
 *  后缀只在同一条线内比先后。解析不了的（不以数字开头）返回 undefined */
function parseMaafwVersion(text) {
    const match = /^(\d+(?:\.\d+)*)(.*)$/.exec(text.trim());
    if (match === null) return undefined;
    return {release: match[1].split(".").map(Number), suffix: match[2].replace(/^[-.]/, "")};
}

/** 同一条线内无后缀（正式版）大于带后缀（预发布），后缀之间按字符串比；解析不了退回纯数字比较 */
function compareMaafwVersions(left, right) {
    const a = parseMaafwVersion(left);
    const b = parseMaafwVersion(right);
    if (a === undefined || b === undefined) return compareVersions(left, right);
    const release = compareVersions(a.release.join("."), b.release.join("."));
    if (release !== 0) return release;
    if (a.suffix === b.suffix) return 0;
    if (a.suffix === "") return 1;
    if (b.suffix === "") return -1;
    return a.suffix < b.suffix ? -1 : 1;
}

/** candidate 的发布线不高于 pin：`5.13.0b6` 与 `5.13.0` 算同一条线，固定预发布版时同线正式版可用 */
function releaseAtMost(candidate, pin) {
    const a = parseMaafwVersion(candidate);
    const b = parseMaafwVersion(pin);
    if (a === undefined || b === undefined) return false;
    return compareVersions(a.release.join("."), b.release.join(".")) <= 0;
}

/** 某个 maafw 配对下的内核 tag：tag 第一段是 CPython 版本，同配对有多个 CPython 线时取最高的 */
function coreTagFor(coreTags, maafwVersion) {
    const pattern = new RegExp(`^(\\d[\\w.]*)-maafw${escapeRegExp(maafwVersion)}$`);
    return coreTags
        .map((tag) => pattern.exec(tag))
        .filter((match) => match !== null)
        .map((match) => match[1])
        .sort(compareVersions)
        .at(-1);
}

/** 挑可用的配对内核：绑定与原生库必须同版本，所以 client 原生库总跟着选中的绑定走。
 *  优先精确配对；内核还没跟上上游补丁（requirements 已 bump、配对还没发）时降级到不高于固定
 *  版本的最高配对——APK 里前后端仍同版本，漂移的只是相对 requirements 的版本差。固定版本比内核
 *  全部配对都旧时不做「升级」猜测（那多半是版本写错了），仍报错并列出现有配对 */
function pickPackagingCore(coreTags, requested) {
    const pairings = availablePairings(coreTags);
    const eligible = pairings.filter((version) => releaseAtMost(version, requested)).sort(compareMaafwVersions);
    const chosen = pairings.includes(requested) ? requested : eligible.at(-1);
    if (chosen === undefined) {
        throw new Error(
            `内核（${CORE_REPO}）没有不高于 maafw${requested} 的配对 release；` +
                `现有配对：${pairings.join("、") || "无"}。` +
                `确认 requirements.txt / maa-project.json 里的版本没写错，` +
                `或等内核发布即可，救急可用 ${CORE_TAG_ENV} 指定别的内核 release`,
        );
    }
    return {
        coreTag: `${coreTagFor(coreTags, chosen)}-maafw${chosen}`,
        maafwVersion: chosen,
        degraded: chosen !== requested,
    };
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

/** displayName → slug 各过一次 ASCII 闸门，都不合格才报错。
 *  与桌面 releaseArtifactName 是两套刻意分叉的逻辑：桌面保留 Unicode，APK 前缀必须 ASCII。 */
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

function parseRequirementPin(text) {
    if (text === undefined) return undefined;
    const match = REQUIREMENT_PIN_PATTERN.exec(text);
    return match === null ? undefined : match[1];
}

function normalizeRequirementName(name) {
    // PEP 503：大小写与 - _ . 归一
    return name.toLowerCase().replace(/[-_.]+/g, "-");
}

/** requirements 里的精确钉版条目（含 maafw），保持文件顺序。带 `;` 环境标记的行整行跳过：
 *  Android 上 pip 不会装它（如 win32 专属），替它降级反而会凭空多装一个包 */
function requirementEntries(text) {
    if (text === undefined) return [];
    const entries = [];
    for (const line of text.split(/\r?\n/)) {
        if (line.includes(";")) continue;
        const match = REQUIREMENT_ENTRY_PATTERN.exec(line);
        if (match === null) continue;
        entries.push({name: normalizeRequirementName(match[1]), version: match[2]});
    }
    return entries;
}

/** 抓索引上某包的 wheel 文件名。索引只放 Chaquopy 自家构建的 Android wheel（纯 Python 包走
 *  upstream），404 = 没这个包，属正常；其他失败大声报错——静默跳过会把错误拖到构建中途的 pip */
async function fetchChaquopyWheels(indexUrl, name) {
    const fixture = chaquopyFixturePackages();
    if (fixture !== null) return Array.isArray(fixture[name]) ? fixture[name] : [];
    const response = await fetch(`${indexUrl}${name}/`, {
        headers: {"User-Agent": "android-packaging-resolver"},
        signal: AbortSignal.timeout(20000),
    });
    if (response.status === 404) return [];
    if (!response.ok) {
        throw new Error(`查询 Chaquopy 索引的 ${name} 失败：HTTP ${response.status}（${indexUrl}${name}/）`);
    }
    const text = await response.text();
    // PEP 503 simple 页面：wheel 全在 <a> 锚文本里（href 带 #sha256 尾巴，不能直接取）
    return [...text.matchAll(/>([^<>]+\.whl)</g)].map((match) => match[1]);
}

/** wheel 文件名拆出版本与 python 标签：{dist}-{version}-{python}-{abi}-{platform}.whl。已知
 *  dist 前缀（PEP 427 里 - 转写成 _）。version 后面可能带 build tag（numpy-1.26.2-0-cp313），
 *  build 段不以 cp/py/pp 开头，据此让位 */
function parseWheel(filename, distribution) {
    const prefix = `${distribution.replace(/-/g, "_")}-`;
    if (!filename.startsWith(prefix) || !filename.endsWith(".whl")) return undefined;
    const segments = filename.slice(prefix.length).slice(0, -4).split("-");
    const tagIndex = segments.findIndex((segment) => /^(cp|py|pp)/.test(segment));
    if (tagIndex < 1) return undefined;
    return {version: segments[0], pythonTag: segments[tagIndex]};
}

/** 该包在索引上可装的版本集合；py3 / py2.py3 纯 wheel 任何 CPython 都可装 */
function indexVersions(wheels, distribution, cpTag) {
    const versions = new Set();
    for (const wheel of wheels) {
        const parsed = parseWheel(wheel, distribution);
        if (parsed === undefined) continue;
        if (parsed.pythonTag === cpTag || parsed.pythonTag === "py3" || parsed.pythonTag === "py2.py3") {
            versions.add(parsed.version);
        }
    }
    return versions;
}

/** 逐包探测 Chaquopy 索引，生成 build_agent_bundle.py 的 --exclude/--require 参数串：桌面
 *  pin 在索引上有 cp 兼容构建 → 不动；没有 → 钉到索引最高可用版；索引上没这个包 → 纯
 *  Python 走 upstream，不钉。只处理 requirements 里实际出现的包，不给别的项目强加降级 */
async function chaquopyPins(indexUrl, entries, cpTag) {
    const args = [];
    for (const {name, version} of entries) {
        const override = CHAQUOPY_PIN_OVERRIDES.get(name);
        if (override !== undefined) {
            args.push(`--exclude ${name}`, `--require ${name}==${override}`);
            continue;
        }
        if (CORE_PROVIDES.has(name)) continue;
        const wheels = await fetchChaquopyWheels(indexUrl, name);
        if (wheels.length === 0) continue;
        const versions = indexVersions(wheels, name, cpTag);
        if (versions.size === 0) {
            throw new Error(
                `Chaquopy 索引有 ${name} 的构建但没有 ${cpTag} 兼容的（${indexUrl}${name}/），` +
                    `Android 装不进这个原生包；到上游确认后换版本，或在 CHAQUOPY_PIN_OVERRIDES 兜底`,
            );
        }
        if (version !== undefined && versions.has(version)) continue;
        const best = [...versions].sort(compareVersions).at(-1);
        args.push(`--exclude ${name}`, `--require ${name}==${best}`);
    }
    return args.join(" ");
}

/** 内核 tag 第一段是 CPython 版本，取 major.minor 查手维护的 Chaquopy 索引表 */
function chaquopyIndex(coreTag) {
    if (coreTag === "") return "";
    const [cpython] = coreTag.split("-");
    const minor = cpython.split(".").slice(0, 2).join(".");
    const url = CHAQUOPY_INDEX_BY_CPYTHON.get(minor);
    if (url === undefined) {
        const known = [...CHAQUOPY_INDEX_BY_CPYTHON.keys()].join("、") || "无";
        throw new Error(
            `Chaquopy 索引表里没有 CPython ${minor} 的条目（内核 tag ${coreTag}）；已知：${known}。` +
                `这是手维护表（无 CPython→URL 公式），到上游确认发布线后在本表补一行`,
        );
    }
    return url;
}

/** 同一内核 tag 推出 wheel 的 python 标签：3.13.15 → cp313 */
function coreCpTag(coreTag) {
    const [
        major,
        minor,
    ] = coreTag.split("-")[0].split(".");
    return `cp${major}${minor}`;
}

async function resolvePackaging(root) {
    const project = readObject(join(root, PROJECT_CONFIG));
    const interfaceConfig = readObject(join(root, INTERFACE));
    const hasAgent = agentDeclared(interfaceConfig);
    // has_ocr 的真实语义是「OCR 模型没入库，CI 必须重新铺」：base 模板无条件生成
    // resource/base/model/ocr/*，走 submodule 时这些文件进 .gitignore、CI 要重新拉；
    // 走 download 时模型入库，这步只是可选。今天「有 ocr 段」恰好等价于走 submodule
    // （只有那个分支才写 config.ocr），所以拿它当判据。
    const hasOcr = project.ocr !== undefined;
    const prefix = artifactPrefix(project);
    const {version: declaredVersion, channel: declaredChannel} = declaredSection(project);
    const warnings = [];

    // MaaFW 版本来源链（适配点见文件头 1）：requirements 钉版 > maa-project.json 精确版本 >
    // 纯 pipeline 按 channel 取最新。agent 项目拿不到精确版本时无法配对内核，直接报错给指引。
    const requirementsText = readText(join(root, REQUIREMENTS));
    const requirementPin = parseRequirementPin(requirementsText);
    let maafwVersion;
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
    } else if (!hasAgent) {
        maafwVersion = await channelLatest(await fetchMaafwReleases(), declaredChannel);
    } else {
        throw new Error(
            "agent 项目需要精确的 MaaFW 版本以配对内核（Android 绑定只随 MaaAgentCoreAndroid 发布）：" +
                "在 requirements.txt 写 maafw==X，或在 maa-project.json 的 maafw.version 填精确版本；" +
                "只有 channel 时无法配对",
        );
    }

    // 内核（绑定载体）只在 agent 项目里用；纯 pipeline 项目 client 库直接从 MaaFramework release 铺
    let coreTag = "";
    let coreFallback = "";
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
            const picked = pickPackagingCore(await fetchCoreTags(), maafwVersion);
            coreTag = picked.coreTag;
            if (picked.degraded) {
                coreFallback = `maafw${maafwVersion} → maafw${picked.maafwVersion}`;
                warnings.push(
                    `内核（${CORE_REPO}）还没出 maafw${maafwVersion} 配对的 release，降级到最高可用配对 ` +
                        `maafw${picked.maafwVersion}；APK 里绑定与原生库仍同版本，只是比 requirements 固定的版本旧。` +
                        `内核发版后这次降级会自动消失`,
                );
                maafwVersion = picked.maafwVersion;
            }
        }
    }

    // pins 依赖索引与内核 CPython，纯 pipeline 项目没有 agent 运行时，不探测
    const chaquopyIndexUrl = chaquopyIndex(coreTag);
    const pins =
        chaquopyIndexUrl === ""
            ? ""
            : await chaquopyPins(chaquopyIndexUrl, requirementEntries(requirementsText), coreCpTag(coreTag));

    return {
        coreTag,
        coreFallback,
        maafwTag: `v${maafwVersion}`,
        artifactPrefix: prefix,
        requirementPin,
        declaredTarget: describeDeclared(project),
        hasAgent,
        hasOcr,
        chaquopyIndex: chaquopyIndexUrl,
        chaquopyPins: pins,
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

    console.log(`agent core tag   : ${packaging.coreTag || "（纯 pipeline，无内核）"}`);
    console.log(`core fallback    : ${packaging.coreFallback || "（未降级）"}`);
    console.log(`client MaaFW tag : ${packaging.maafwTag}`);
    console.log(`artifact prefix  : ${packaging.artifactPrefix}`);
    console.log(`maa-project.json : ${packaging.declaredTarget}`);
    console.log(`requirements pin : ${packaging.requirementPin ?? "（未钉 maafw==X）"}`);
    console.log(`has agent        : ${packaging.hasAgent}`);
    console.log(`has ocr (re-sync): ${packaging.hasOcr}`);
    console.log(`chaquopy index   : ${packaging.chaquopyIndex || "（无 agent 运行时）"}`);
    console.log(`chaquopy pins    : ${packaging.chaquopyPins || "（无需降级）"}`);

    writeOutputs({
        core_tag: packaging.coreTag,
        maafw_tag: packaging.maafwTag,
        artifact_prefix: packaging.artifactPrefix,
        has_agent: String(packaging.hasAgent),
        has_ocr: String(packaging.hasOcr),
        chaquopy_index: packaging.chaquopyIndex,
        chaquopy_pins: packaging.chaquopyPins,
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
