---
order: 2
icon: ri:treasure-map-line
---

# Item Data Protocol

> [!TIP]
>
> This document describes the storage format and structure of various item data in the game

## Resource Location

- Roguelike (SOS) items: `assets/resource/data/sos/items.json`
- Combat items: `assets/resource/data/combat/items.json`

## SOS Roguelike Item Data

### File Structure

```jsonc
{
    "artefacts": {      // Creation data
        "attribute_type": []  // Creations grouped by attribute
    },
    "harmonics": {      // Harmonic resonance data
        "attribute_type": []  // Harmonic resonances grouped by attribute
    }
}
```

### Attribute Types

Five attribute types in the game:

- `Strength` - Strength attribute
- `Reaction` - Reaction attribute
- `Mystery` - Mystery attribute
- `Perception` - Perception attribute
- `Passion` - Passion attribute

### Creations

Creations are grouped by attribute, each containing all creation names related to that attribute.

```jsonc
{
    "artefacts": {
        "Strength": [
            "Tuning Fork Echo I",
            "Tuning Fork Echo II",
            "Glory Insignia",
            "Strength Charm",
            // ... more creations
        ],
        "Reaction": [
            "Devouring Horn I",
            "Dividing Copper Fish",
            // ... more creations
        ]
        // ... other attributes
    }
}
```

### Harmonic Resonances

Harmonic resonances are similarly grouped by attribute, each containing all harmonic resonance names related to that attribute.

```jsonc
{
    "harmonics": {
        "Strength": [
            "Inverted Blood",
            "Thin Stream of Blood",
            "Ancestral Connection",
            // ... more harmonic resonances
        ],
        "Reaction": [
            "Preparation",
            "Unexpected Awareness",
            // ... more harmonic resonances
        ]
        // ... other attributes
    }
}
```

### Usage Guide

This data is primarily used for:

1. **Item Recognition**: As a reference dictionary when OCR recognizes item names
2. **Item Selection**: Match items by attribute priority when automatically selecting items
3. **Data Validation**: Verify if recognized results are valid item names
