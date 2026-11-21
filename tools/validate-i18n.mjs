import {existsSync, readFileSync, readdirSync, statSync} from "node:fs";
import {join} from "node:path";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {parse: parseJsonc, parseTree} = require("jsonc-parser");

// ---------------------------------------------------------------------------
// interface.json declares `languages` as { <language code>: <translation file> }.
// An i18n-able field whose value starts with `$` is a key into those files, and
// so is a pipeline node's focus message content. This script checks the three
// ways that contract can rot:
//   1. a `$key` reference with no entry in some language file
//   2. an entry in a language file that nothing references any more
//   3. a text field or focus message still holding a literal instead of a `$key`
// i18n is opt-in: a project that declares no `languages` is only checked for
// `$key` references it cannot resolve, so a single-language project passes.
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

// jsonc-parser resolves a repeated key to the last occurrence without complaining,
// so a duplicated entry would silently shadow the one above it.
function duplicateKeys(path) {
    const root = parseTree(readFileSync(path, "utf8"));
    const seen = new Set();
    const duplicates = [];
    for (const property of root?.children ?? []) {
        const key = property.children?.[0]?.value;
        if (typeof key !== "string") continue;
        if (seen.has(key)) duplicates.push(key);
        seen.add(key);
    }
    return duplicates;
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

// Every field MaaFW's Project Interface V2 declares as an i18nString. `doc` and
// `desc` also accept an array of i18n strings.
const I18N_FIELDS = new Set([
    "contact",
    "desc",
    "description",
    "doc",
    "icon",
    "label",
    "license",
    "pattern_msg",
    "title",
    "welcome",
]);

// I18n fields whose literal form is user-facing text. Once `languages` is
// declared such a field must be a `$key` — in any language, not just Chinese,
// because a literal cannot follow the interface language. `icon`, `license`, and
// `contact` are i18n-able too, but a literal there is a path or an identifier
// rather than text, so it stays allowed.
const TEXT_FIELDS = new Set([
    "desc",
    "description",
    "doc",
    "label",
    "pattern_msg",
    "title",
    "welcome",
]);

let ok = true;

function fail(message) {
    console.error("x " + message);
    ok = false;
}

// ---------------------------------------------------------------------------
// Collect `$key` references and literal text from the interface files
// ---------------------------------------------------------------------------

const referenced = new Map(); // key -> first file that referenced it
const literalText = [];

function checkString(field, value, file, path) {
    if (!I18N_FIELDS.has(field)) return;
    if (value.startsWith("$")) {
        const key = value.slice(1);
        if (!referenced.has(key)) referenced.set(key, `${file}${path}`);
    } else if (TEXT_FIELDS.has(field)) {
        literalText.push(`${file}${path}`);
    }
}

function scan(node, file, path) {
    if (Array.isArray(node)) {
        node.forEach((item, i) => scan(item, file, `${path}[${i}]`));
        return;
    }
    if (node === null || typeof node !== "object") return;

    for (const [
        field,
        value,
    ] of Object.entries(node)) {
        const child = `${path}.${field}`;
        if (typeof value === "string") {
            checkString(field, value, file, child);
            continue;
        }
        // `pipeline_override` is game-facing pipeline data, not UI text
        if (field === "pipeline_override") continue;
        // `doc` and `desc` also accept an array of i18n strings
        if (Array.isArray(value) && I18N_FIELDS.has(field)) {
            value.forEach((item, i) => {
                const element = `${child}[${i}]`;
                if (typeof item === "string") checkString(field, item, file, element);
                else scan(item, file, element);
            });
            continue;
        }
        scan(value, file, child);
    }
}

let interfaceJson;
try {
    interfaceJson = loadJson("interface.json");
} catch (e) {
    console.error("x " + e.message);
    console.error("\ni18n validation failed");
    process.exit(1);
}
scan(interfaceJson, "interface.json", "");

// Task files are whatever `import` points at — walking tasks/ alone would miss any
// that live elsewhere, so scan both and de-duplicate.
const taskFiles = new Set();
if (existsSync("tasks")) {
    for (const file of walkJsonFiles("tasks")) {
        taskFiles.add(file.replaceAll("\\", "/"));
    }
}
for (const entry of Array.isArray(interfaceJson.import) ? interfaceJson.import : []) {
    if (typeof entry !== "string") continue;
    const normalised = entry.replaceAll("\\", "/").replace(/^\.\//, "");
    if (existsSync(normalised)) taskFiles.add(normalised);
}
for (const file of [...taskFiles].sort()) {
    try {
        scan(loadJson(file), file, "");
    } catch (e) {
        fail(e.message);
    }
}

// Pipeline `focus` message templates also take `$key` references (a `content`
// starting with `$` is an i18n key). Scan only `focus.*.content` strings so other
// `$`-shaped values (e.g. expression `$0`/`$1` back-references) aren't mistaken
// for keys; other pipeline fields (desc, expected, …) aren't i18n-able, so they
// stay out of the literal-text check.
function scanFocus(node, file, path) {
    if (Array.isArray(node)) {
        node.forEach((item, i) => scanFocus(item, file, `${path}[${i}]`));
        return;
    }
    if (node === null || typeof node !== "object") return;
    for (const [
        field,
        value,
    ] of Object.entries(node)) {
        const child = `${path}.${field}`;
        if (field === "focus") {
            // focus maps message type -> template string | { content, display, trace }.
            // A legacy custom value (string, array, …) is pipeline data, not a template map.
            if (value === null || typeof value !== "object" || Array.isArray(value)) continue;
            for (const [
                msgType,
                tmpl,
            ] of Object.entries(value ?? {})) {
                const content = typeof tmpl === "string" ? tmpl : tmpl?.content;
                if (typeof content !== "string") continue;
                if (content.startsWith("$")) {
                    const key = content.slice(1);
                    if (!referenced.has(key)) referenced.set(key, `${file}${child}.${msgType}`);
                } else {
                    literalText.push(`${file}${child}.${msgType}.content`);
                }
            }
            continue;
        }
        scanFocus(value, file, child);
    }
}

// resource/<pack>/pipeline/**/*.json plus resource/<pack>/default_pipeline.json —
// a focus template in either place applies to many nodes at once, so its keys are
// referenced just the same. The default pipeline sits beside `pipeline/`, not inside
// it, so it needs its own entry here.
if (existsSync("resource")) {
    for (const pack of readdirSync("resource", {withFileTypes: true})) {
        if (!pack.isDirectory()) continue;
        const packDir = join("resource", pack.name);
        const files = [];
        const pipelineDir = join(packDir, "pipeline");
        if (existsSync(pipelineDir) && statSync(pipelineDir).isDirectory()) {
            files.push(...walkJsonFiles(pipelineDir));
        }
        const defaultPipeline = join(packDir, "default_pipeline.json");
        if (existsSync(defaultPipeline)) files.push(defaultPipeline);
        for (const file of files) {
            try {
                scanFocus(loadJson(file), file.replaceAll("\\", "/"), "");
            } catch (e) {
                fail(e.message);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Compare against the declared translation files
// ---------------------------------------------------------------------------

const languages = interfaceJson.languages;
const hasLanguages = Boolean(languages) && typeof languages === "object" && Object.keys(languages).length > 0;

if (!hasLanguages) {
    // A project with no translations at all is fine; one that uses `$key` is not.
    if (referenced.size > 0) {
        fail(`interface.json has no \`languages\` block, but ${referenced.size} i18n key(s) are in use`);
    }
} else {
    const defined = new Map(); // lang -> Set of keys

    for (const [
        lang,
        relPath,
    ] of Object.entries(languages)) {
        if (typeof relPath !== "string") {
            fail(`${lang}: the language file path must be a string`);
            continue;
        }
        let table;
        try {
            table = loadJson(relPath);
        } catch (e) {
            fail(`${lang}: ${e.message}`);
            continue;
        }
        const keys = new Set(Object.keys(table));
        defined.set(lang, keys);

        for (const key of duplicateKeys(relPath)) {
            fail(`${relPath}: "${key}" is defined more than once`);
        }

        for (const [
            key,
            value,
        ] of Object.entries(table)) {
            if (typeof value !== "string" || value.length === 0) {
                fail(`${relPath}: "${key}" must be a non-empty string`);
            }
        }

        const missing = [...referenced.keys()].filter((key) => !keys.has(key)).sort();
        for (const key of missing.slice(0, 10)) {
            fail(`${relPath}: missing "${key}" (referenced by ${referenced.get(key)})`);
        }
        if (missing.length > 10) {
            fail(`${relPath}: ... and ${missing.length - 10} more missing key(s)`);
        }

        const orphans = [...keys].filter((key) => !referenced.has(key)).sort();
        for (const key of orphans.slice(0, 10)) {
            fail(`${relPath}: "${key}" is never referenced`);
        }
        if (orphans.length > 10) {
            fail(`${relPath}: ... and ${orphans.length - 10} more unused key(s)`);
        }
    }

    // Every language must cover exactly the same keys as every other language.
    const langs = [...defined.keys()];
    for (const lang of langs.slice(1)) {
        const base = defined.get(langs[0]);
        const other = defined.get(lang);
        const onlyInBase = [...base].filter((key) => !other.has(key)).sort();
        const onlyInOther = [...other].filter((key) => !base.has(key)).sort();
        for (const key of onlyInBase.slice(0, 10)) {
            fail(`${languages[lang]}: "${key}" is present in ${languages[langs[0]]} but missing here`);
        }
        for (const key of onlyInOther.slice(0, 10)) {
            fail(`${languages[langs[0]]}: "${key}" is present in ${languages[lang]} but missing here`);
        }
    }

    // A literal is only drift once the project has translations to hold the text
    // instead; a single-language project must not be flagged for it.
    for (const site of literalText.slice(0, 20)) {
        fail(`literal text in a translatable field (use a \`$key\`): ${site}`);
    }
    if (literalText.length > 20) {
        fail(`... and ${literalText.length - 20} more literal string(s)`);
    }
}

if (!ok) {
    console.error("\ni18n validation failed");
    process.exit(1);
}

if (!hasLanguages) {
    console.log("[OK] no translation files are declared and no i18n keys are in use");
} else {
    console.log(`[OK] i18n is consistent (${referenced.size} keys across ${Object.keys(languages).length} languages)`);
}
