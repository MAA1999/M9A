---
order: 6
icon: mdi:information-outline
---
# Feature Introduction

## Start Game

Start the game and wait for it to enter the main interface.

::: warning
This feature is currently not supported on the Global server PC client. If you need this feature, please configure it in Software Settings → Launch Settings.
:::

## Collect Wasteland

Collect wasteland production, including the following options:

- **Wellspring**: Collect wellspring production
- **Gather Magic Essence**: Collect magic essence production items
- **Deliver Orders**: Complete order delivery

## Daily Psychube (Will Analysis)

Farm daily free Will Analysis attempts, including the following options:

- **Double Analysis Bonus Battle**: Use stamina for combat when double analysis bonus is available
- **Consume Candy**: Automatically use psychube candy

## Regular Combat

Execute regular stage combat, including the following options:

- **Custom Combat Stage**: Manually specify combat stage
  - When disabled, you can select stage type (Main Story/Resource/Insight)
  - When enabled, you can input specific main story stage number
- **Consume Candy**: Automatically use candy
- **Custom Combat Count**: Specify combat count. It will consume all stamina when disabled.
- **Drop Statistics Report**: Report stage drop data

::: tip
Chapter 12 has added new materials, welcome to farm new stages to help update the one-image guide!
:::

## Event Farming

Farm event stages, including the following options:

- **Rerun Mode**: Choose whether it's a rerun event
- **Event Difficulty**: Select event stage difficulty
- **Consume Candy**: Automatically use candy
- **Custom Combat Count**: Specify combat count

::: warning
When a main story version is live, disabling rerun mode will skip the current task. If you need to farm main story stages, please use the Regular Combat feature.
:::

## Auto Deep Sleep

Automatically complete Deep Sleep battles, including the following options:

- **First Half Formation**: Select formation for the first half area
- **Second Half Formation**: Select formation for the second half area
- **Only Claim Weekly Shallow Sleep Rewards**: Only claim rewards without battling

::: note

- Avoid duplicating first and second half formations
- Supports both old and new formation systems
- Supports custom formation naming
- Future support for formations beyond the first four
:::

## Auto Awakening Dream

Automatically complete Awakening Dream battles, including the following options:

- **Awakening Dream First Half Formation**: Select formation for the first half area
- **Awakening Dream Second Half Formation**: Select formation for the second half area

::: note

- Avoid duplicating first and second half formations
- Supports both old and new formation systems
- Supports custom formation naming
- Future support for formations beyond the first four
:::

## Bank Shopping

Automatically purchase specified items at the bank, including the following options:

- **Single Account Mode**: In single account mode, it will skip tasks already executed in the current cycle
- **Counter Specials**: Purchase counter special items
- **Lower Counter**: Purchase lower counter items
- **Psychube Observation**: Purchase psychube observation
- **Dream Narrative**: Purchase dream narrative

## Claim Rewards

Claim various rewards, including the following options:

- **Claim Mail Rewards**: Collect rewards from mail
- **Claim Task Rewards**: Claim daily and weekly task rewards
- **Claim Roar Roar Jukebox**: Claim Roar Roar Jukebox rewards

## Suspended in the Rain: Mystery Sea

Complete "Think" weekly sweep task.

- **Single Account Mode**: In single account mode, it will skip tasks already executed in the current cycle

::: note
This feature only completes "Think" weekly sweep
:::

## Switch Account

Switch to the last account (accounts beyond the third one will be ignored).

::: note

- After switching, you can continue adding tasks for multi-account multi-configuration task execution
- Currently only supports Official server
- Recommended to set emulator resolution to 1280×720
:::

## Close Game

Close the game process.

::: warning
This feature is currently not supported on the Global server PC client. If you need this feature, please configure it in Software Settings → Launch Settings.
:::

## Outside Deduction: The Series of Dusks

Roguelike mode for farming credits, including the following options:

- **Catalyst Selection**: Choose the catalyst to use (only effective in non-fast mode)
- **Fast Mode**: When enabled, only uses Magic Lamp to farm the first floor
- **Deduction Difficulty**: Select deduction difficulty

### Fast Mode

::: warning

1. Before using fast mode, please fully level up `Engrave Growth - Song of Guidance` and `Engrave Growth - Building Code`
2. Please increase difficulty level as much as possible (difficulty 11 achieves maximum credit efficiency of 200%) and max out credit efficiency bonuses in the tech tree to prevent insufficient score of 2,500 leading to farming failure
:::

### Non-Fast Mode

::: tip

1. Before use, you can pin (mark) four characters in your box as deployment characters
2. Team composition should include a healer
3. Please ensure the last battle was in auto-battle mode before use, M9A cannot check if it's in auto-battle
:::

::: warning
M9A does not handle story content, tutorials, and other elements that only appear when playing roguelike for the first time. You need to complete these once manually before using this feature.
:::

::: note
Due to the complexity of this feature's implementation, strange issues may occur. If possible, please enable emulator screen recording. When encountering problems, try to preserve sufficient information (all content under `debug` and `logs` directories) so developers can quickly locate and resolve the issue. [Click here to submit an issue](https://github.com/MAA1999/M9A/issues/new/choose)
:::

#### Pinning Demonstration

![Pinning Demonstration](/images/en-us/introduction-pin-example.webp)

#### Pinning Successful

![Pinning Successful](/images/en-us/introduction-pin-success.webp)

## Outside Deduction: The Syndrome of Silence

Syndrome of Silence roguelike mode, including the following options:

- **Battle Formation**: Select battle formation to use
- **Carry a Good Companion**: Choose whether to carry a good companion
- **Difficulty Selection**: Select game difficulty
- **Instrument Selection**: Select instrument to use

::: warning

1. M9A does not process the gameplay instructions page that only appears when playing roguelike for the first time. Please manually progress to at least the second floor before using
2. M9A cannot check if it's in auto-battle mode. Please ensure your most recent battle was in auto-battle mode before using
:::

::: tip
Based on testing, it's best to choose difficulty 2 or 3 for the mission. Difficulty 4 makes it easy to die in battle
:::

---

## Standalone Tasks

The following tasks need to be **run independently** at specified interfaces and cannot be combined with other tasks:

### Rerun Event Stage Clear

Complete rerun event stage clear according to task list, including the following options:

- **Consume Candy**: Automatically use candy

::: note
This task completes tasks according to the task list, only supports previously completed rerun event stages
:::

### Artefact Masters (Rubbing Acrobatics)

Complete the first floor sweep of the arena.

::: warning
Please manually open the arena page before running this task
:::

### When the Alarm Sounds (High-Level Required)

Complete When the Alarm Sounds sweep, including the following options:

- **Sweep Difficulty**: Select sweep difficulty

::: warning
This feature does not change characters and takes all debuffs, so it's only suitable for high-level teams
:::

::: tip

- Recommended team: Big Three (37, Eternity, 6) + 66, Tooth Fairy + Tutu, or pursuit team
- Please manually open the When the Alarm Sounds main page (with "Rain Mark Tracking" and "Rain Mark Disposal" text in the middle) before use
- **Fast option**: Directly fight boss stage without 5th position buff, suitable for fully-built Big Three + double healer team
- Non-fast mode will max out 5th position buff before fighting boss, improving clear stability
- Test team: 37 + Eternity + Melmoth + Semmelweis + Tutu (note: place main DPS in 5th position)
:::

### Critter Crash

Quick farming in Critter Crash interface.

::: warning

- Start in Critter Crash interface
- Supports CN server version 3.2
- Please play two rounds manually first to raise alert level to 3 before using
:::

### Pre-Storm Protocol

Complete Pre-Storm Protocol mini-game, including the following options:

- **Pre-Storm Protocol Farming Mode**: Select corresponding mode based on tutorial progress

::: warning
This task needs to run independently, please navigate to the mini-game main page before running
:::

::: note
This task has two scenarios:

1. Have not defeated the boss on the third day of the tutorial (i.e., clicking "Start Simulation" does not lead to difficulty selection interface)
2. Have defeated the boss on the third day of the tutorial (i.e., clicking "Start Simulation" leads to difficulty selection interface)

Please select the corresponding option based on your situation
:::

### Auto Stage Clear (Testing)

Auto stage clear feature, currently in testing phase.

::: warning

- This feature is in testing and is not guaranteed to work properly
- Currently not available for the main story
- Please manually open the page you need to clear (such as current event, anecdote, etc.) before running this task
:::
