import {existsSync, readFileSync, readdirSync, statSync} from "node:fs";
import {join, resolve} from "node:path";
import {pathToFileURL} from "node:url";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const Ajv = require("ajv");
const Ajv2020 = require("ajv/dist/2020.js");
const addFormats = require("ajv-formats");
const {parse: parseJsonc} = require("jsonc-parser");

// ---------------------------------------------------------------------------
// Load JSON/JSONC files (comments and trailing commas allowed)
// ---------------------------------------------------------------------------

function loadJson(path) {
    if (!existsSync(path)) throw new Error(path + " is missing");
    const errors = [];
    const data = parseJsonc(readFileSync(path, "utf8"), errors);
    if (errors.length > 0) {
        throw new Error(path + ": " + errors[0].error);
    }
    return data;
}

// ---------------------------------------------------------------------------
// Schema setup: load all *.schema.json, register for $ref resolution
// ---------------------------------------------------------------------------

const schemaDir = resolve("tools/schema");
if (!existsSync(schemaDir)) {
    throw new Error("Missing tools/schema directory");
}

// logger:false suppresses "unknown format" warnings for MaaFW custom formats
// (uint32, int32, etc.) — they are informational, not validation errors.
const ajv7 = new Ajv({allErrors: true, strict: false, logger: false});
addFormats(ajv7);
// MaaFW 用 PCRE 正则语法（如 \x{4e00}），JavaScript RegExp 不兼容，跳过 regex 格式校验
ajv7.addFormat("regex", {type: "string", validate: () => true});

const ajv2020 = new Ajv2020({allErrors: true, strict: false, logger: false});
addFormats(ajv2020);
ajv2020.addFormat("regex", {type: "string", validate: () => true});

const schemaUris = {};

for (const file of readdirSync(schemaDir)) {
    if (!file.endsWith(".schema.json")) continue;
    const fullPath = join(schemaDir, file);
    const schema = loadJson(fullPath);
    const uri = pathToFileURL(fullPath).href;
    const is2020 = String(schema.$schema || "").includes("2020-12");
    const ajv = is2020 ? ajv2020 : ajv7;
    ajv.addSchema(schema, uri);
    schemaUris[file] = uri;
}

function validator(filename) {
    const uri = schemaUris[filename];
    if (!uri) throw new Error("Schema not found: " + filename);
    const schema = loadJson(join(schemaDir, filename));
    const ajv = String(schema.$schema || "").includes("2020-12") ? ajv2020 : ajv7;
    return ajv.getSchema(uri);
}

const interfaceValidator = validator("interface.schema.json");
const taskValidator = validator("interface_import.schema.json");
const pipelineValidator = validator("pipeline.schema.json");

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

let allValid = true;

function validateFile(path, validate) {
    let data;
    try {
        data = loadJson(path);
    } catch (e) {
        console.error(`x ${path}: ${e.message}`);
        allValid = false;
        return;
    }
    const valid = validate(data);
    if (valid) {
        console.log(`v ${path}`);
        return;
    }
    console.error(`x ${path}:`);
    const errors = validate.errors || [];
    for (const err of errors.slice(0, 10)) {
        const jsonPath = err.instancePath || "/";
        console.error(`  ${jsonPath}: ${err.message}`);
    }
    if (errors.length > 10) {
        console.error(`  ... and ${errors.length - 10} more error(s)`);
    }
    allValid = false;
}

function* walkJsonFiles(dir) {
    for (const entry of readdirSync(dir, {withFileTypes: true})) {
        const fullPath = join(dir, entry.name);
        if (entry.isDirectory()) {
            yield* walkJsonFiles(fullPath);
        } else if (entry.name.endsWith(".json") || entry.name.endsWith(".jsonc")) {
            yield fullPath;
        }
    }
}

// interface.json
validateFile("interface.json", interfaceValidator);

// tasks/*.json
if (existsSync("tasks")) {
    for (const file of readdirSync("tasks")) {
        if (file.endsWith(".json") || file.endsWith(".jsonc")) {
            validateFile(join("tasks", file), taskValidator);
        }
    }
}

// resource/*/pipeline/**/*.json
// default_pipeline.json is intentionally skipped: it contains partial default
// parameters that are merged into actual nodes at runtime, not standalone
// pipeline nodes. The pipeline schema validates complete nodes only.
if (existsSync("resource")) {
    for (const pack of readdirSync("resource", {withFileTypes: true})) {
        if (!pack.isDirectory()) continue;
        const pipelineDir = join("resource", pack.name, "pipeline");
        if (existsSync(pipelineDir) && statSync(pipelineDir).isDirectory()) {
            for (const file of walkJsonFiles(pipelineDir)) {
                validateFile(file, pipelineValidator);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// package.json manual checks (not a MaaFW schema file)
// ---------------------------------------------------------------------------

const packageJson = loadJson("package.json");
const pkgErrors = [];

if (typeof packageJson.name !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(packageJson.name)) {
    pkgErrors.push("name must be an ASCII kebab-case slug");
}
if (
    typeof packageJson.version !== "string" ||
    !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(packageJson.version)
) {
    pkgErrors.push("version must be a SemVer version");
}
if (packageJson.private !== true) {
    pkgErrors.push("private must be true");
}
if (packageJson.type !== "module") {
    pkgErrors.push("type must be module");
}
if (typeof packageJson.scripts !== "object" || packageJson.scripts === null || Array.isArray(packageJson.scripts)) {
    pkgErrors.push("scripts must be an object");
}

if (pkgErrors.length > 0) {
    console.error("x package.json:");
    for (const err of pkgErrors) console.error(`  ${err}`);
    allValid = false;
} else {
    console.log("v package.json");
}

// ---------------------------------------------------------------------------

if (allValid) {
    console.log("\n[OK] local project schema is valid");
} else {
    process.exitCode = 1;
}
