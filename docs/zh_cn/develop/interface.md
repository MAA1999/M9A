---
order: 3
icon: tdesign:system-interface
---
# interface.json 编写

> [!TIP]
>
> 参考资料：
> [interface.schema.json](https://github.com/MaaXYZ/MaaFramework/blob/main/tools/interface.schema.json)
> [ProjectInterface协议.md](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.2-ProjectInterface%E5%8D%8F%E8%AE%AE.md)

`interface.json` 旨在提供菜单配置。

## controller

对于 M9A 来说，固定选择 adb 方式，基本不需要改动。

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

资源配置。每种资源需要资源名 `name` 以及 资源路径 `path`，均为必填。

特别地，对于资源路径 'path'，M9A 按顺序加载资源，若是存在相同资源名，则后加载的资源会覆盖前面的资源。

以 B 服为例，资源配置如下：

```json
{
  "resources": [
        {
            "name": "B 服",
            "path": [
                "./resource/base",
                "./resource/bilibili"
            ]
        }
    ]
}
```

这里，`.` 是 M9A 项目根目录，`base` 文件夹是官服资源，`bilibili` 文件夹是 B 服覆盖官服的资源。

## task

任务列表。任务列表包含多个任务，而每个任务又有任务名 `name`、任务入口 `entry`、任务参数 `pipeline_override`、以及任务选项 `option`，其中 `name` `entry` 必填。

`pipeline_override` 中应为 pipeline node，并带有覆写参数，例如：

```json
{
    "name": "轶事派遣（角色故事请自行阅读）",
    "entry": "Anecdote",
    "pipeline_override": {
        "EnterTheActivityMain": {
            "template_doc": "修改为当期活动入口的template",
            "template": "Combat/Activity/LondonDawningEnterTheShow.png"
        }
    }
}
```

这里原 node 为：

```json
{
    "EnterTheActivityMain": {
        "doc": "进入当期活动主界面",
        "recognition": "TemplateMatch",
        "template_code": "在interface.json中修改template",
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

经过覆写，该 node 在执行“轶事派遣（角色故事请自行阅读）”任务时，实际执行效果等同于：

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

执行“轶事派遣（角色故事请自行阅读）”任务后，node 便会恢复原状。

`option` 则是根据你下面的具体设置来决定如何覆写 pipeline node。

## option

选项定义。每种选项有可选项 `cases` 以及 默认选项 `default_case`, 其中`cases`必填。

一般用 `cases`,举例：

```json
{
    "task": [
        {
            "name": "常规作战",
            "entry": "Combat",
            "option": [
                "作战关卡",
                "复现次数",
                "刷完全部体力",
                "吃全部临期糖"
            ]
        }
    ],
    "option":{
        "刷完全部体力": {
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

`defaul_case` 为默认选项，从 `cases` 中选择一个。

## version

版本。不必填写，ci install 时会自动生成。

## message

信息。目前为 `MaaPiCli` 运行时第一行输出的文字。
