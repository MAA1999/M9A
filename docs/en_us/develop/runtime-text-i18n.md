---
order: 10
icon: mdi:translate-variant
---

# Runtime Text Localisation

M9A text comes in two layers: **interface text** (task names, options, descriptions, etc., through the Project Interface V2 `$key` mechanism — see [Interface Localisation](./i18n.md)) and **runtime text** (text that appears while tasks run and interact with the game). This document is the reference for the latter.

Runtime text falls into four categories by where it appears, each with its own mechanism:

| Location                | Content                                                      | Mechanism                                     | Status                                                                     |
| ----------------------- | ------------------------------------------------------------ | --------------------------------------------- | -------------------------------------------------------------------------- |
| pipeline `focus`        | Node notifications / toasts: task progress and failure hints | PI `$key` → `locales/*.json`                  | Landed                                                                     |
| pipeline OCR `expected` | Recognising in-game text                                     | Written in Chinese, expanded from a mapping   | Landed                                                                     |
| Item-name data          | `data/combat/items.json`                                     | Five-language `names` committed with the data | Partially landed                                                           |
| Agent logs              | Python agent's process output                                | Straight to loguru                            | **Deliberately not done** — see [below](#agent-text-deliberately-not-done) |

What they share: MaaFW loads a single pipeline at runtime, and recognition/display is only correct if the text matches or expresses the current language — so translation never duplicates resources; each layer solves it in place.

## Focus messages

A pipeline node's `focus` field is the first-hand feedback users see in the client's notification panel (task progress, failure reasons, self-recovery hints). MaaFW PI v2 resolves `$key` in focus templates — in both the shorthand string form and the `content` of the object form:

```json
"Start1999Error": {
    "focus": {
        "Node.Action.Starting": "$Focus.Start1999Error"
    }
},
"CUB_LackOfMaterial": {
    "focus": {
        "Node.Recognition.True": {
            "content": "$Focus.CUB_LackOfMaterial",
            "display": ["log", "toast"]
        }
    }
}
```

Rules:

- Focus text is always `$Focus.<node name>`; when one node carries several events, append an event suffix to disambiguate;
- Display markup such as `<span>` goes into the locale value, not the pipeline;
- `tools/validate-i18n.mjs` scans the focus of every `resource/*/pipeline`: Chinese that is not a `$key` fails the check, and missing/orphan keys go through the same validation as interface text.

## Translation data is maintained in this repository

The OCR `expected` approach: the pipeline stays a single version, and a tool expands the Simplified Chinese `expected` in place into five-language arrays (CN/TC/EN/JP/KR) — no duplicated pipeline copies and no per-language recognition overrides in overlays.

The translation data this expansion relies on is **maintained entirely in this repository**, with no external data source:

- The Simplified-Chinese-to-four-languages mapping needed for expansion, and the expanded five-language `expected` arrays themselves, are **committed to this repository**;
- The mapping is hand-editable: fixing a translation or adding new text is a normal PR;
- When a game update introduces new text, or same-word-different-translation and version renames show up, the maintainer is responsible for reviewing and extending the mapping (see the [maintenance checklist](#maintenance-checklist-for-game-updates)).

Day-to-day maintenance is therefore self-contained for regular contributors: edit the mapping or run the tool, and `pnpm check` keeps the pipelines and the mapping consistent.

## Data contract: the OCR text mapping

`tools/i18n/ocr_text.json` is the single translation source for recognition text, and it is hand-editable. It serves only the development-time maintenance tooling and validation — the agent never reads it at runtime — so it lives under `tools/` and is not shipped in releases, a deliberate line against `data/` (runtime data that ships, such as item names):

```json
{
    "texts": {
        "确认": {"tw": "確認", "en": [
                "Confirm",
                "Exit"
            ], "jp": "決定", "kr": "확인"},
        "显影罐": {"tw": "顯影罐", "en": "Penumbra Can", "jp": "現像液缶", "kr": "현상 탱크"}
    },
    "node_overrides": {
        "8bitLevelEntry": {"zh": "进入", "tw": "進入", "en": "Enter", "jp": "始める", "kr": "진입"}
    },
    "untranslatable": [
        "^挂载$",
        "售",
        "市场(.*| 雏)形"
    ],
    "excluded_keys": ["language_90011687"]
}
```

- `texts` is keyed by the Simplified Chinese source text (after newline/whitespace normalisation), with tw/en/jp/kr as values; Chinese is the key itself and is not stored twice;
- Each language value may be a string or an **array of candidates** — when the game itself carries several official translations of the same Chinese text, all of them go in (e.g. 「确认」 has both Confirm and Exit for `en`); MaaFW accepts any array entry, so ambiguity is dissolved by construction;
- When a specific node's context needs a narrower translation, override the whole row per node name in `node_overrides` (a single row or an array of rows); it takes priority over `texts`. The `8bitLevelEntry` entry above only demonstrates the format — `node_overrides` is empty in the repository today, since the global 「进入」 row already covers that case;
- English is stored as **plain text**; converting it to the `(?i)` case-insensitive, `\s*`-relaxed-spacing regex happens uniformly at expansion time inside the tool; every mapping value is regex-escaped before being written into `expected` (MaaFW validates and matches `expected` items as regexes);
- `untranslatable` explicitly registers text that deliberately stays monolingual: regex fragments (`^挂载$`), truncated single characters (「售」) and the like, where a full-sentence lookup is impossible; the check does not require them to be expandable;
- `excluded_keys` excludes whole language-table keys from candidate lookup: the official text table occasionally carries dev-leftover rows (measured example `language_90011687`, where the Simplified Chinese 「未解锁」 maps to `uuuuer` / `iagoMBZ` and friends in the other languages), whose values would otherwise pollute the candidates. The sync tool filters these keys when building the reverse index and drops their historical values during merge — hand-deleting candidates from `texts` does not survive the next sync; exclusion must be registered here;
- Fixing a translation in any language is a normal PR against this file — no special workflow involved.

## The sync tool

The tool is `tools/i18n/sync-ocr.mjs` and consumes the mapping above:

```bash
node tools/i18n/sync-ocr.mjs            # expand/rewrite OCR expected of the base pipelines in place
node tools/i18n/sync-ocr.mjs --check    # dry-run validation, wired into pnpm check (check:ocr)
```

- **expand**: JSONC-aware in-place replacement — comments and formatting are preserved; running it again is a no-op.
- **check**: fails when an `expected` array differs from what the mapping would produce, or when a Chinese text outside the mapping (and not registered as untranslatable) shows up.

### Detection and write-back rules

- OCR node detection: `recognition == "OCR"` or `recognition.type == "OCR"`; OCR sub-recognitions inside Or/And composites (`any_of`/`all_of`, nested included) are covered as well;
- `expected` is resolved as `recognition.param.expected` → `recognition.expected` → node-level `expected`; both a single string and a string array are accepted, and the write-back is always an array;
- The five languages are expanded from the mapping; identical texts across languages are de-duplicated and missing languages are skipped;
- The write-back keeps a `// @i18n-src: ["original", ...]` comment above the array to pin down the author's intent: re-runs rebuild from that comment, so stale expansion products never accumulate after mapping changes;
- Author-written non-mapping items (regexes, numbers, etc.) are preserved verbatim in the array.

### ROI widening

When the longest display width across the five languages exceeds the original text, the tool widens the recognition area: `roi` is never modified; instead the `roi_offset` right margin is raised to "base width × five-language/Chinese width ratio" (MaaFW semantics), clamped to the 720p baseline screen width of 1280; when `roi` references another node, edits only ever touch the referencing node's own `roi_offset`, never the referenced node. `only_rec` nodes are treated the same: count-reader nodes (`5/5`-style expected) produce no translation expansion and are naturally unaffected, while a text-flag node left unwrapped would get clipped on wider-language clients — a more certain failure than the false-match risk widening introduces. Nodes with no `roi` skip this step. Widening is idempotent by "raise if short of target": a right margin already at the computed value is left alone, and cascaded widening along roi reference chains is iterated to a fixed point inside the tool.

### The `@i18n-skip` escape hatch

For nodes that intentionally keep a regex or fragment and should not be translated, add a comment inside the `expected` array:

```json
"expected": [
    // @i18n-skip truncated match; full-sentence lookup is meaningless
    "^售"
],
```

The comment must be inside the array brackets; once present, the tool leaves the whole node untouched and the check no longer requires it to be expandable.

## Five-language item names

`data/combat/items.json` commits five-language `names` directly (short names for a few dozen materials, shipped with releases). Adding items and verifying version renames are the maintainer's responsibility, merged in as normal PRs; when adding items, keep the existing rarity grouping and ordering.

## Authoring rules

When adding or modifying pipelines:

- Write OCR `expected` as **complete Simplified Chinese text** by default and let the tool expand it from the mapping; never hand-write five-language arrays;
- Only add `@i18n-skip` when a regex or fragment is genuinely required, and state the reason in the comment;
- Focus text is always `$Focus.<node name>`, with every declared language added to `locales/*.json`;
- Never write a single-language `expected` or focus in an overseas overlay — it would override everything back down to one language;
- For text missing from the mapping, extend the mapping first, then run the expansion; the check catches anything left over;
- Generated pipelines (`tools/pipeline-generate/`) maintain five-language `names` maps inside the generator, bake multi-language `expected` directly, and fail hard on missing translations.

## Division of labour with overseas overlays

Once base is expanded, `resource/global_*/pipeline` and `resource/tw/pipeline` keep only **language-independent regional differences**: startup package names, entry actions, channel resource selectors, and so on. Recognition fields and focus never go into overlays.

## Maintenance checklist for game updates

When a game update introduces new UI text:

1. **Maintainer**: review and extend the mapping (five-language translations of new text, ambiguity resolution, version-rename checks) and commit the mapping diff;
2. **All contributors**: run the expansion to write the pipelines back, and review the diff;
3. Merge new item names into `items.json`;
4. Pass `pnpm check` and `pnpm check:py` and submit with the version-adaptation PR.

## Agent text: deliberately not done

Agent-side i18n has no technical blockers — MaaFW PI v2 injects the `PI_CLIENT_LANGUAGE` environment variable when starting the agent, and a `locales/<lang>/agent.json` namespace extension (see [Interface Localisation](./i18n.md)) would be enough to support it. After evaluation, M9A decides **not** to build this layer:

- All 354 M9A agent messages go to the logger (log panel) and are mostly process diagnostics (122 of them debug-level); the primary UX text lives in focus and the pipelines;
- The main readers of those logs are the maintainers debugging issues, for whom the Chinese originals are more useful; overseas users reporting problems paste the originals anyway;
- Translating 354 messages × 4 languages ≈ 1400 translation units of ongoing maintenance is out of proportion to the benefit.

When to re-evaluate: if the agent ever needs to push messages to the user proactively (e.g. presenting battle status or result summaries as toasts — the Python binding can do this by running a throwaway node that carries focus), wire **that new batch of text** to `PI_CLIENT_LANGUAGE` (`agent/utils/pienv.py` already defines the constant) and a `locales/<lang>/agent.json` namespace — do not backfill the existing logs.

## Boundaries and known limitations

- Template images and initial ROIs still require real emulator screenshots (1280x720 baseline); the tool only widens existing ROIs;
- The mapping covers texts that have appeared; new text is blocked by the check until the mapping is extended — this is intended;
- Server-authoritative data such as drop rates is out of scope; the mapping and item names cover names and declarative data only;
- Context disambiguation (same word, different translation) is resolved by the maintainer when updating the mapping; if a translation does not match the actual screen, fix it via `node_overrides`.

## Status

- **Focus messages**: landed (33 `$Focus.*` entries; validation wired into `pnpm check`);
- **OCR mapping and sync tool**: landed (275 mapping entries, 71 registered untranslatable items; 376 of the 536 OCR nodes expanded into five languages, the rest being regexes/fragments that need no translation; `check:ocr` wired into `pnpm check`).
