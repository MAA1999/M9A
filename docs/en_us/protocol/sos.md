---
order: 1
icon: ri:game-fill
---

# Out-of-Combat Protocol: Syndrome of Silence Roguelike Assistant

> [!TIP]
>
> Please note that JSON files do not support comments. Any comments in the text are for demonstration only and should not be copied directly.

## Resource Location

Related resources are stored under `assets/resource/data/sos`.

## Field Description

### Top-Level Structure

```jsonc
{
    "types": [],           // Array of node types, listing all possible node types
    "<NodeTypeName>": {}   // Configuration for each node type
}
```

### Node Type List

The `types` field defines all supported node types:

- `Completed Node` - Node that has been completed
- `Main Path` - Main story event
- `Encounter on the Road` - Side event
- `Treasure Site` - Obtain treasure
- `Rest Area` - Recovery and rest
- `Shopping Opportunity` - Spend "Goldfinch Coins" to buy items
- `Craftsman's Hand` - Upgrade and replace creations
- `Encounter` - Simple battle
- `Extra Encounter` - Battle with special rules
- `Conflict` - More difficult elite battle
- `Perilous Situation` - Increasingly difficult chained battle challenge
- `Hard Battle` - Extremely dangerous boss battle
- `Dialogue` - Dialogue event node

### Node Configuration Structure

Each node type contains the following fields:

```jsonc
{
    "event_name_roi": [x, y, w, h],  // Region of interest for event name recognition, null means no event name recognition needed
    "actions": [],                    // Default action sequence (for nodes without event name or for general handling)
    "events": {},                     // Event-specific action configuration (optional)
    "interrupts": []                  // List of interrupt handler nodes (optional)
}
```

#### Node Type Classification

**Nodes without event name** (directly execute `actions`):

- `Shopping Opportunity`
- `Encounter`
- `Extra Encounter`
- `Conflict`
- `Hard Battle`
- `Craftsman's Hand`

**Nodes with event name** (need to recognize the specific event, execute the corresponding configuration in `events`):

- `Main Path`
- `Rest Area`
- `Treasure Site`
- `Perilous Situation`

### Action Types

#### 1. RunNode - Run a node

Run a predefined process node

```jsonc
{
    "type": "RunNode",
    "name": "NodeName"
}
```

Common nodes:

- `SOSTeamSelect` - Team selection
- `SOSCombat` - Battle process
- `SOSContinue` - Continue/confirm button
- `SOSEventEnd` - End event
- `BackButton` - Back button
- `SOSConfirm` - Confirm button

#### 2. SelectOption - Option selection

Select a dialogue or event option (vertically arranged)

```jsonc
{
    "type": "SelectOption",
    "method": "OCR" | "HSV",          // Recognition method: OCR text recognition or HSV color recognition
    "expected": ["Option1", "Option2"],  // For OCR: expected text(s) (required)
    "order_by": "Vertical",           // Sort order: Vertical or Horizontal, default is Vertical (optional)
    "index": 0                        // Option index, default 0 is the first, -1 is the last (optional)
}
```

**OCR method:**

- Select option by recognizing text content
- `expected` can be a string or an array of strings, matched in order
- A separate recognition node is created for each expected value

**HSV method:**

- Select option by color recognition
- Use the `index` parameter to specify which option to select

#### 3. SelectEncounterOption - Encounter option selection

Specialized for "Encounter on the Road" scenarios (horizontally arranged)

```jsonc
{
    "type": "SelectEncounterOption",
    "method": "OCR" | "HSV",          // Recognition method: OCR text recognition or HSV color recognition
    "expected": "Option text",        // For OCR: expected text (required)
    "order_by": "Vertical",           // Sort order for template recognition: Vertical or Horizontal, default is Vertical (optional)
    "index": 0                        // For HSV: option index, default 0 is the first, -1 is the last (optional)
}
```

**OCR method:**

- Select option by recognizing text content
- `expected` is a string specifying the expected text to recognize
- `order_by` is used for magnifier icon template recognition sorting, default is `Vertical`

**HSV method:**

- Select option by color recognition
- Use the `index` parameter to specify which option to select
- `order_by` is used for magnifier icon template recognition sorting, default is `Vertical`

### Interrupt Handler Nodes (Interrupts)

Interrupt handler nodes that may be triggered during action execution:

- `SOSSelectHarmonic` - Select Harmonic
- `SOSHarmonicObtained` - Harmonic obtained
- `SOSSelectArtefact` - Select Artefact
- `SOSArtefactsObtained` - Artefact obtained
- `SOSLoseArtefact` - Lose Artefact
- `SOSSelectResonator` - Select Resonator
- `SOSResonatorObtained` - Resonator obtained
- `SOSStatsUpButton` - Stats up button
- `SOSStatsUp` - Stats up
- `SOSNextMessage` - Next message
- `SOSContinue` - Continue button
- `SOSDice` - Dice event

### Event Configuration Examples

#### Simple Battle Node Example

```jsonc
"Conflict": {
    "event_name_roi": null,  // No event name recognition needed
    "actions": [
        {
            "type": "RunNode",
            "name": "SOSTeamSelect"  // 1. Select team
        },
        {
            "type": "RunNode",
            "name": "SOSCombat"  // 2. Enter battle
        }
    ]
}
```

#### Complex Event Node Example

```jsonc
"Rest Area": {
    "event_name_roi": [858, 72, 132, 33],  // Region for event name recognition
    "events": {
        "Club Visitor": {  // Specific event name
            "actions": [
                {
                    "type": "RunNode",
                    "name": "SOSContinue"  // 1. Click continue
                },
                {
                    "type": "SelectOption",
                    "method": "HSV",
                    "index": -1  // 2. Select the last option (HSV recognition)
                },
                {
                    "type": "RunNode",
                    "name": "SOSEventEnd"  // 3. End event
                }
            ],
            "interrupts": [  // Possible interrupts
                "SOSArtefactsObtained",
                "SOSStatsUpButton",
                "SOSStatsUp",
                "SOSLoseArtefact",
                "SOSNextMessage"
            ]
        }
    }
}
```

#### Event with Option Recognition Example

```jsonc
"Main Path": {
    "event_name_roi": [858, 72, 132, 33],
    "events": {
        "Journey Begins": {
            "actions": [
                {
                    "type": "RunNode",
                    "name": "SOSContinue"
                },
                {
                    "type": "SelectOption",
                    "method": "OCR",
                    "expected": [
                        "Mystery",    // Prefer these attributes
                        "Strength",
                        "Passion",
                        "Reaction",
                        "Perception"
                    ]
                },
                {
                    "type": "RunNode",
                    "name": "SOSEventEnd"
                }
            ],
            "interrupts": [
                "SOSSelectHarmonic",
                "SOSHarmonicObtained",
                "SOSStatsUp"
            ]
        }
    }
}
```

## Configuration Description

### ROI Region Description

`event_name_roi` defines the region for event name recognition, in the format `[x, y, width, height]`:

- `x`: X coordinate of the top-left corner
- `y`: Y coordinate of the top-left corner
- `width`: Width
- `height`: Height
- `null`: This node does not require event name recognition

### Execution Flow

#### 1. Node Selection Phase (SOSSelectNode)

1. Use neural network to recognize node type (from the `types` array)
2. Click the node and wait for UI response (up to 5 retries)
3. If `event_name_roi` is configured, recognize the event name in the specified region
4. Record the current node type and event name

#### 2. Node Processing Phase (SOSNodeProcess)

1. Determine whether event name recognition is needed based on node type:
   - **Nodes without event name**: Directly use the action sequence in `actions`
   - **Nodes with event name**: Find the corresponding event configuration in `events`
2. Execute each action in `actions` in order
3. Interrupt detection is performed before and after each action

#### 3. Action Execution Mechanism

For each action:

1. Try to execute the main action (up to 10 retries)
2. If execution fails, traverse the `interrupts` list for interrupt detection
3. If an interrupt event is detected, handle it immediately, then continue the main action
4. If all retries fail, return failure

#### 4. Interrupt Detection Mechanism

- Interrupt detection is triggered each time the main action fails
- Traverse the `interrupts` array in order
- If an interrupt event is detected, execute the corresponding task immediately
- After handling the interrupt, continue the main action

### Notes

- Actions are executed in the order of the `actions` array
- Each action is retried up to 10 times; timeout is considered failure
- Interrupt detection is triggered when the main action fails, not asynchronously
- OCR option recognition matches the `expected` array in order, stopping at the first match
- For HSV method, `index` -1 means the last option, 0 means the first
- Node click operation waits for UI freeze detection (500ms freeze, 3000ms timeout)
- If event name recognition fails, the entire node process fails and the task stops
- Unadapted events will log an error and stop task execution

### Development Suggestions

- When adding new events, first add the event configuration in the corresponding node type's `events`
- Interrupt nodes should be independently recognizable and executable tasks
- When using OCR option recognition, `expected` should include all possible correct option texts
- For complex event flows, it is recommended to split into multiple small actions for easier debugging and maintenance
