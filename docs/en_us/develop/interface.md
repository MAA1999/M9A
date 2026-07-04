---
order: 3
icon: tdesign:system-interface
---
# Writing interface.json

::: tip
Reference materials:
[interface.schema.json](https://github.com/MaaXYZ/MaaFramework/blob/main/tools/interface.schema.json)
[ProjectInterfaceV2 Protocol](https://maafw.xyz/docs/3.3-ProjectInterfaceV2)
:::

`interface.json` is the standardized project structure declaration for MaaFramework, designed to provide menu configuration for graphical interfaces.  
`interface_cli.json` provides configuration for the command-line version.

## Overall Structure

Main fields include:

- `interface_version`: Interface version number, currently 2, required
- `name`: Project unique identifier
- `label`: Project display name (optional, supports internationalization)
- `icon`: Project icon path (optional)
- `version`: Project version number
- `github`: GitHub repository URL
- `contact`: Contact information
- `license`: License information
- `welcome`: Welcome message/announcement (optional)
- `description`: Project description (optional)
- `languages`: Multi-language support configuration (optional)
- `controller`: Controller configuration array
- `resource`: Resource configuration array
- `agent`: Agent configuration object
- `task`: Task configuration array
- `option`: Option definition object

## controller

Controller configuration array, each controller contains:

- `name`: Controller unique identifier (required)
- `label`: Display name (optional, supports internationalization)
- `description`: Controller description (optional)
- `icon`: Controller icon (optional)
- `type`: Controller type, `"Adb"` or `"Win32"` (required)
- `display_short_side` / `display_long_side` / `display_raw`: Resolution settings (optional)
- `adb`: Adb controller configuration (when type is Adb)
- `win32`: Win32 controller configuration (when type is Win32)

::: tip
In V2 protocol, Adb controller's input/screencap are automatically detected and optimized by MaaFramework, no manual configuration needed.
:::

For Win32 controller, you can configure:

- `class_regex`: Window class name regex
- `window_regex`: Window title regex
- `mouse` / `keyboard` / `screencap`: Control methods (optional, uses default if not provided)

## agent

```json
"agent": {
    "child_exec": "python",
    "child_args": [
        "./agent/main.py",
        "-u"
    ]
}
```

## resource

Resource configuration array, each resource contains:

- `name`: Resource package unique identifier (required)
- `label`: Display name (optional, supports internationalization)
- `description`: Resource description (optional)
- `icon`: Resource icon (optional)
- `path`: Resource path array (required)
- `controller`: Supported controller list (optional, supports all controllers if not specified)

::: tip
For the `path` array, M9A loads resources sequentially. If tasks/nodes with the same name exist, later-loaded resources will override earlier ones (top-level key replacement).
:::

For example, for bilibili Server, the resource configuration is as follows:

```json
{
  "resources": [
        {
            "name": "bilibili Server",
            "path": [
                "./resource/base",
                "./resource/bilibili"
            ]
        }
    ]
}
```

Here, `.` is the root directory of the M9A project. The `base` folder contains official server resources, and the `bilibili` folder contains resources for Server B that overwrite the official server resources.

## task

Task configuration array, each task contains:

- `name`: Task unique identifier (required)
- `label`: Display name (optional, supports internationalization)
- `entry`: Task entry, the Task name in `pipeline` (required)
- `default_check`: Whether selected by default (optional, default false)
- `description`: Task description (optional)
- `icon`: Task icon (optional)
- `resource`: Supported resource package list (optional, available in all resource packages if not specified)
- `pipeline_override`: Task parameter override (optional)
- `option`: Task configuration item list (optional)

In `pipeline_override`, it should be a pipeline node with override parameters, for example:

```json
{
    "name": "Anecdote Dispatch (Please read character stories yourself)",
    "entry": "Anecdote",
    "pipeline_override": {
        "EnterTheActivityMain": {
            "template_doc": "Modify to the current event entry template",
            "template": "Combat/Activity/LondonDawningEnterTheShow.png"
        }
    }
}
```

The original node is:

```json
{
    "EnterTheActivityMain": {
        "doc": "Enter the main interface of the current event",
        "recognition": "TemplateMatch",
        "template_code": "Modify the template in interface.json",
        "roi": [
            885,
            123,
            340,
            183
        ],
        "action": "Click",
        "post_wait_freezes": {
            "time": 500,
            "target": [
                0,
                179,
                190,
                541
            ]
        }
    }
}
```

After overriding, this node will behave as follows when executing the "Anecdote Dispatch (Please read character stories yourself)" task:

```json
{
    "EnterTheActivityMain": {
        "recognition": "TemplateMatch",
        "template": "Combat/Activity/LondonDawningEnterTheShow.png",
        "roi": [
            885,
            123,
            340,
            183
        ],
        "action": "Click",
        "post_wait_freezes": {
            "time": 500,
            "target": [
                0,
                179,
                190,
                541
            ]
        }
    }
}
```

After executing the "Anecdote Dispatch (Please read character stories yourself)" task, the node will revert to its original state.

`option` determines how to override the pipeline node based on your specific settings below.

## option

Option definition object, key is option identifier, value is option configuration. Each option contains:

- `type`: Option type (optional, default `"select"`)
  - `"select"`: Dropdown selection box
  - `"input"`: User input box
  - `"switch"`: Switch selection (Yes/No)
- `label`: Display label (optional, supports internationalization)
- `description`: Option description (optional)
- `icon`: Option icon (optional)
- `cases`: Selectable items array (`select`/`switch` type required)
- `default_case`: Default option name (`select` type optional)
- `inputs`: Input field configuration (`input` type required)
- `pipeline_override`: Pipeline override (`input` type usage)

### select Type Option

The most commonly used option type, example:

```json
{
    "task": [
        {
            "name": "Regular Combat",
            "entry": "Combat",
            "option": [
                "Combat Stages",
                "Use All Stamina"
            ]
        }
    ],
    "option": {
        "Use All Stamina": {
            "type": "select",
            "cases": [
                {
                    "name": "Yes",
                    "pipeline_override": {
                        "AllIn": {
                            "enabled": true
                        }
                    }
                },
                {
                    "name": "No",
                    "pipeline_override": {
                        "AllIn": {
                            "enabled": false
                        }
                    }
                }
            ]
        }
    }
}
```

`default_case` is the default option, selected from `cases`.

### switch Type Option

Switch type, supports only two cases, must use `"Yes"`/`"No"` as name:

```json
{
    "Use All Stamina": {
        "type": "switch",
        "label": "Use All Stamina",
        "cases": [
            {
                "name": "Yes",
                "pipeline_override": {
                    "AllIn": {
                        "enabled": true
                    }
                }
            },
            {
                "name": "No",
                "pipeline_override": {
                    "AllIn": {
                        "enabled": false
                    }
                }
            }
        ]
    }
}
```

### input Type Option

User input type, defines input fields via `inputs`:

```json
{
    "Custom Stage": {
        "type": "input",
        "label": "Custom Stage",
        "inputs": [
            {
                "name": "Chapter Number",
                "label": "Chapter Number",
                "description": "Stage chapter number in digits",
                "default": "4",
                "pipeline_type": "string",
                "verify": "^\\d+$",
                "pattern_msg": "Please enter a number"
            }
        ],
        "pipeline_override": {
            "EnterTheShow": {
                "next": "MainChapter_{Chapter Number}"
            }
        }
    }
}
```

Input field descriptions:

- `name`: Field identifier
- `label`: Display name
- `description`: Field description
- `default`: Default value
- `pipeline_type`: Data type (`"string"` / `"int"` / `"bool"`)
- `verify`: Regex validation
- `pattern_msg`: Validation failure message

Use `{field_name}` in `pipeline_override` to reference input values.

## Internationalization Support

Fields that support internationalization can use direct values (paths, URLs, text) or use the `$` prefix for internationalization.

**Internationalization mechanism:**

- If a field value **starts with `$`**, it's a translation key that needs to be looked up in the translation files configured in `languages`
- If a field value **does not start with `$`**, the value is used directly (path, URL, or text)

Configure multi-language:

```json
{
    "languages": {
        "zh_cn": "interface_zh.json",
        "en_us": "interface_en.json"
    },
    "label": "$project_name",        // Use translation key
    "contact": "CONTACT",             // Direct file path
    "description": "Direct text"     // Direct text
}
```

Translation file example (`interface_zh.json`):

```json
{
    "project_name": "My Project"
}
```

**Fields supporting internationalization:** `label`, `description`, `title`, `contact`, `license`, `welcome`, `icon`, etc.

::: tip
For `contact`, `license`, `welcome`, `description` fields:

- Can be a file path (relative to interface.json)
- Can be a URL
- Can be direct text
- Content supports Markdown format
- Use `$` prefix for internationalization

For the `icon` field, the `$` prefix is used for path localization (different icon files for different languages).
:::

## version

Version number. No need to fill in; it will be automatically generated during CI build.
