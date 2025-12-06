---
order: 3
icon: tdesign:system-interface
---
# Writing interface.json

> [!TIP]
>
> Reference materials:
> [interface.schema.json](https://github.com/MaaXYZ/MaaFramework/blob/main/tools/interface.schema.json)
> [ProjectInterface Protocol.md](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/3.2-ProjectInterface.md)

`interface.json` is designed to provide menu configuration.

## controller

For M9A, the adb method is fixed and generally does not require modification.

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

Resource configuration. Each resource requires a resource name `name` and a resource path `path`, both of which are mandatory.

Specifically, for the resource path 'path', M9A loads resources sequentially. If there are resources with the same name, the later-loaded resource will overwrite the earlier one.

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

Task list. The task list contains multiple tasks, and each task has a task name `name`, task entry `entry`, task parameters `pipeline_override`, and task options `option`, where `name` and `entry` are mandatory.

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

Option definitions. Each option has selectable `cases` and a default option `default_case`, where `cases` is mandatory.

Typically, use `cases`. For example:

```json
{
    "task": [
        {
            "name": "Regular Combat",
            "entry": "Combat",
            "option": [
                "Combat Stages",
                "Repetition Count",
                "Use All Stamina",
                "Consume All Temporary Sugar"
            ]
        }
    ],
    "option": {
        "Use All Stamina": {
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

## version

Version. No need to fill in; it will be automatically generated during CI installation.

## message

Message. Currently, it is the first line of output when `MaaPiCli` runs.
