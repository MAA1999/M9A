import {existsSync, readFileSync, readdirSync} from "node:fs";
import {join} from "node:path";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {parse: parseJsonc, parseTree} = require("jsonc-parser");

// ---------------------------------------------------------------------------
// interface.json declares `languages` as { <lang code>: <translation file> }.
// Any i18n-able field whose value starts with `$` is a key into those files.
// This script checks the three ways that contract can rot:
//   1. a `$key` reference with no entry in some language file
//   2. an entry in a language file that nothing references any more
//   3. a user-facing field still holding hard-coded Chinese instead of a `$key`
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

// Ranges that indicate Chinese text: roman numerals (Ⅰ Ⅱ Ⅲ), CJK radicals, CJK
// punctuation (、。「」), CJK Ext-A, CJK Unified, compatibility ideographs, and
// fullwidth forms (（）：！). All of these already appear in this repo's strings.
const CJK = /[Ⅰ-ⅿ⺀-⻿　-〿㐀-䶿一-鿿豈-﫿＀-￯]/;

// Every field the MaaFW Project Interface V2 protocol declares as an i18nString.
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

let ok = true;

function fail(message) {
    console.error("x " + message);
    ok = false;
}

// ---------------------------------------------------------------------------
// Collect `$key` references and hard-coded Chinese from the interface files
// ---------------------------------------------------------------------------

const referenced = new Map(); // key -> first file that referenced it
const hardCoded = [];

function checkString(field, value, file, path) {
    if (value.startsWith("$")) {
        const key = value.slice(1);
        if (!referenced.has(key)) referenced.set(key, file);
    } else if (I18N_FIELDS.has(field) && CJK.test(value)) {
        hardCoded.push(`${file}${path}`);
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

const interfaceJson = loadJson("interface.json");
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
    scan(loadJson(file), file, "");
}

// ---------------------------------------------------------------------------
// Compare against the declared translation files
// ---------------------------------------------------------------------------

const languages = interfaceJson.languages;
if (!languages || Object.keys(languages).length === 0) {
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
}

for (const site of hardCoded.slice(0, 20)) {
    fail(`hard-coded Chinese in a translatable field: ${site}`);
}
if (hardCoded.length > 20) {
    fail(`... and ${hardCoded.length - 20} more hard-coded string(s)`);
}

if (!ok) {
    console.error("\ni18n validation failed");
    process.exit(1);
}

if (!languages || Object.keys(languages).length === 0) {
    console.log("[OK] no translation files are declared and no i18n keys are in use");
} else {
    console.log(`[OK] i18n is consistent (${referenced.size} keys across ${Object.keys(languages).length} languages)`);
}
