---
order: 4
icon: ri:sword-line
---

# Combat Data Protocol

> [!TIP]
>
> This document describes the storage format and structure of combat-related data

## Resource Location

Combat data is stored in the `assets/resource/data/combat/` directory:

- `items.json` - Combat item data
- `drop_index.json` - Stage drop index

## items.json - Combat Item Data

### File Structure

```jsonc
{
    "gold": {},    // Gold rarity items
    "yellow": {},  // Yellow rarity items
    "purple": {},  // Purple rarity items
    "blue": {},    // Blue rarity items
    "green": {}    // Green rarity items
}
```

### Rarity Classification

Combat items are classified into five rarity levels:

- `gold` - Gold (highest rarity)
- `yellow` - Yellow (high rarity)
- `purple` - Purple (medium rarity)
- `blue` - Blue (normal rarity)
- `green` - Green (basic rarity)

### Item Data Format

Each item uses item ID as key, containing item name:

```jsonc
{
    "gold": {
        "111004": {"name": "Fruit of Discernment"},
        "111005": {"name": "Evergreen Sword"},
        "111006": {"name": "Golden Fleece"}
    }
}
```

## drop_index.json - Stage Drop Index

### File Structure

```jsonc
{
    "stage_code": [item_id_list]
}
```

### Stage Code Format

Stage code format: `"chapter-stage_difficulty"`

- Chapter: Number (e.g., `1`, `2`, `12`)
- Stage: Number (e.g., `1`, `14`, `21`)
- Difficulty:
  - `G` - Story difficulty
  - `E` - Perilous difficulty

Examples:

- `"1-1G"` - Chapter 1 Stage 1 Story difficulty
- `"12-21E"` - Chapter 12 Stage 21 Perilous difficulty

### Data Example

```jsonc
{
    "1-1G": [110501, 110101, 110201, 110301, 110401],
    "1-14E": [110102, 110101, 110201, 110301, 110401, 110501],
    "12-21E": [110904, 110903, 110101, 111102, 110902, ...]
}
```

## Usage Guide

This data is primarily used for:

1. **Item Recognition**: Identify items obtained during combat by ID or name
2. **Rarity Judgment**: Determine rarity based on item's rarity classification
3. **Drop Prediction**: Query possible item drops by stage code
4. **Drop Statistics**: Record and analyze drop distributions across different stages
