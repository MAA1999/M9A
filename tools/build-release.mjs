import {
    chmodSync,
    cpSync,
    existsSync,
    mkdirSync,
    readFileSync,
    readdirSync,
    realpathSync,
    renameSync,
    rmSync,
    statSync,
    writeFileSync,
} from "node:fs";
import {basename, dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const projectSlug = "m9a";
const releaseArtifactName = "M9A";

// --- GUI type registry (extensible for future GUIs) ---

const GUI_TYPES = {
    mfaa: {
        suffix: "MFAA",
        runtimeDir: "mfaa",
        entrypointCandidates: (platform) =>
            platform.startsWith("win-")
                ? [
                      "MFAAvalonia.exe",
                      "MFAAvalonia",
                  ]
                : [
                      "MFAAvalonia",
                      "MFAAvalonia.exe",
                  ],
        flatLayout: true,
        modifyInterface(iface) {
            return iface;
        },
    },
    mxu: {
        suffix: "MXU",
        runtimeDir: "mxu",
        entrypointCandidates: (platform) =>
            platform.startsWith("win-")
                ? [
                      "mxu.exe",
                      "mxu",
                  ]
                : [
                      "mxu",
                      "mxu.exe",
                  ],
        flatLayout: false,
        modifyInterface(iface, slug, ver) {
            const modified = {...iface};
            const displayName =
                typeof modified.label === "string" && modified.label.trim() ? modified.label.trim() : slug;
            modified.title = `${displayName} ${ver} | MXU`;
            modified.mirrorchyan_rid = "M9A-MXU";
            // Deliberately no agent override: prepareReleaseInterface already sets the
            // platform-correct command (the bundled interpreter running agent/main.py), and
            // MXU resolves relative child_exec paths against the project root on its own.
            return modified;
        },
    },
};

function main() {
    const dryRun = process.argv.includes("--dry-run");
    const releaseTagOverride = commandLineValue("--release-tag");
    mkdirSync("dist", {recursive: true});

    const project = readJson("maa-project.json");
    const interfaceJson = readJson("interface.json");
    if (interfaceJson.name !== projectSlug) {
        throw new Error("interface.json name must match release artifact slug");
    }

    const sourceVersion = String(interfaceJson.version ?? "");
    if (!isReleaseVersion(sourceVersion)) {
        throw new Error("interface.json version must be a release tag such as v0.1.0");
    }

    const releaseTag = releaseTagOverride ?? detectReleaseTag();
    if (!dryRun && !releaseTag) {
        throw new Error("release build requires a SemVer Git tag such as v0.1.0");
    }

    const version = releaseTag ?? sourceVersion;
    if (!isReleaseVersion(version)) {
        throw new Error("release tag must be a SemVer tag such as v0.1.0");
    }

    const runtimePlatform = detectRuntimePlatform();

    const enabledGuis = [];
    if (project.runtime?.mfa?.enabled !== false) {
        enabledGuis.push("mfaa");
    }
    if (project.runtime?.mxu?.enabled) {
        enabledGuis.push("mxu");
    }

    if (enabledGuis.length === 0) {
        throw new Error("no GUI runtime enabled in maa-project.json");
    }

    for (const path of [
        ...strings(interfaceJson.resource),
        ...strings(interfaceJson.import),
        ...interfaceLanguagePaths(interfaceJson.languages),
    ]) {
        if (path.includes("\\")) {
            throw new Error(`release paths must use forward slashes: ${path}`);
        }
        if (!isProjectRelativePath(path)) {
            throw new Error(`release paths must stay within the project root: ${path}`);
        }
        const relativePath = path.startsWith("./") ? path.slice(2) : path;
        if (!existsSync(relativePath)) {
            throw new Error(`release referenced path does not exist: ${path}`);
        }
    }

    const artifacts = [];

    for (const guiKey of enabledGuis) {
        const gui = GUI_TYPES[guiKey];
        console.log(`\n--- Building ${gui.suffix} package ---`);
        const packagePaths = releasePackagePaths(interfaceJson, guiKey);

        const guiInterface = releaseGuiInterface(guiKey, interfaceJson, version, runtimePlatform);

        if (!dryRun) {
            const guiPath = guiRuntimePath(gui.runtimeDir, runtimePlatform);
            if (!existsSync(guiPath)) {
                console.warn(`[WARN] ${gui.suffix} runtime not found at ${guiPath}, skipping.`);
                continue;
            }
            for (const path of packagePaths) {
                if (!existsSync(path)) {
                    throw new Error(`release package path is missing: ${path}`);
                }
            }
            if (packageHasAgent(interfaceJson)) {
                const pythonPath = pythonRuntimePath(runtimePlatform);
                if (!existsSync(pythonPath)) {
                    throw new Error(`release package path is missing: ${pythonPath}`);
                }
            }
            prepareReleasePackage(guiKey, gui, packagePaths, guiInterface, runtimePlatform);
            smokeReleasePackage(gui, `dist/package-${guiKey}`, packagePaths, runtimePlatform);
        }

        const releaseTargets = [
            [
                "win",
                "x86_64",
                "zip",
            ],
            [
                "win",
                "aarch64",
                "zip",
            ],
            [
                "linux",
                "x86_64",
                "tar.gz",
            ],
            [
                "linux",
                "aarch64",
                "tar.gz",
            ],
            [
                "macos",
                "x86_64",
                "tar.gz",
            ],
            [
                "macos",
                "aarch64",
                "tar.gz",
            ],
        ];
        for (const [
            os,
            arch,
            ext,
        ] of releaseTargets) {
            artifacts.push(`${releaseArtifactName}-${os}-${arch}-${version}-${gui.suffix}.${ext}`);
        }
    }

    const suffixPattern = enabledGuis.map((g) => GUI_TYPES[g].suffix).join("|");
    for (const artifact of artifacts) {
        if (
            !new RegExp(
                "^" +
                    escapeRegExp(releaseArtifactName) +
                    "-(win|linux|macos)-(x86_64|aarch64)-v.+-(" +
                    suffixPattern +
                    ")\\.(zip|tar\\.gz)$",
            ).test(artifact)
        ) {
            throw new Error(`invalid artifact name: ${artifact}`);
        }
        console.log(`[OK] artifact name: ${artifact}`);
    }

    if (!existsSync("runtimes")) {
        console.warn("[WARN] Runtime assets are not present yet; run pnpm sync:runtime before a real release.");
    }

    console.log(
        dryRun
            ? `[OK] release dry-run smoke check completed for ${projectSlug}`
            : `[OK] release build placeholder completed for ${projectSlug}`,
    );
}

function readJson(path) {
    return JSON.parse(readFileSync(path, "utf8"));
}

function writeJson(path, value) {
    writeFileSync(path, JSON.stringify(value, null, 4) + "\n", "utf8");
}

function strings(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === "string") : [];
}

function interfaceResourcePaths(value) {
    return Array.isArray(value) ? value.flatMap((item) => (isRecord(item) ? strings(item.path) : [])) : [];
}

// interface.json `languages` maps a language code to its translation file. If one of
// those files is missing from the package the client renders raw `$Key` strings.
function interfaceLanguagePaths(value) {
    return isRecord(value) ? Object.values(value).filter((item) => typeof item === "string") : [];
}

function isProjectRelativePath(path) {
    const stripped = path.startsWith("./") ? path.slice(2) : path;
    return (
        stripped !== "" &&
        stripped !== "." &&
        !stripped.startsWith("/") &&
        !/^[A-Za-z]:/.test(stripped) &&
        !stripped.split("/").includes("..")
    );
}

function releasePackagePaths(interfaceJson, guiKey) {
    const paths = [
        "tasks",
        "resource",
        // translation files are only required when interface.json declares `languages`
        ...interfaceLanguagePaths(interfaceJson.languages),
    ];
    if (guiKey === "mfaa") {
        paths.push("runtimes", "libs/MaaAgentBinary", "plugins");
    }
    if (packageHasAgent(interfaceJson)) {
        paths.push("agent");
    }
    return paths;
}

function optionalPackagePaths() {
    return [
        "data",
        "README.md",
        "LICENSE",
        "CONTACT",
    ];
}

function packageHasAgent(interfaceJson) {
    return Array.isArray(interfaceJson.agent) && interfaceJson.agent.length > 0;
}

function prepareReleaseInterface(interfaceJson, version, runtimePlatform) {
    const releaseInterface = {...interfaceJson, version};
    delete releaseInterface.$schema;
    if (packageHasAgent(interfaceJson)) {
        releaseInterface.agent = interfaceJson.agent.map((agent) =>
            isRecord(agent)
                ? {
                      ...agent,
                      child_exec: releaseAgentChildExec(runtimePlatform),
                      child_args: [
                          ...RELEASE_AGENT_CHILD_ARGS,
                      ],
                  }
                : agent,
        );
    }
    return releaseInterface;
}

// GUI tweaks always run on top of the per-platform release interface, so a GUI can never
// replace the platform-correct Agent command set up by prepareReleaseInterface.
function releaseGuiInterface(guiKey, interfaceJson, version, runtimePlatform) {
    const gui = GUI_TYPES[guiKey];
    if (!gui) {
        throw new Error(`unknown GUI runtime: ${guiKey}`);
    }
    return gui.modifyInterface(
        prepareReleaseInterface(interfaceJson, version, runtimePlatform),
        projectSlug,
        version,
        runtimePlatform,
    );
}

function prepareReleasePackage(guiKey, gui, packagePaths, interfaceJson, runtimePlatform) {
    const pkgDir = `dist/package-${guiKey}`;
    rmSync(pkgDir, {recursive: true, force: true});
    mkdirSync(pkgDir, {recursive: true});
    copyDirectoryContents(guiRuntimePath(gui.runtimeDir, runtimePlatform), pkgDir);
    renameGuiEntrypoint(gui, pkgDir, runtimePlatform);
    writeJson(join(pkgDir, "interface.json"), interfaceJson);
    if (existsSync("logo.ico")) {
        copyPath("logo.ico", join(pkgDir, "logo.ico"));
    }
    for (const path of packagePaths) {
        const options = path === "agent" ? {filter: shouldCopyAgentPath} : {};
        copyPath(path, join(pkgDir, path), options);
    }
    for (const path of optionalPackagePaths()) {
        if (existsSync(path)) {
            copyPath(path, join(pkgDir, path));
        }
    }
    if (packageHasAgent(interfaceJson)) {
        copyPath(pythonRuntimePath(runtimePlatform), join(pkgDir, "python"));
    }
    if (!gui.flatLayout) {
        prepareMxuMaafwRuntime(pkgDir, runtimePlatform);
        removeFiles(pkgDir, (name) => name.toLowerCase().endsWith(".pdb"));
    }
    if (runtimePlatform.startsWith("win-")) {
        for (const file of [
            "ModifyPCRegistry.ps1",
            "游戏PC端注册表修改_ModifyPCRegistry.bat",
        ]) {
            const source = join("tools/registry", file);
            if (existsSync(source)) {
                copyPath(source, join(pkgDir, file));
            }
        }
    }

    ensureUnixExecutablePermissions(pkgDir, runtimePlatform);
}

function prepareMxuMaafwRuntime(pkgDir, runtimePlatform) {
    const maafwDest = join(pkgDir, "maafw");
    mkdirSync(maafwDest, {recursive: true});

    const nativeRuntime = join("runtimes", runtimePlatform, "native");
    if (!existsSync(nativeRuntime)) {
        throw new Error(`release package path is missing: ${nativeRuntime}`);
    }
    copyDirectoryContents(nativeRuntime, maafwDest, {filter: shouldCopyMxuMaafwPath});

    if (existsSync("libs/MaaAgentBinary")) {
        copyDirectoryContents("libs/MaaAgentBinary", join(maafwDest, "MaaAgentBinary"));
    }
}

function smokeReleasePackage(gui, root, packagePaths, runtimePlatform) {
    if (!existsSync(join(root, "interface.json"))) {
        throw new Error("release package smoke failed: interface.json is missing at package root");
    }
    const entrypoint = guiEntrypointName(runtimePlatform);
    if (!existsSync(join(root, entrypoint))) {
        throw new Error(`release package smoke failed: GUI entrypoint is missing: ${entrypoint}`);
    }
    for (const candidate of gui.entrypointCandidates(runtimePlatform)) {
        if (existsSync(join(root, candidate))) {
            throw new Error(`release package smoke failed: entrypoint must be renamed: ${candidate}`);
        }
    }
    if (existsSync(join(root, projectSlug, "interface.json"))) {
        throw new Error("release package smoke failed: package must not contain a top-level wrapper directory");
    }
    for (const path of packagePaths) {
        const packagePath = path;
        if (!existsSync(join(root, packagePath))) {
            throw new Error(`release package smoke failed: package path is missing: ${packagePath}`);
        }
    }
    for (const path of releaseDevPaths()) {
        if (existsSync(join(root, path))) {
            throw new Error(`release package smoke failed: package includes dev file: ${path}`);
        }
    }
    if (!gui.flatLayout) {
        if (!existsSync(join(root, "maafw"))) {
            throw new Error("release package smoke failed: MXU package is missing maafw");
        }
        for (const path of [
            "runtimes",
            "libs",
            "plugins",
        ]) {
            if (existsSync(join(root, path))) {
                throw new Error(`release package smoke failed: MXU package includes top-level ${path}`);
            }
        }
        const pdbFiles = [];
        walkFiles(root, (path, name) => {
            if (name.toLowerCase().endsWith(".pdb")) pdbFiles.push(path);
        });
        if (pdbFiles.length > 0) {
            throw new Error(`release package smoke failed: MXU package includes pdb files: ${pdbFiles.join(", ")}`);
        }
        const forbiddenMaafwFiles = [];
        walkFiles(join(root, "maafw"), (path, name) => {
            if (isMxuMaafwExcludedName(name)) forbiddenMaafwFiles.push(path);
        });
        if (forbiddenMaafwFiles.length > 0) {
            throw new Error(
                `release package smoke failed: MXU maafw includes excluded files: ${forbiddenMaafwFiles.join(", ")}`,
            );
        }
    }

    const packagedInterface = readJson(join(root, "interface.json"));
    if (!isRecord(packagedInterface)) {
        throw new Error("release package smoke failed: interface.json must be an object");
    }
    if (packagedInterface.$schema !== undefined) {
        throw new Error("release package smoke failed: package interface.json must not include $schema");
    }
    if (!isReleaseVersion(String(packagedInterface.version ?? ""))) {
        throw new Error("release package smoke failed: package interface.json version must be a release tag");
    }
    if (packageHasAgent(packagedInterface)) {
        const childExec = packagedInterface.agent[0]?.child_exec ?? releaseAgentChildExec(runtimePlatform);
        if (!existsSync(join(root, ...childExec.split("/")))) {
            throw new Error(`release package smoke failed: Agent Python entrypoint is missing: ${childExec}`);
        }
    }
    assertUnixExecutablePermissions(root, runtimePlatform);
    for (const path of [
        ...interfaceResourcePaths(packagedInterface.resource),
        ...strings(packagedInterface.import),
        ...interfaceLanguagePaths(packagedInterface.languages),
    ]) {
        if (path.includes("\\")) {
            throw new Error(`release package smoke failed: package path uses backslashes: ${path}`);
        }
        const relativePath = path.startsWith("./") ? path.slice(2) : path;
        if (!existsSync(join(root, relativePath))) {
            throw new Error(`release package smoke failed: referenced path is missing: ${path}`);
        }
    }
}

function releaseDevPaths() {
    return [
        ".github",
        ".vscode",
        ".create-maa-project",
        ".venv",
        "cache",
        "debug",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "maa-project.json",
        "tools/schema",
    ];
}

function copyPath(source, target, options = {}) {
    mkdirSync(dirname(target), {recursive: true});
    cpSync(source, target, {recursive: true, force: true, filter: options.filter});
}

function copyDirectoryContents(source, target, options = {}) {
    mkdirSync(target, {recursive: true});
    for (const entry of readdirSync(source)) {
        copyPath(join(source, entry), join(target, entry), options);
    }
}

function shouldCopyAgentPath(source) {
    const name = basename(source).toLowerCase();
    return name !== "__pycache__" && !name.endsWith(".pyc") && !name.endsWith(".pyo");
}

function shouldCopyMxuMaafwPath(source) {
    return !isMxuMaafwExcludedName(basename(source));
}

function isMxuMaafwExcludedName(name) {
    const lower = name.toLowerCase();
    return (
        lower.includes("maadbgcontrolunit") ||
        lower.includes("maathriftcontrolunit") ||
        lower.includes("maarpc") ||
        lower.includes("maahttp") ||
        lower.includes("maapicli") ||
        lower.endsWith(".node") ||
        lower.endsWith(".pdb")
    );
}

// Windows hosts cannot represent Unix permission bits, so cross-building a non-Windows
// package there must skip the executable-bit checks instead of failing the smoke test.
function ensureUnixExecutablePermissions(root, runtimePlatform) {
    if (process.platform === "win32" || runtimePlatform.startsWith("win-")) return;
    for (const path of findUnixExecutableFiles(root)) {
        const mode = statSync(path).mode;
        chmodSync(path, mode | 0o755);
    }
}

function assertUnixExecutablePermissions(root, runtimePlatform) {
    if (process.platform === "win32" || runtimePlatform.startsWith("win-")) return;
    for (const path of findUnixExecutableFiles(root)) {
        if ((statSync(path).mode & 0o111) === 0) {
            throw new Error(`release package smoke failed: executable bit is missing: ${path}`);
        }
    }
}

function findUnixExecutableFiles(root) {
    const names = new Set([
        projectSlug,
        "MFAAvalonia",
        "mxu",
        "MaaPiCli",
        "MaaAgentServer",
        "maa-cli",
        "python",
        "python3",
    ]);
    const found = [];
    walkFiles(root, (path, name) => {
        if (names.has(name)) found.push(path);
    });
    return found;
}

function walkFiles(root, visit) {
    for (const entry of readdirSync(root, {withFileTypes: true})) {
        const path = join(root, entry.name);
        if (entry.isDirectory()) {
            walkFiles(path, visit);
        } else if (entry.isFile()) {
            visit(path, entry.name);
        }
    }
}

function removeFiles(root, shouldRemove) {
    walkFiles(root, (path, name) => {
        if (shouldRemove(name)) rmSync(path, {force: true});
    });
}

function guiRuntimePath(runtimeDir, runtimePlatform) {
    return join(".create-maa-project", "runtime", runtimeDir, runtimePlatform);
}

function pythonRuntimePath(runtimePlatform) {
    return join(".create-maa-project", "runtime", "python", runtimePlatform);
}

function guiEntrypointName(runtimePlatform) {
    return runtimePlatform.startsWith("win-") ? `${projectSlug}.exe` : projectSlug;
}

function renameGuiEntrypoint(gui, root, runtimePlatform) {
    const target = join(root, guiEntrypointName(runtimePlatform));
    for (const candidate of gui.entrypointCandidates(runtimePlatform)) {
        const source = join(root, candidate);
        if (existsSync(source)) {
            renameSync(source, target);
            return;
        }
    }
}

function detectRuntimePlatform() {
    const explicit = normalizeRuntimePlatform(process.env.CREATE_MAA_PROJECT_RUNTIME_PLATFORM ?? "");
    if (explicit) return explicit;
    const os =
        process.platform === "win32"
            ? "win"
            : process.platform === "darwin"
              ? "osx"
              : process.platform === "linux"
                ? "linux"
                : "";
    const arch = normalizeRuntimeArch(process.arch);
    const platform = os && arch ? `${os}-${arch}` : "";
    if (!platform) {
        throw new Error("release runtime platform could not be detected");
    }
    return platform;
}

function normalizeRuntimePlatform(value) {
    const normalized = String(value)
        .trim()
        .toLowerCase()
        .replace(/^windows/, "win")
        .replace(/^win32/, "win")
        .replace(/^darwin/, "osx")
        .replace(/^macos/, "osx")
        .replace(/x86_64/g, "x64")
        .replace(/amd64/g, "x64")
        .replace(/aarch64/g, "arm64")
        .replace(/_/g, "-");
    return /^(win|linux|osx)-(x64|arm64)$/.test(normalized) ? normalized : "";
}

function normalizeRuntimeArch(value) {
    if (value === "x64" || value === "x86_64" || value === "amd64") return "x64";
    if (value === "arm64" || value === "aarch64") return "arm64";
    return "";
}

// Every release package ships an embedded interpreter with the Agent dependencies
// preinstalled: Windows uses the python.org embeddable runtime, macOS and Linux use
// python-build-standalone. All of them live under `python/` at the package root.
function releaseAgentChildExec(runtimePlatform) {
    return runtimePlatform.startsWith("win-") ? "python/python.exe" : "python/bin/python3";
}

const RELEASE_AGENT_CHILD_ARGS = [
    "-u",
    "agent/main.py",
];

function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function detectReleaseTag() {
    const refName = process.env.GITHUB_REF_NAME;
    if (typeof refName === "string" && refName.startsWith("v")) return refName;
    const ref = process.env.GITHUB_REF;
    return typeof ref === "string" && ref.startsWith("refs/tags/") ? ref.slice("refs/tags/".length) : undefined;
}

function commandLineValue(name) {
    const index = process.argv.indexOf(name);
    if (index < 0) return undefined;
    const value = process.argv[index + 1];
    if (typeof value !== "string" || value.startsWith("--")) {
        throw new Error(`${name} requires a value`);
    }
    return value;
}

function isReleaseVersion(value) {
    return /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/.test(value);
}

function escapeRegExp(value) {
    return value.replace(/[.*+?^${|}()|[\]\\]/g, "\\$&");
}

function isMainModule() {
    if (!process.argv[1]) {
        return false;
    }
    try {
        return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
    } catch {
        return false;
    }
}

if (isMainModule()) {
    main();
}

export {releaseAgentChildExec, releaseGuiInterface};
