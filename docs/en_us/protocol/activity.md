---
order: 3
icon: ri:calendar-event-line
---

# Activity Data Protocol

> [!TIP]
>
> This document describes the storage format and structure of game version and activity data

## Resource Location

Activity data is stored by language in the `assets/resource/data/activity/` directory:

- `cn.json` - Simplified Chinese (CN Server)
- `en.json` - English (Global Server)
- `jp.json` - Japanese (JP Server)
- `tw.json` - Traditional Chinese (TW Server)

## File Structure

```jsonc
{
    "version_number": {
        "version_name": "Version Name",
        "start_time": start_timestamp,
        "end_time": end_timestamp,
        "activity": {
            // Activity configuration
        }
    }
}
```

## Field Description

### Top-level Fields

- `version_number`: Game version number, format `"x.y"` or `"spXX"` (e.g., `"2.6"`, `"3.1"`, `"sp01"`)
- `version_name`: Version name (e.g., `"Madness and Civility"`, `"Spring of Florence"`)
- `start_time`: Version start time, Unix timestamp (milliseconds)
- `end_time`: Version end time, Unix timestamp (milliseconds)
- `activity`: Activity configuration for this version

### Activity Types

#### combat - Combat Activity

Main or side story combat activities.

```jsonc
{
    "combat": {
        "event_type": "MainStory" | "SideStory",  // Activity type
        "start_time": start_timestamp,
        "end_time": end_timestamp,
        "override": {}  // Optional: override configuration
    }
}
```

**event_type Description**:

- `MainStory` - Main story activity
- `SideStory` - Side story activity

#### anecdote - Anecdote Activity

Anecdote collection activities.

```jsonc
{
    "anecdote": {
        "start_time": start_timestamp,
        "end_time": end_timestamp,
        "override": {}  // Optional: override configuration
    }
}
```

#### re-release - Rerun Activity

Reruns of past activities.

```jsonc
{
    "re-release": {
        "name": "Activity Name",
        "alias": "Activity Alias",
        "start_time": start_timestamp,
        "end_time": end_timestamp,
        "override": {}  // Optional: override configuration
    }
}
```

## Override Configuration

### Overview

The `override` field is used to override default node recognition and action configurations to adapt to special interfaces or flows of specific activities.

### Structure

```jsonc
{
    "override": {
        "node_name": {
            "recognition": {},  // Recognition configuration
            "action": {},       // Action configuration
            "next": [],         // Next node list
            "focus": {}         // Focus configuration (for hint messages)
        }
    }
}
```

### Configuration Description

`override` is used to override default node configurations and supports the following fields:

- `recognition` - Override recognition configuration (recognition area, recognition type, expected content, etc.)
- `action` - Override action configuration (click position, swipe parameters, etc.)
- `next` - Override next node list
- `focus` - Set focus hint messages (for displaying warnings or instructions)

### Configuration Examples

#### Example 1: Override Recognition Area

```jsonc
{
    "override": {
        "FlagInActivityMain": {
            "recognition": {
                "param": {
                    "roi": [1029, 33, 96, 22],
                    "expected": "Achievement",
                    "only_rec": true
                }
            }
        }
    }
}
```

#### Example 2: Override Action Target

```jsonc
{
    "override": {
        "EnterTheActivityMain": {
            "action": {
                "param": {
                    "target": [881, 127, 156, 55]
                }
            }
        }
    }
}
```

#### Example 3: Override Next Node

```jsonc
{
    "override": {
        "JudgeDuringRe_release": {
            "next": ["ActivityMainChapter"]
        }
    }
}
```

#### Example 4: Set Focus Hint

```jsonc
{
    "override": {
        "focus": {
            "focus": {
                "Node.Action.Starting": "This task only applies to old version anecdotes, please complete manually"
            }
        }
    }
}
```

## Usage Guide

This data is primarily used for:

1. **Activity Judgment**: Determine which activities are currently running based on the current time
2. **Version Recognition**: Recognize the current game version
3. **Interface Adaptation**: Adapt to special interfaces of different activities through override configuration
4. **Flow Customization**: Customize dedicated execution flows for specific activities
