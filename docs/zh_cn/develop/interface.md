---
order: 3
icon: tdesign:system-interface
---
# interface.json 编写

::: tip
参考资料：
[interface.schema.json](https://github.com/MaaXYZ/MaaFramework/blob/main/tools/interface.schema.json)
[ProjectInterfaceV2协议](https://maafw.xyz/docs/3.3-ProjectInterfaceV2)
:::

`interface.json` 是 MaaFramework 的标准化项目结构声明，旨在提供图形化界面菜单配置。  
`interface_cli.json` 则是为命令行版本提供配置。

## 整体结构

主要字段包括：

- `interface_version`: 接口版本号，当前为 2，必填
- `name`: 项目唯一标识符
- `label`: 项目显示名称（可选，支持国际化）
- `icon`: 项目图标路径（可选）
- `version`: 项目版本号
- `github`: GitHub 仓库地址
- `contact`: 联系方式信息
- `license`: 许可证信息
- `welcome`: 欢迎消息/公告（可选）
- `description`: 项目描述（可选）
- `languages`: 多语言支持配置（可选）
- `controller`: 控制器配置数组
- `resource`: 资源配置数组
- `agent`: 代理配置对象
- `task`: 任务配置数组
- `option`: 选项定义对象

## controller

控制器配置数组，每个控制器包含：

- `name`: 控制器唯一标识符（必填）
- `label`: 显示名称（可选，支持国际化）
- `description`: 控制器描述（可选）
- `icon`: 控制器图标（可选）
- `type`: 控制器类型，`"Adb"` 或 `"Win32"`（必填）
- `display_short_side` / `display_long_side` / `display_raw`: 分辨率设置（可选）
- `adb`: Adb 控制器配置（type 为 Adb 时）
- `win32`: Win32 控制器配置（type 为 Win32 时）

::: tip
在 V2 协议中，Adb 控制器的 input/screencap 由 MaaFramework 自动检测和选择最优方式，无需手动配置。
:::

对于 Win32 控制器，可配置：

- `class_regex`: 窗口类名正则表达式
- `window_regex`: 窗口标题正则表达式
- `mouse` / `keyboard` / `screencap`: 控制方式（可选，不提供则使用默认）

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

资源配置数组，每种资源包含：

- `name`: 资源包唯一标识符（必填）
- `label`: 显示名称（可选，支持国际化）
- `description`: 资源描述（可选）
- `icon`: 资源图标（可选）
- `path`: 资源路径数组（必填）
- `controller`: 支持的控制器列表（可选，不指定则支持所有控制器）

::: tip
对于 `path` 数组，M9A 按顺序加载资源。若存在相同名称的任务/节点，后加载的资源会覆盖前面的资源（顶级键替换）。
:::

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

任务配置数组，每个任务包含：

- `name`: 任务唯一标识符（必填）
- `label`: 显示名称（可选，支持国际化）
- `entry`: 任务入口，pipeline 中 Task 的名称（必填）
- `default_check`: 是否默认选中（可选，默认 false）
- `description`: 任务描述（可选）
- `icon`: 任务图标（可选）
- `resource`: 支持的资源包列表（可选，不指定则在所有资源包中可用）
- `pipeline_override`: 任务参数覆盖（可选）
- `option`: 任务配置项列表（可选）

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

选项定义对象，键为选项标识符，值为选项配置。每个选项包含：

- `type`: 选项类型（可选，默认 `"select"`）
  - `"select"`: 下拉选项框
  - `"input"`: 用户输入框
  - `"switch"`: 开关选择（Yes/No）
- `label`: 显示标签（可选，支持国际化）
- `description`: 选项描述（可选）
- `icon`: 选项图标（可选）
- `cases`: 可选项数组（`select`/`switch` 类型必填）
- `default_case`: 默认选项名称（`select` 类型可选）
- `inputs`: 输入字段配置（`input` 类型必填）
- `pipeline_override`: pipeline 覆盖（`input` 类型使用）

### select 类型选项

最常用的选项类型，举例：

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

`default_case` 为默认选项，从 `cases` 中选择一个。

### switch 类型选项

开关类型，仅支持两个 cases，需使用 `"Yes"`/`"No"` 作为 name：

```json
{
    "刷完全部体力": {
        "type": "switch",
        "label": "刷完全部体力",
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

### input 类型选项

用户输入类型，通过 `inputs` 定义输入字段：

```json
{
    "自定义关卡": {
        "type": "input",
        "label": "自定义关卡",
        "inputs": [
            {
                "name": "章节号",
                "label": "章节号",
                "description": "关卡章节号，用阿拉伯数字表示",
                "default": "4",
                "pipeline_type": "string",
                "verify": "^\\d+$",
                "pattern_msg": "请输入数字"
            }
        ],
        "pipeline_override": {
            "EnterTheShow": {
                "next": "MainChapter_{章节号}"
            }
        }
    }
}
```

input 字段说明：

- `name`: 字段标识符
- `label`: 显示名称
- `description`: 字段描述
- `default`: 默认值
- `pipeline_type`: 数据类型（`"string"` / `"int"` / `"bool"`）
- `verify`: 正则表达式校验
- `pattern_msg`: 校验失败提示

在 `pipeline_override` 中使用 `{字段名}` 引用输入值。

## 国际化支持

支持国际化的字段可以直接使用具体值（如路径、URL、文本），也可以使用 `$` 前缀进行国际化。

**国际化机制：**
    - 如果字段值**以 `$` 开头**，表示这是一个翻译键，需要从 `languages` 配置的翻译文件中读取实际值
    - 如果字段值**不以 `$` 开头**，则直接使用该值（路径、URL 或文本）

配置多语言：

```json
{
    "languages": {
        "zh_cn": "interface_zh.json",
        "en_us": "interface_en.json"
    },
    "label": "$project_name",        // 使用翻译键
    "contact": "CONTACT",             // 直接使用文件路径
    "description": "这是直接文本"     // 直接使用文本
}
```

翻译文件示例（`interface_zh.json`）：

```json
{
    "project_name": "我的项目"
}
```

**支持国际化的字段：** `label`、`description`、`title`、`contact`、`license`、`welcome`、`icon` 等。

::: tip
对于 `contact`、`license`、`welcome`、`description` 等字段：

- 可以是文件路径（相对于 interface.json）
- 可以是 URL
- 可以是直接文本
- 内容支持 Markdown 格式
- 使用 `$` 前缀可实现国际化

对于 `icon` 字段，`$` 前缀用于路径本地化（不同语言使用不同图标文件）。
:::

## version

版本号。不必填写，CI 构建时会自动生成。
