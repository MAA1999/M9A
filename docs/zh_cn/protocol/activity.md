---
order: 3
icon: ri:calendar-event-line
---

# 活动数据协议

> [!TIP]
>
> 本文档说明游戏版本和活动数据的存储格式和结构

## 资源存放位置

活动数据按语言分别存储在 `assets/resource/data/activity/` 目录下：

- `cn.json` - 简体中文（国服）
- `en.json` - 英文（国际服）
- `jp.json` - 日文（日服）
- `tw.json` - 繁体中文（港澳台服）

## 文件结构

```jsonc
{
    "版本号": {
        "version_name": "版本名称",
        "start_time": 开始时间戳,
        "end_time": 结束时间戳,
        "activity": {
            // 活动配置
        }
    }
}
```

## 字段说明

### 顶层字段

- `版本号`：游戏版本号，格式为 `"x.y"` 或 `"spXX"`（如 `"2.6"`, `"3.1"`, `"sp01"`）
- `version_name`：版本名称（如 `"疯癫与文明"`, `"翡冷翠之春"`）
- `start_time`：版本开始时间，Unix 时间戳（毫秒）
- `end_time`：版本结束时间，Unix 时间戳（毫秒）
- `activity`：该版本包含的活动配置

### 活动类型

#### combat - 战斗活动

主线或支线剧情战斗活动。

```jsonc
{
    "combat": {
        "event_type": "MainStory" | "SideStory",  // 活动类型
        "start_time": 开始时间戳,
        "end_time": 结束时间戳,
        "override": {}  // 可选：覆盖配置
    }
}
```

**event_type 说明**：

- `MainStory` - 主线剧情活动
- `SideStory` - 支线剧情活动

#### anecdote - 轶闻活动

轶闻收集类活动。

```jsonc
{
    "anecdote": {
        "start_time": 开始时间戳,
        "end_time": 结束时间戳,
        "override": {}  // 可选：覆盖配置
    }
}
```

#### re-release - 复刻活动

往期活动的复刻。

```jsonc
{
    "re-release": {
        "name": "活动名称",
        "alias": "活动简称",
        "start_time": 开始时间戳,
        "end_time": 结束时间戳,
        "override": {}  // 可选：覆盖配置
    }
}
```

## override 覆盖配置

### 概述

`override` 字段用于覆盖默认的节点识别和动作配置，以适配特定活动的特殊界面或流程。

### 结构

```jsonc
{
    "override": {
        "节点名称": {
            "recognition": {},  // 识别配置
            "action": {},       // 动作配置
            "next": [],         // 下一个节点列表
            "focus": {}         // 焦点配置（用于提示信息）
        }
    }
}
```

### 配置说明

`override` 用于覆盖默认节点的配置，支持以下字段：

- `recognition` - 覆盖识别配置（识别区域、识别类型、期望内容等）
- `action` - 覆盖动作配置（点击位置、滑动参数等）
- `next` - 覆盖下一个节点列表
- `focus` - 设置焦点提示信息（用于显示警告或说明）

### 配置示例

#### 示例 1：覆盖识别区域

```jsonc
{
    "override": {
        "FlagInActivityMain": {
            "recognition": {
                "param": {
                    "roi": [1029, 33, 96, 22],
                    "expected": "成就",
                    "only_rec": true
                }
            }
        }
    }
}
```

#### 示例 2：覆盖动作目标

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

#### 示例 3：覆盖下一个节点

```jsonc
{
    "override": {
        "JudgeDuringRe_release": {
            "next": ["ActivityMainChapter"]
        }
    }
}
```

#### 示例 4：设置焦点提示

```jsonc
{
    "override": {
        "focus": {
            "focus": {
                "Node.Action.Starting": "当前任务只适用旧版轶事派遣，请手动完成当期轶事"
            }
        }
    }
}
```

## 使用说明

这些数据主要用于：

1. **活动判断**：根据当前时间判断哪些活动正在进行
2. **版本识别**：识别当前游戏版本
3. **界面适配**：通过 override 配置适配不同活动的特殊界面
4. **流程定制**：为特定活动定制专门的执行流程
