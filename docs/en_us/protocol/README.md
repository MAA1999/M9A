---
title: Protocol Docs Overview
description: Overview of the M9A protocol docs — storage formats for activity, combat, item and warehouse inventory data, plus roguelike mode adaptation.
icon: basil:document-solid
index: false
dir:
    title: Protocol Docs
    order: 3
---

# Protocol Docs

This section records the contracts between M9A and the game data: how that data is stored in the repository, and what rules to follow when new content has to be adapted. Read it before changing anything under `data/` or wiring up a new event.

## Game data

- [Activity Data Protocol](activity.md) — the storage format for game version and activity data, and how files are split per language.
- [Combat Data Protocol](combat.md) — the structure of combat-related data such as combat items and the drop index.
- [Item Data Protocol](items.md) — the structure and fields of the various item data files.
- [Warehouse Inventory Protocol](warehouse-inventory.md) — the architecture of the Warehouse Inventory task and the format it writes to `config/warehouse_inventory.json`.

## Gameplay adaptation

- [Out-of-Combat Protocol: Syndrome of Silence Roguelike Assistant](sos.md) — the resource directory and top-level data structures for the roguelike mode.
