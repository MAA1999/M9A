---
order: 6
icon: ri:archive-line
---

# Warehouse Inventory Protocol

> [!TIP]
>
> This document describes the 「Warehouse Inventory」(WarehouseInventory) task and its data
> protocol. The task scans the warehouse material page for all materials with templates,
> writes their quantities to `data/combat/warehouse_inventory.json`, which future features
> (e.g. auto-replenish, material shortage hints) can read.

## Architecture Overview

| File                                              | Content                                                                                       |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `tasks/WarehouseInventory.json`                   | Task entry definition (group: `daily`)                                                        |
| `resource/base/pipeline/warehouse_inventory.json` | Flow: enter warehouse → confirm tab → scan → exit warehouse → return to main screen           |
| `agent/custom/action/warehouse_inventory.py`      | `WarehouseInventoryScan`: 3-segment round-trip scan + count OCR + majority voting + JSON dump |
| `data/combat/items.json`                          | Material data source (grouped by rarity); decides which materials are scanned                 |
| `resource/base/image/Warehouse/Item-<id>.png`     | Material icon templates (used by TemplateMatch)                                               |
| `data/combat/warehouse_inventory.json`            | Runtime output: quantity snapshot (gitignored, not committed)                                 |

## Pipeline Flow

```
WarehouseInventory (entry)
  └─ WI_EnterWarehouse    OCR「仓库」→ click to enter warehouse (retry if not found)
       └─ WI_WarehouseFlag  OCR「素材」tab → confirm material page
            └─ WI_Scan     Custom action: WarehouseInventoryScan (core scan)
                 └─ WI_ExitWarehouse  TemplateMatch back button → exit warehouse
                      └─ WI_AtMain     OCR「仓库」entry → confirm main screen
                           └─ [JumpBack]ReturnMain
```

## Scan Mechanism (WarehouseInventoryScan)

### Data Source & Template Filtering

- Data source: `data/combat/items.json` (gold/yellow/purple/blue/green, 46 farmable materials)
- **Only materials with templates are scanned**: a material is included only if
  `resource/base/image/Warehouse/Item-<id>.png` exists. Missing templates are skipped and
  recorded — **adding a new material only requires adding a template image, no code change**.

### Scroll-to-Top & Round-Trip Scan

Before scanning, swipe up 6 screens to reach the top of the list, ensuring full coverage
from the top, then run a 3-segment round-trip scan
(down 6 → up 6 → down 6 screens, 12 screens total) so every material passes the screen 2-3
times. The scan stops early once every material has at least 3 valid readings.

### Count Recognition (BF_ItemCount OCR)

The count digits sit at the bottom of the grid cell below the icon; position depends on
icon height:

| Icon height                       | Digit position        | Offset group       |
| --------------------------------- | --------------------- | ------------------ |
| `h >= 80` (tall gold/purple/blue) | icon top `+82~95px`   | `(82, 85, 90, 95)` |
| `h < 80` (short green/blue)       | icon bottom `+2~10px` | `(h+2, h+6, h+10)` |

- Horizontal ROI: only the middle half of the icon (`dx = w*0.25, dw = -w*0.5`) to avoid
  swallowing the rarity decoration bars on both sides (digit 1 + decoration lines can be
  read as 11 for Golden Fleece)
- Each offset is OCR'd once; take the longest digit group in the text (real count has more
  digits than stray edge noise)
- Measured: the 50% width covers 1~5 digits (e.g. 20023/1919); widening to 70% pulls in
  golden decoration bars and is not usable

### Anti-Misread: Multi-Reading Majority Vote

A single reading can be polluted by decoration (3→31, 1→11, 231→21). Two levels of
correction:

1. **Multi-offset per screen**: 4/3 offsets OCR the same icon, take the majority
2. **Multi-screen round trip**: readings accumulate across passes; final answer is the
   majority value, or the longest-digit value when there is no majority (truncation errors
   are shorter than the true value)

## Output Format

`data/combat/warehouse_inventory.json`:

```jsonc
{
    "updated_at": "2026-08-06 15:12:18", // scan completion time
    "counts": {
        "110101": 81, // material id → count
        "110102": 60,
    },
    "skipped": [], // ids with icon found but count OCR failed
    "materials": {
        // material metadata (id → name/rarity)
        "110101": {"name": "颤颤之齿", "rarity": "green"},
    },
}
```

- Materials absent from `counts` were not found in the warehouse (counted as 0, not written)
- `skipped` materials must NOT be treated as 0 (icon visible but count unreadable);
  manual confirmation required
- This file is a runtime artifact and is gitignored

## Maintenance Guide

- **Adding a material**: add `"id": {"name": "材料名"}` to the matching rarity group in
  `data/combat/items.json`, and place the template at
  `resource/base/image/Warehouse/Item-<id>.png` (1280x720 baseline, dark-background icon)
- **Template requirements**: must match the in-game warehouse icon rendering (size, tone);
  best captured by cropping from a warehouse screenshot
- **Misread debugging**: check `多次读数不一致` (inconsistent readings) warnings in
  `debug/custom/<date>.log`, identify the decoration interference, then adjust the
  empirical offsets documented in the code comments
