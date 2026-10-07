---
order: 10
icon: material-symbols:inventory-2-outline-rounded
---

# Maintaining the Farming Material Catalog

Materials and stages of the "Smart Balanced Material Farming" task (depot maintain mode + the original balance logic) are fully data-driven: adding a material or a stage family never requires touching the decision code.

## Data flow

1. `data/combat/balanced_farming.json` — the catalog: item id → name / stage / difficulty (optional drop per run / reading source). The same file is also read by the original 智能均衡刷材料 (`BalancedFarmingAnalyze`), which only scans the depot — it skips `source: "character"` entries, so adding materials needs no extra work there
2. Target stock — the GUI "Depot maintain" master switch plus one switch per material with its own "target amount / candy uses", overridable per material in `config/depot_maintain_targets.json`
3. `config/warehouse_inventory.json` — the material snapshot: depot materials are written by the `WarehouseInventory` task, Dust/Sharpodonty are merged in by `DepotCurrencyInspect` (character-upgrade page reading)
4. `DepotMaintainPlan` (pipeline node `BF_Plan`) reads all three, picks the material with the largest deficit, overrides `SelectCombatStage`, `AllIn`, the round's candy and report settings, then enters battle

## Adding a material

1. Screenshot the game and crop the icons — **templates cannot be generated from the unpacked source art**: the warehouse icon is a zoom-cropped render of that art (masked correlation only 0.28–0.66, below the TemplateMatch threshold of 0.9; a leave-one-out validation of a "art × 0.66, centre-cropped" recipe scored 0/30). Both sets must be cropped from real screenshots:

    - depot → consumables page screenshot → `resource/base/image/Warehouse/Item-<id>.png` (tight crop, keeps the game's shadow; existing templates range from 59×83 to 124×93)
    - **Look-alike icons within one family (the tome items' 残篇/孤卷/全章 tiers) must keep only the family emblem, painting everything else pure green (RGB 0,255,0)** and relying on `green_mask` — the four families' icons correlate at 0.94+, so whole-tile matching reads another family's tile. `BF_ItemIcon` also pins `order_by: Score`: MaaFW defaults to taking the **leftmost** tile above threshold, not the best score (all four families were cross-read from the leftmost tile in practice)
    - the settlement screen when the material drops → `resource/base/image/Items_processed/Item-<id>.png` (drop row of 5 tiles at x 663/780/897/1014/1131, y 553, tile 83×56)

2. Append an entry to `data/combat/balanced_farming.json`:

    ```json
    "110103": { "name": "Biting Box", "stage": "7-26", "level": "Hard", "per_run": 1 }
    ```

    - `stage`: main story uses `chapter-stage` (e.g. `7-26`), resource stages use `family-stage` (e.g. `MA-06`)
    - `level`: `Hard` / `Story` / `None`
    - `per_run` (optional): conservative lower bound of drops per run, used to estimate the number of runs; defaults to 1 per run when omitted

3. Add the GUI entry for the new material in `tasks/BalancedFarming.json` (three places):
    - material switch: a `switch` option named after the material; its `Yes` case carries the participation marker and lists the settings option, its `No` case does nothing (off by default)

        ```json
        "<material name>": {
            "type": "switch",
            "label": "$Option.BalancedFarming.Material.<id>",
            "cases": [
                { "name": "No" },
                {
                    "name": "Yes",
                    "pipeline_override": { "BF_Plan": { "attach": { "mat_<id>": true } } },
                    "option": ["<material name>·设置"]
                }
            ]
        }
        ```

    - settings: a `<material name>·设置` input option with two fields `target_<id>` / `candy_<id>` (both `pipeline_type: string`, `verify: "^\\d*$"`, `default: ""`); its `pipeline_override` puts both onto `BF_Plan.attach` (**not `custom_action_param`** — MaaFW merges `attach` additively but replaces leaf keys, so one `custom_action_param` per material would keep only the last); label it with the shared key `$Option.BalancedFarming.Material.Settings`
    - wire it in: add `<material name>` to the `option` list of the "Depot maintain" case `Yes` (the order is the UI order)
    - add `Option.BalancedFarming.Material.<id>` to both `locales/zh_cn.json` and `locales/en_us.json` (display name, conventionally with the stage: `岩中典残篇（ME-02）`)
    - use a switch rather than a checkbox list: MFAAvalonia renders checkbox cases as a row of buttons with all sub-options stacked below (switch and content separated), while a `switch` card is "toggle row + nested sub-option box right under it", keeping the toggle and its two fields together
    - **materials that are not in the depot page** (currencies such as Dust 205 / Sharpodonty 203): mark the entry with `"source": "character"`, their readings come from the character-upgrade page instead (see the section below) and no warehouse icon template is needed; a refresh then visits the character page instead of running a depot scan

4. Validate:

    ```bash
    uv run --frozen pytest tests/test_depot_maintain.py -k shipped -q
    pnpm check
    ```

    The `-k shipped` case checks that the icon template, the chapter entry template and the stage entry node all exist; `pnpm check` covers the task-file schema and i18n keys.

## Codex (insight) stages and difficulties

The four insight families drop per difficulty tier (verified 2026-10-07 from the reward section of the wiki stage pages):

| Family (stage prefix)   | 02   | 04   | 06   |
| ----------------------- | ---- | ---- | ---- |
| 岩中典 (`ME`, 群山之声) | 残篇 | 孤卷 | 全章 |
| 星升典 (`SL`, 星陨之所) | 残篇 | 孤卷 | 全章 |
| 木娑典 (`SS`, 深林之形) | 残篇 | 孤卷 | 全章 |
| 兽涎典 (`BW`, 荒兽之野) | 残篇 | 孤卷 | 全章 |

- Write stages as `ME-02` / `SS-04` / `BW-06` with `level: None`; this matches the `tasks/Combat.json` stage options (they also use `ME-02` plus `TargetStageName_OCR.expected: ["02"]`), so navigation reuses the existing resource-stage flow with no new code.
- Drops scale with the **parity of the difficulty**: **even tiers (02/04/06) drop 2 per run, odd tiers (01/03/05) drop 1**; an odd tier costs slightly less stamina but yields only one, so it is the worse deal — the catalog therefore only uses even tiers and always writes `per_run: 2`. Even without a drop template the `ceil(deficit / 2)` estimate stays exact. Only when adding an odd-tier entry should `per_run` be 1 (and that is rarely worth adding).
- The catalog always uses the top tier (全章 = 06); on an account that has not unlocked it yet the stage navigation will fail — an endgame-account trade-off.
- These stages are absent from `drop_index.json`, so depot maintain self-reads the settlement row; **when a material has no drop template it automatically falls back to the per-run estimate** (exact for fixed drops, no per-battle reading and no warning spam).
- **Newly added materials do not take part in the drop report**: `drop_index.json` doubles as the report table, and planning looks the stage up in it — stages inside the table (the original materials) keep running `DropRecognition` in the victory chain as before, while stages outside it (e.g. the codex stages) have that node disabled for the round and only self-read the settlement row. Do not add new stages/items to `drop_index.json`.
- Reference implementation: `tasks/CharUpgrade.json` + `agent/custom/action/char_upgrade.py` farms the same materials (entering the stage by clicking 获取 on the character's insight panel, re-checking with `CUB_IsEnoughMaterial` after every battle, `drop_per_run: 2`); it relies on the game's own navigation, which is equivalent to this catalog's stage codes.
- The wiki item pages list only boxes (残典瓶/圣篇轴) as sources for 残篇/孤卷, but the stage-page reward sections prove 02/04 also drop them as fixed rewards — trust the stage pages.

## Where names, rarity and stages come from

Names/rarity/desc are not in the unpack (`datacfg_*.dat` is encrypted); take them from the huiji wiki (`res1999.huijiwiki.com`) instead: `Data:Item/map.json` (name ↔ id) and `Data:<id>.json` (`name/rare (1..5 → green/blue/purple/yellow/gold)/subType/sources`). Plain `curl` is blocked by the WAF (it serves a JS challenge page), so scrape with a same-origin fetch from the wiki page's browser console.

Two hard rules for picking stages (verified 2026-10-07):

- **Families share stages**: per `data/combat/drop_index.json` one stage often drops the whole material family (e.g. `7-26E` drops 110101–110104), so new entries can reuse the family's existing stage; when a tier only drops elsewhere, follow drop_index (e.g. 110504 狂人絮语 only at `3-13E`).
- **Synthesis products stay out of the catalog**: `111003-111006` (铂金通灵板 / 分别善恶之果 / 长青剑 / 金羊毛) are wasteland-synthesis products with no farming stage; list them in `items.json` only, for naming.

## Adding a stage family

1. Add the entry nodes to `resource/base/pipeline/combat.json` following the existing families: `ResourceChapter_<family>` → `ResourceChapter_<family>Enter`, recognizing the chapter label of that family (template or OCR)
2. Register the family in `STAGE_FAMILIES` in `agent/utils/material_catalog.py`: family code → entry node / display name / recognition templates
3. Run the same `-k shipped` validation

`SelectCombatStage` splits `family-stage` into the family code and the stage number (zero-padded to two digits) and hands it to the matching Enter node, so no Python code is needed for a new family.

## Target stock and per-material candy

- The GUI "Depot maintain" switch is the **master switch (off by default)**: while off, the task uses the original "farm the least-stocked" logic and the two items below are neither shown nor applied; turning it on reveals them
    - The off state travels as `BF_Plan.action.param.custom_action_param.depot_disabled` (case `No` in `tasks/BalancedFarming.json`); `DepotMaintainPlan` falls back to the legacy flow before parsing any target
- With the GUI "Depot maintain" switch on, every material is an **independent switch** (`switch` option): **turning it on reveals that material's own "target amount + candy uses" fields** (a PI case sub-option: while off they are neither shown nor applied), with the toggle and its fields in the same card. Turning no material on = no restriction (targets decide alone)
- Each material's two number fields (matching MAA depot maintain's "pick your materials, set each target"):
    - `Target amount` (`target_<id>`): **blank = do not farm this material**, `0` = skip it, a positive integer = the stock to top it up to
    - `Candy uses` (`candy_<id>`): max candies to use for this material when stamina is short — **blank = unlimited (follow the global "糖果" option)**, `0` = never, `N` = at most N
- Per-material candy is applied **dynamically every round** by the planner: `DepotMaintainPlan` remembers the task-wide baseline at the first round (`EatCandy.enabled` / `EatCandyStart.max_hit`, i.e. the node data after the global option applied) and then sets `enabled = global-on AND this material is not 0` and `max_hit = this material's count (blank restores the baseline)` for the chosen material only, recomputing every round so settings never leak between materials
    - `EatCandy.enabled` is exactly what `TargetCountCandyRoute` / `TargetCountDetermine` consult to decide whether candy may refill stamina; disabling it for one material does not affect the others
- `config/depot_maintain_targets.json`: **per-material overrides** of the GUI target amount. A template (every material set to `null`) is generated automatically the first time the task runs in depot-maintain mode; turn the ones you care about into positive integers:

    ```json
    {
        "_说明": "positive = override the GUI per-material target; null = unset (not farmed)",
        "110103": 200,
        "110203": null
    }
    ```

    - A `positive integer` overrides the GUI value; `null` (or simply not listing the material) means unset; keys starting with `_` are comments
    - An invalid value only drops that entry with a warning; the file wins over the GUI, but a material whose switch is off still does not participate

- A missing / corrupted config or invalid values are ignored, falling back to "unset"; the log states the reason

## Depot snapshot

- Source: `config/warehouse_inventory.json` written by the `WarehouseInventory` task; the Dust/Sharpodonty readings are written into the same file from the character-upgrade page
- Valid for 24 hours; the constant is `SNAPSHOT_TTL_HOURS` in `agent/custom/action/depot_maintain.py`
- **The two reading sets have separate timestamps**: depot readings use `updated_at` (written by the full scan), character-page readings use `currency_updated_at` (written by `write_snapshot_counts`). Refreshes judge freshness per source and only run the step that is needed (depot materials → full depot scan, character-page materials → a character-upgrade page visit). The depot scan rewrites the whole file but **keeps readings it did not scan**, so the character-page readings survive
- If the snapshot is still unusable after refreshing (scan/read failed), the original in-place depot scan flow is used instead
- Planning only reads the snapshot and never rewrites it

## Dust / Sharpodonty (read from the character-upgrade page)

These two currencies are not in the depot page; their counts only show in the top-right of the **character level-up panel** (Dust roi `[966,20,96,26]`, Sharpodonty roi `[1122,20,96,26]`).

- Reading flow (`resource/base/pipeline/depot_currency.json`, entry `DepotCurrencyInspect`): `DepotCurrencyRead` reuses the TrustReward task's character-page entry nodes (`EnterCharacter` → `FlagInCharacter` → `FirstCharacter` → `FlagInCharacterDetail`, with `next` overridden to continue into `CI_LevelPlus`, which taps the "等级 +" button) → opens the level-up panel → recognises the two numbers and merges them into the snapshot → taps back to home
    - The TrustReward chain assumes it starts at the home screen, so the nav entry `DepotCurrencyNav` carries the same `[JumpBack]ReturnMain` guard as the `WarehouseInventory` entry; only the runtime `next` lists are overridden, **`character.json` is untouched** and the TrustReward task itself is unaffected
- **Precision**: the panel shows an abbreviated value (e.g. `9792K`); the game uses K/M only (no Chinese units) and the unit-switch threshold is unknown — the parser converts by suffix without assuming a threshold. Thousand granularity gives a ≤1000 display error, irrelevant for targets in the tens of thousands to millions
- Stages: Dust at `LP-06` (12500 fixed per run), Sharpodonty at `MA-06` (9000 fixed per run; checked against the wiki stage pages 2026-10-08); neither is in the `drop_index` report table, so drops are self-read from the settlement row
- In the GUI, these two materials' **target-amount fields accept K/M suffixes** (`5M` = 5000000, verify regex `^\d*[KkMm]?$`); regular materials stay digits-only
- Any character works: the panel's top-right bar is the shared currency bar and also shows for max-level characters
- Navigation and rois were captured on device at 1280×720; re-run `DepotCurrencyInspect` on the emulator before changing them

## Settlement drop row and the stop rule (verified on device)

- The row is fixed: five 84×84 tiles spaced 117 apart at y 553..637; the `DropRegionRec` roi `[661,549,598,68]` covers every tile. The row scrolls horizontally, so recognition swipes up to 3 times
- Drop templates live in `resource/base/image/Items_processed/Item-<id>.png` (icon area 83×56, **no count text**, so matching is count-independent)
- The count band sits at the tile bottom: `[box.x + 22, 613, box.w - 44, 17]` — **below the `DropRegionRec` roi**, so it must be derived from the matched box; the digits are binarized first (`filter_digit_colors` in `agent/utils/settlement_drops.py`)
- Accumulation comes from one of two sources, chosen by `DepotMaintainAccumulate` at planning time: release builds read drop_core's `DropRecognitionState.total_drops` (requires the stage to have data in `drop_index.json` and the drop-report option to stay on); otherwise the settlement row is read directly. The same check decides whether `DropRecognition` stays enabled in this round's victory chain — stages outside the table never take part in the drop report
- On reaching the target the current batch is made the last one and the existing `TargetCountProgress` ends the run normally — nothing is clicked on the settlement screen (at the cost of at most 3 extra battles)
- One round tops up one material; `TargetCountFinish.next` is overridden back to `BF_Plan`, so the same task keeps topping up the next material with a deficit until: everything is satisfied, the previous round fought no battle (no stamina / cannot replay), or the round cap (`MAX_ROUNDS_PER_TASK`, 50) is hit. **Continuing on the same stage skips the trip home**: in depot-maintain mode `combat.depot_batch_end_node()` hands control straight back to `BF_Plan` (bypassing `TargetCountFinish`'s home button), and the planner re-opens the replay-count panel in place via `AllIn` whenever the stage page's replay button is on screen; switching material/stage, or ending a batch back at the home screen, still goes through the full `Combat` navigation. In-place batches never reach `TargetCountFinish`, so `DepotMaintainDone` prints the drop summary and returns home at the end
- Every battle writes the confirmed drop increment back into the depot snapshot; `updated_at` stays untouched (it marks the last full scan), only `counts` change
- Fixed-drop stages without a drop template run in estimate mode, where the **planning node writes back `battles actually fought × per_run` at the end of each round** (accounted per round number, so a re-entry after a snapshot rescan never double-writes). Without this the snapshot would stay stale and the multi-material loop would farm the same material over and over
- Depot icons (`Warehouse/Item-<id>.png`, tightly cropped) and drop icons (`Items_processed/`) are two different asset sets — cross-matching scores below 0.6. A material that should both participate in depot maintain and be counted per battle needs templates in both sets
- Entering combat uses a plain `next` (`BF_Plan → Combat`); **never `[JumpBack]Combat`** — a jump-back returns to the parent node and retries its `next` list, so a single-entry list re-enters combat forever

## Cropping from a live device (MaaMCP)

With the emulator connected you can do this in-session — no manual screenshots (verified 2026-10-07):

1. `find_adb_device_list` → `connect_adb_device` → `screencap` (saved at 720p)
2. To scroll, use `swipe` — **its coordinates are in 720p space** (native-resolution values are ignored); one screen up is `start (640, 620) → end (640, 300)` with `duration 2500`
3. Depot icons: tiles are about 120×120; crop `(tile.x + 2, tile.y + 2, 116, 94)` (dropping the bottom count bar) and save as `Warehouse/Item-<id>.png` (RGB, keep the tile background — matches the existing templates)
4. Self-check after cropping: `matchTemplate` against the same-resolution screenshot should score ≈ 1.000 with no higher hit elsewhere

Identifying an item without OCR: first the **seal colour** (岩中 = gold, 星升 = blue, 木娑 = green, 兽涎 = crimson), then cross-check the depot count against an older snapshot.

## Known limits

- The catalog only covers depot materials; currencies (dust, sharpodonty, …) use compact K/M numbers, have a drop template but no depot template, and drop_core explicitly skips them (`HELPER_ITEMS`), so they need a separate reading channel and are currently out of scope
- `per_run` now only caps the runs per round (defaulting to a conservative 1 per run); the actual stop is driven by observed drops

## Checks

```bash
pnpm format:py
pnpm check:py          # ruff + pyright(strict) + pytest
pnpm check             # formatting / schema / i18n / MaaFW integrity
```
