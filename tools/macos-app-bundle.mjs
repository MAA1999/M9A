// Assembles a macOS application bundle from a release package and wraps it in a dmg, so the macOS
// build ships as a real .app the way MaaEnd does.
//
// Contents/MacOS holds only the GUI executable and one in-bundle relative symlink per top-level
// entry; the entries themselves live in Contents/Resources/MXU-portable. MXU still finds
// interface.json next to the executable through that link, while the data stays out of the code
// directory, where codesign reports "code object is not signed at all / In subcomponent: ...json"
// and the bundle ends up unsigned (MXU's docs/macos-deployment.md calls this out).
import {spawnSync} from "node:child_process";
import {
    chmodSync,
    closeSync,
    copyFileSync,
    cpSync,
    existsSync,
    lstatSync,
    mkdirSync,
    openSync,
    readdirSync,
    readFileSync,
    readlinkSync,
    readSync,
    renameSync,
    rmSync,
    symlinkSync,
    writeFileSync,
} from "node:fs";
import {basename, dirname, join, relative, resolve} from "node:path";

// Mach-O and universal binaries, read as big-endian u32 so both byte orders are listed.
const MACHO_MAGICS = new Set([
    0xfeedface,
    0xcefaedfe,
    0xfeedfacf,
    0xcffaedfe,
    0xcafebabe,
    0xbebafeca,
    0xcafebabf,
    0xbfbafeca,
]);

const PORTABLE_DIR = "MXU-portable";
const DEFAULT_BUNDLE_ID = "com.m9a.app";

function main() {
    const options = parseOptions(process.argv.slice(2));
    const packageDir = resolve(options.package);
    const appDir = resolve(options.app);
    if (!existsSync(packageDir)) {
        throw new Error(`release package does not exist: ${packageDir}`);
    }

    assembleBundle(packageDir, appDir, options);
    verifyBundle(appDir, options);
    if (options.icon) attachIcon(appDir, resolve(options.icon), options);
    if (process.platform !== "darwin") {
        if (options.dmg || !options.skipSign) {
            console.warn("[WARN] codesign and hdiutil are macOS-only; the bundle was not signed or packed");
        }
    } else {
        if (!options.skipSign) signBundle(appDir, options);
        if (options.dmg) createDmg(appDir, resolve(options.dmg), options);
    }
    console.log(`[OK] macOS app bundle: ${appDir}`);
}

function parseOptions(argv) {
    const options = {
        package: "",
        app: "",
        version: "v0.0.0",
        executable: "m9a",
        bundleId: DEFAULT_BUNDLE_ID,
        displayName: "M9A",
        icon: "",
        dmg: "",
        skipSign: false,
    };
    const valueFlags = {
        "--package": "package",
        "--app": "app",
        "--version": "version",
        "--executable": "executable",
        "--bundle-id": "bundleId",
        "--display-name": "displayName",
        "--icon": "icon",
        "--dmg": "dmg",
    };
    for (let index = 0; index < argv.length; index += 1) {
        const flag = argv[index];
        if (flag === "--skip-sign") {
            options.skipSign = true;
            continue;
        }
        const key = valueFlags[flag];
        if (!key) {
            throw new Error(`unknown option: ${flag}`);
        }
        const value = argv[index + 1];
        if (typeof value !== "string" || value.startsWith("--")) {
            throw new Error(`${flag} requires a value`);
        }
        options[key] = value;
        index += 1;
    }
    if (!options.package) throw new Error("--package is required");
    if (!options.app) throw new Error("--app is required");
    return options;
}

function assembleBundle(packageDir, appDir, options) {
    const contentsDir = join(appDir, "Contents");
    const macosDir = join(contentsDir, "MacOS");
    const portableDir = join(contentsDir, "Resources", PORTABLE_DIR);
    rmSync(appDir, {recursive: true, force: true});
    mkdirSync(macosDir, {recursive: true});
    mkdirSync(portableDir, {recursive: true});

    const entrypoint = join(packageDir, options.executable);
    if (!existsSync(entrypoint)) {
        throw new Error(`release package has no entrypoint: ${options.executable}`);
    }
    if (!existsSync(join(packageDir, "interface.json"))) {
        throw new Error("release package has no interface.json");
    }

    for (const entry of readdirSync(packageDir, {withFileTypes: true})) {
        if (entry.name === ".DS_Store") continue;
        const source = join(packageDir, entry.name);
        if (entry.name === options.executable) {
            moveEntry(source, join(macosDir, entry.name));
            chmodSync(join(macosDir, entry.name), 0o755);
            continue;
        }
        const target = join(portableDir, entry.name);
        moveEntry(source, target);
        symlinkSync(relative(macosDir, target), join(macosDir, entry.name));
    }
    writeInfoPlist(appDir, options);
}

function moveEntry(source, target) {
    mkdirSync(dirname(target), {recursive: true});
    try {
        renameSync(source, target);
    } catch (error) {
        if (error.code !== "EXDEV") throw error;
        cpSync(source, target, {recursive: true});
        rmSync(source, {recursive: true, force: true});
    }
}

// codesign only seals what it is given, so every nested Mach-O is signed before the bundle: signing
// the bundle last records their signatures in the seal.
function signNestedCode(appDir, options) {
    const macosExecutable = join(appDir, "Contents", "MacOS", options.executable);
    const nested = [];
    collectMachOFiles(join(appDir, "Contents"), (path) => {
        if (path !== macosExecutable) nested.push(path);
    });
    for (const path of nested) {
        chmodSync(path, (lstatSync(path).mode & 0o777) | 0o755);
        run("codesign", [
            "--force",
            "--sign",
            "-",
            "--identifier",
            `${options.bundleId}.${nestedIndex(path, appDir)}`,
            path,
        ]);
    }
    console.log(`[OK] signed ${nested.length} nested Mach-O file(s)`);
}

function nestedIndex(path, appDir) {
    return relative(join(appDir, "Contents"), path)
        .split(/[\\/]/u)
        .join(".")
        .replace(/[^A-Za-z0-9.-]/gu, "_");
}

function collectMachOFiles(root, visit) {
    for (const entry of readdirSync(root, {withFileTypes: true})) {
        const path = join(root, entry.name);
        if (entry.isDirectory()) {
            collectMachOFiles(path, visit);
            continue;
        }
        if (!entry.isFile()) continue;
        if (isMachO(path)) visit(path);
    }
}

function isMachO(path) {
    let descriptor;
    try {
        descriptor = openSync(path, "r");
        const buffer = Buffer.alloc(4);
        if (readSync(descriptor, buffer, 0, 4, 0) < 4) return false;
        return MACHO_MAGICS.has(buffer.readUInt32BE(0));
    } catch {
        return false;
    } finally {
        if (descriptor !== undefined) closeSync(descriptor);
    }
}

function writeInfoPlist(appDir, options) {
    const fullVersion = String(options.version).replace(/^v/i, "");
    const shortVersion = fullVersion.split("-")[0];
    const entries = [
        [
            "CFBundleDevelopmentRegion",
            "zh_CN",
        ],
        [
            "CFBundleExecutable",
            options.executable,
        ],
        [
            "CFBundleIdentifier",
            options.bundleId,
        ],
        [
            "CFBundlePackageType",
            "APPL",
        ],
        [
            "CFBundleInfoDictionaryVersion",
            "6.0",
        ],
        [
            "CFBundleName",
            options.displayName,
        ],
        [
            "CFBundleDisplayName",
            options.displayName,
        ],
        [
            "CFBundleShortVersionString",
            shortVersion,
        ],
        [
            "CFBundleVersion",
            fullVersion,
        ],
        [
            "LSMinimumSystemVersion",
            "11.0",
        ],
        [
            "NSHighResolutionCapable",
            "true",
        ],
    ];
    const body = entries
        .map(
            ([
                key,
                value,
            ]) =>
                key === "NSHighResolutionCapable"
                    ? `    <key>${key}</key>\n    <true/>`
                    : `    <key>${key}</key>\n    <string>${escapeXml(value)}</string>`,
        )
        .join("\n");
    const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
${body}
</dict>
</plist>
`;
    writeFileSync(join(appDir, "Contents", "Info.plist"), plist, "utf8");
}

function escapeXml(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// sips and iconutil only exist on macOS, so a failed conversion keeps the default system icon
// instead of breaking the packaging step.
function attachIcon(appDir, iconPath, options) {
    if (process.platform !== "darwin") {
        console.warn("[WARN] sips and iconutil are macOS-only; the app keeps the default icon");
        return;
    }
    const resourcesDir = join(appDir, "Contents", "Resources");
    const icnsName = `${options.displayName.toLowerCase()}.icns`;
    const icnsPath = join(resourcesDir, icnsName);
    const workDir = join(resourcesDir, "icon-work");
    rmSync(workDir, {recursive: true, force: true});
    mkdirSync(workDir, {recursive: true});
    try {
        const pngPath = join(workDir, "icon.png");
        if (iconPath.toLowerCase().endsWith(".ico")) {
            run("uv", [
                "run",
                "--frozen",
                "python",
                "-c",
                [
                    "import sys",
                    "from PIL import Image",
                    "image = Image.open(sys.argv[1])",
                    "image.size = sorted(image.info.get('sizes', [image.size]))[-1]",
                    "image.load()",
                    "image.convert('RGBA').save(sys.argv[2])",
                ].join("; "),
                iconPath,
                pngPath,
            ]);
        } else {
            copyFileSync(iconPath, pngPath);
        }
        const iconsetDir = join(workDir, "icon.iconset");
        mkdirSync(iconsetDir, {recursive: true});
        for (const size of [
            16,
            32,
            128,
            256,
            512,
        ]) {
            for (const [
                suffix,
                scale,
            ] of [
                [
                    "",
                    1,
                ],
                [
                    "@2x",
                    2,
                ],
            ]) {
                run("sips", [
                    "-z",
                    String(size * scale),
                    String(size * scale),
                    pngPath,
                    "--out",
                    join(iconsetDir, `icon_${size}x${size}${suffix}.png`),
                ]);
            }
        }
        run("iconutil", [
            "-c",
            "icns",
            iconsetDir,
            "-o",
            icnsPath,
        ]);
        const plistPath = join(appDir, "Contents", "Info.plist");
        const plist = readFileSync(plistPath, "utf8").replace(
            "    <key>CFBundleIdentifier</key>",
            `    <key>CFBundleIconFile</key>\n    <string>${icnsName}</string>\n    <key>CFBundleIdentifier</key>`,
        );
        writeFileSync(plistPath, plist, "utf8");
    } catch (error) {
        console.warn(`[WARN] macOS app icon was not applied: ${error.message}`);
    } finally {
        rmSync(workDir, {recursive: true, force: true});
    }
}

function signBundle(appDir, options) {
    signNestedCode(appDir, options);
    // No --deep here: it re-discovers subcomponents, and the nested signatures are already in place,
    // so sealing the bundle itself is what records them.
    run("codesign", [
        "--force",
        "--sign",
        "-",
        "--identifier",
        options.bundleId,
        appDir,
    ]);
    run("codesign", [
        "--verify",
        "--strict",
        "--verbose=2",
        appDir,
    ]);
}

function createDmg(appDir, dmgPath, options) {
    const stagingDir = `${dmgPath}.staging`;
    rmSync(stagingDir, {recursive: true, force: true});
    mkdirSync(stagingDir, {recursive: true});
    run("cp", [
        "-R",
        appDir,
        join(stagingDir, basename(appDir)),
    ]);
    symlinkSync("/Applications", join(stagingDir, "Applications"));
    mkdirSync(dirname(dmgPath), {recursive: true});
    const dmgArgs = [
        "create",
        "-volname",
        `${options.displayName} ${options.version}`,
        "-srcfolder",
        stagingDir,
        "-ov",
        "-format",
        "UDZO",
        dmgPath,
    ];
    // Hosted runners occasionally answer `Resource busy` while the volume service is still
    // settling after the bundle was just written; a short retry absorbs that flake.
    for (let attempt = 1; ; attempt++) {
        try {
            run("hdiutil", dmgArgs);
            break;
        } catch (error) {
            if (attempt >= 4) throw error;
            const waitMs = attempt * 5000;
            console.warn(`[WARN] hdiutil create failed (attempt ${attempt}/4), retrying in ${waitMs / 1000}s`);
            spawnSync("sleep", [String(waitMs / 1000)]);
        }
    }
    rmSync(stagingDir, {recursive: true, force: true});
}

// The layout contract is checked on every host, including the Windows and Linux builders that
// cross-build a macOS package, so a dangling link or a data file left in the code directory fails
// before anything is signed.
function verifyBundle(appDir, options) {
    const contentsDir = join(appDir, "Contents");
    const macosDir = join(contentsDir, "MacOS");
    const portableDir = join(contentsDir, "Resources", PORTABLE_DIR);
    if (!existsSync(join(contentsDir, "Info.plist"))) {
        throw new Error("macOS bundle is missing Contents/Info.plist");
    }
    const executable = join(macosDir, options.executable);
    const executableStats = lstatSync(executable, {throwIfNoEntry: false});
    if (!executableStats || !executableStats.isFile()) {
        throw new Error(`macOS bundle is missing its executable: ${options.executable}`);
    }
    for (const entry of readdirSync(macosDir, {withFileTypes: true})) {
        if (entry.name === options.executable) continue;
        const linkPath = join(macosDir, entry.name);
        const stats = lstatSync(linkPath);
        if (!stats.isSymbolicLink()) {
            throw new Error(`macOS bundle keeps data inside Contents/MacOS: ${entry.name}`);
        }
        const resolved = resolve(dirname(linkPath), readlinkSync(linkPath));
        if (!existsSync(resolved)) {
            throw new Error(`macOS bundle symlink does not resolve: ${entry.name}`);
        }
        if (!resolved.startsWith(portableDir)) {
            throw new Error(`macOS bundle symlink escapes ${PORTABLE_DIR}: ${entry.name}`);
        }
    }
    if (!existsSync(join(portableDir, "interface.json"))) {
        throw new Error(`macOS bundle is missing ${PORTABLE_DIR}/interface.json`);
    }
}

function run(command, args) {
    const result = spawnSync(command, args, {stdio: "inherit"});
    if (result.error) throw result.error;
    if (result.status !== 0) {
        throw new Error(`command failed: ${command} ${args.join(" ")} (exit code ${result.status ?? 1})`);
    }
}

if (process.argv[1] && process.argv[1].endsWith("macos-app-bundle.mjs")) {
    main();
}
