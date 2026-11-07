// Assembles a macOS application bundle from a release package and wraps it in a dmg, so the macOS
// build ships as a real .app the way MaaEnd does.
//
// The layout follows MXU's docs/macos-deployment.md: Contents/MacOS keeps every Mach-O file (the
// main executable, dylibs, native Agent extensions) so @loader_path and the launch path stay intact,
// while read-only data files move to Contents/Resources/MXU-portable. Both sides get an in-bundle
// relative symlink to the other, because the Agent resolves its real script path and still has to
// import the native extensions that stayed behind. Writing data straight into Contents/MacOS makes
// codesign fail with "code object is not signed at all / In subcomponent: ...json", which leaves the
// bundle unable to pass `codesign --verify --strict` and breaks macOS notifications.
import {spawnSync} from "node:child_process";
import {
    chmodSync,
    closeSync,
    copyFileSync,
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

    visit(packageDir, "", (relativePath, absolutePath, isDirectory) => {
        if (isDirectory) {
            mkdirSync(join(macosDir, relativePath), {recursive: true});
            mkdirSync(join(portableDir, relativePath), {recursive: true});
            return;
        }
        placeEntry(relativePath, absolutePath, {macosDir, portableDir});
    });

    const bundleExecutable = join(macosDir, options.executable);
    if (!existsSync(bundleExecutable)) {
        throw new Error(`macOS entrypoint is not a Mach-O executable: ${options.executable}`);
    }
    chmodSync(bundleExecutable, 0o755);
    writeInfoPlist(appDir, options);
}

// A Mach-O file stays in the code directory and gets a link in the portable tree; a data file moves
// to the portable tree and gets a link in the code directory. Exactly one real copy exists per file.
function placeEntry(relativePath, absolutePath, {macosDir, portableDir}) {
    const isCode = isMachO(absolutePath);
    const homeDir = isCode ? macosDir : portableDir;
    const linkDir = isCode ? portableDir : macosDir;
    const target = join(homeDir, relativePath);
    mkdirSync(dirname(target), {recursive: true});
    moveFile(absolutePath, target);

    const linkPath = join(linkDir, relativePath);
    mkdirSync(dirname(linkPath), {recursive: true});
    symlinkSync(relative(dirname(linkPath), target), linkPath);
}

function visit(root, relativePath, visitEntry) {
    const directory = relativePath ? join(root, relativePath) : root;
    for (const entry of readdirSync(directory, {withFileTypes: true})) {
        if (entry.name === ".DS_Store") continue;
        const childRelative = relativePath ? join(relativePath, entry.name) : entry.name;
        const childAbsolute = join(directory, entry.name);
        if (entry.isDirectory()) {
            visitEntry(childRelative, childAbsolute, true);
            visit(root, childRelative, visitEntry);
            continue;
        }
        if (entry.isSymbolicLink()) {
            // Materialise the target: a link pointing outside the package would dangle once moved.
            const content = readFileSync(childAbsolute);
            rmSync(childAbsolute, {force: true});
            writeFileSync(childAbsolute, content);
        }
        visitEntry(childRelative, childAbsolute, false);
    }
}

function moveFile(source, target) {
    try {
        renameSync(source, target);
    } catch (error) {
        if (error.code !== "EXDEV") throw error;
        copyFileSync(source, target);
        rmSync(source, {force: true});
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
    const icnsName = "m9a.icns";
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
    chmodSync(join(appDir, "Contents", "MacOS", options.executable), 0o755);
    run("codesign", [
        "--force",
        "--deep",
        "--sign",
        "-",
        "--identifier",
        options.bundleId,
        appDir,
    ]);
    run("codesign", [
        "--verify",
        "--deep",
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
    run("hdiutil", [
        "create",
        "-volname",
        `${options.displayName} ${options.version}`,
        "-srcfolder",
        stagingDir,
        "-ov",
        "-format",
        "UDZO",
        dmgPath,
    ]);
    rmSync(stagingDir, {recursive: true, force: true});
}

// The layout contract is checked on every host, including the Windows and Linux builders that
// cross-build a macOS package, so a broken link or a data file left in the code directory fails
// before anything is signed.
function verifyBundle(appDir, options) {
    const contentsDir = join(appDir, "Contents");
    const macosDir = join(contentsDir, "MacOS");
    const portableDir = join(contentsDir, "Resources", PORTABLE_DIR);
    if (!existsSync(join(contentsDir, "Info.plist"))) {
        throw new Error("macOS bundle is missing Contents/Info.plist");
    }
    const executablePath = join(macosDir, options.executable);
    const stats = lstatSync(executablePath, {throwIfNoEntry: false});
    if (!stats || !stats.isFile()) {
        throw new Error(`macOS bundle is missing its executable: ${options.executable}`);
    }
    for (const entry of [
        "json",
        "md",
        "png",
        "py",
    ]) {
        const stray = findRealFileWithExtension(macosDir, `.${entry}`);
        if (stray) {
            throw new Error(`macOS bundle keeps data in Contents/MacOS, codesign would reject it: ${stray}`);
        }
    }
    checkMirroredLinks(macosDir, portableDir, "data file");
    checkMirroredLinks(portableDir, macosDir, "Mach-O file");
}

function checkMirroredLinks(root, linkRoot, label) {
    walkFiles(root, (relativePath) => {
        const linkPath = join(linkRoot, relativePath);
        const stats = lstatSync(linkPath, {throwIfNoEntry: false});
        if (!stats) {
            throw new Error(`macOS bundle is missing the ${label} link: ${relativePath}`);
        }
        if (!stats.isSymbolicLink()) {
            throw new Error(`macOS bundle keeps two real copies of ${relativePath}`);
        }
        const resolved = resolve(dirname(linkPath), readRelativeLink(linkPath));
        if (!existsSync(resolved)) {
            throw new Error(`macOS bundle symlink does not resolve: ${relativePath}`);
        }
    });
}

function readRelativeLink(linkPath) {
    return readlinkSync(linkPath);
}

function walkFiles(root, visitFile) {
    for (const entry of readdirSync(root, {withFileTypes: true})) {
        const path = join(root, entry.name);
        if (entry.isDirectory()) {
            walkFiles(path, (childRelative) => visitFile(join(entry.name, childRelative)));
            continue;
        }
        if (entry.isSymbolicLink()) continue;
        visitFile(entry.name);
    }
}

function findRealFileWithExtension(root, extension) {
    let found;
    walkFiles(root, (relativePath) => {
        if (found === undefined && relativePath.toLowerCase().endsWith(extension)) found = relativePath;
    });
    return found;
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
