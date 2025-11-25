---
order: 1
icon: ri:game-fill
---

# 局外演绎：无声综合征 肉鸽辅助协议

> [!TIP]
>
> 请注意 JSON 文件是不支持注释的，文本中的注释仅用于演示，请勿直接复制使用

## 资源存放位置

`assets/resource/data/sos` 下存放着相关资源

## 字段说明

### 顶层结构

```jsonc
{
    "types": [],           // 节点类型数组，包含所有可能的节点类型
    "节点类型名称": {}     // 每个节点类型的具体配置
}
```

### 节点类型列表

`types` 字段定义了所有支持的节点类型：

- `已完成节点` - 已完成的节点
- `必经之路` - 主线故事事件
- `途中偶遇` - 支线事件
- `藏宝地` - 获得宝藏
- `休憩处` - 恢复与休息
- `购物契机` - 花费金雀子儿购买商品
- `巧匠之手` - 升级和置换造物
- `遭遇` - 简单的战斗
- `途中余兴` - 具备特殊规则的战斗
- `冲突` - 较为困难的精英战斗
- `险象环生` - 难度逐步递增的连环战斗挑战
- `恶战` - 极其危险的首领战斗
- `对话` - 对话事件节点

### 节点配置结构

每个节点类型包含以下字段：

```jsonc
{
    "event_name_roi": [x, y, w, h],  // 事件名称识别区域，null 表示不需要识别事件名
    "actions": [],                    // 默认动作序列（用于无事件名或通用处理）
    "events": {},                     // 特定事件的动作配置（可选）
    "interrupts": []                  // 中断处理节点列表（可选）
}
```

#### 节点类型分类

**无事件名节点**（直接执行 `actions`）：

- `购物契机`
- `遭遇`
- `途中余兴`
- `冲突`
- `恶战`
- `巧匠之手`

**有事件名节点**（需识别具体事件，执行对应 `events` 中的配置）：

- `必经之路`
- `休憩处`
- `藏宝地`
- `险象环生`

### 动作类型 (Action Types)

#### 1. RunNode - 运行节点

运行预定义的流程节点

```jsonc
{
    "type": "RunNode",
    "name": "节点名称"
}
```

常用节点：

- `SOSTeamSelect` - 队伍选择
- `SOSCombat` - 战斗流程
- `SOSContinue` - 继续/确认按钮
- `SOSEventEnd` - 事件结束
- `BackButton` - 返回按钮
- `SOSConfirm` - 确认按钮

#### 2. SelectOption - 选项选择

选择对话或事件选项（垂直排列）

```jsonc
{
    "type": "SelectOption",
    "method": "OCR" | "HSV",          // 识别方法：OCR文字识别 或 HSV颜色识别
    "expected": ["选项1", "选项2"],  // OCR方法：期望的文字内容（必需）
    "order_by": "Vertical",           // 排序方式：Vertical(垂直) 或 Horizontal(水平)，默认 Vertical（可选）
    "index": 0                        // 选项索引，默认 0 表示第一个，-1 表示最后一个（可选）
}
```

**OCR 方法**：

- 通过识别文字内容来选择选项
- `expected` 可以是字符串或字符串数组，按顺序优先匹配
- 会为每个 expected 值创建独立的识别节点进行匹配

**HSV 方法**：

- 通过颜色识别来选择选项
- 使用 `index` 参数指定选择第几个选项

#### 3. SelectEncounterOption - 途中偶遇选项选择

专用于"途中偶遇"场景的选项选择（水平排列）

```jsonc
{
    "type": "SelectEncounterOption",
    "method": "OCR" | "HSV",          // 识别方法：OCR文字识别 或 HSV颜色识别
    "expected": "选项文字",           // OCR方法：期望的文字内容
    "order_by": "Vertical",           // 模板识别排序方式：Vertical(垂直) 或 Horizontal(水平)，默认 Vertical
    "index": 0                        // HSV方法：选项索引，默认 0 表示第一个，-1 表示最后一个
}
```

**OCR 方法**：

- 通过识别文字内容来选择选项
- `expected` 为字符串，指定期望识别的文字内容
- `order_by` 用于放大镜图标模板识别的排序方式，默认 `Vertical`

**HSV 方法**：

- 通过颜色识别来选择选项
- 使用 `index` 参数指定选择第几个选项
- `order_by` 用于放大镜图标模板识别的排序方式，默认 `Vertical`

### 中断处理节点 (Interrupts)

在执行动作过程中可能触发的中断处理节点：

- `SOSSelectHarmonic` - 选择和弦
- `SOSHarmonicObtained` - 获得和弦
- `SOSSelectArtefact` - 选择遗器
- `SOSArtefactsObtained` - 获得遗器
- `SOSLoseArtefact` - 失去遗器
- `SOSSelectResonator` - 选择共鸣者
- `SOSResonatorObtained` - 获得共鸣者
- `SOSStatsUpButton` - 属性提升按钮
- `SOSStatsUp` - 属性提升
- `SOSNextMessage` - 下一条消息
- `SOSContinue` - 继续按钮
- `SOSDice` - 骰子事件

### 事件配置示例

#### 简单战斗节点示例

```jsonc
"冲突": {
    "event_name_roi": null,  // 不需要识别事件名
    "actions": [
        {
            "type": "RunNode",
            "name": "SOSTeamSelect"  // 1. 选择队伍
        },
        {
            "type": "RunNode",
            "name": "SOSCombat"  // 2. 进入战斗
        }
    ]
}
```

#### 复杂事件节点示例

```jsonc
"休憩处": {
    "event_name_roi": [858, 72, 132, 33],  // 识别事件名称的区域
    "events": {
        "俱乐部来客": {  // 特定事件名称
            "actions": [
                {
                    "type": "RunNode",
                    "name": "SOSContinue"  // 1. 点击继续
                },
                {
                    "type": "SelectOption",
                    "method": "HSV",
                    "index": -1  // 2. 选择最后一个选项（HSV识别）
                },
                {
                    "type": "RunNode",
                    "name": "SOSEventEnd"  // 3. 结束事件
                }
            ],
            "interrupts": [  // 可能触发的中断
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

#### 带选项识别的事件示例

```jsonc
"必经之路": {
    "event_name_roi": [858, 72, 132, 33],
    "events": {
        "旅途的开始": {
            "actions": [
                {
                    "type": "RunNode",
                    "name": "SOSContinue"
                },
                {
                    "type": "SelectOption",
                    "method": "OCR",
                    "expected": [
                        "奥秘",    // 优先选择这些属性
                        "力量",
                        "激情",
                        "反应",
                        "感知"
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

## 配置说明

### ROI 区域说明

`event_name_roi` 定义了事件名称的识别区域，格式为 `[x, y, width, height]`：

- `x`: 左上角 X 坐标
- `y`: 左上角 Y 坐标  
- `width`: 宽度
- `height`: 高度
- `null`: 表示该节点不需要识别具体事件名称

### 执行流程

#### 1. 节点选择阶段（SOSSelectNode）

1. 通过神经网络识别节点类型（从 `types` 数组中获取）
2. 点击节点并等待界面响应（最多重试 5 次）
3. 如果配置了 `event_name_roi`，则在指定区域识别事件名称
4. 记录当前节点类型和事件名称

#### 2. 节点处理阶段（SOSNodeProcess）

1. 根据节点类型判断是否需要识别事件名：
   - **无事件名节点**：直接使用 `actions` 中的动作序列
   - **有事件名节点**：从 `events` 中查找对应事件的配置
2. 按顺序执行 `actions` 中的每个动作
3. 每个动作执行前后都会进行中断检测

#### 3. 动作执行机制

每个动作执行时的流程：

1. 尝试执行主动作（最多重试 10 次）
2. 如果执行失败，遍历 `interrupts` 列表进行中断检测
3. 检测到中断事件时立即处理，然后继续主动作
4. 所有重试失败后返回失败

#### 4. 中断检测机制

- 中断检测在每次主动作执行失败时触发
- 按照 `interrupts` 数组顺序依次识别
- 识别到中断事件后立即执行对应任务
- 中断处理完成后继续执行主动作

### 注意事项

- 动作按照 `actions` 数组顺序依次执行
- 每个动作最多重试 10 次，超时则判定为失败
- 中断检测在主动作执行失败时触发，而非异步监听
- OCR 选项识别会按照 `expected` 数组顺序优先匹配，匹配到第一个即停止
- HSV 方法使用 `index` 参数时，-1 表示选择最后一个选项，0 表示第一个
- 节点点击操作会等待界面冻结检测（500ms 冻结时间，3000ms 超时）
- 如果事件名识别失败，整个节点处理会失败并停止任务
- 未适配的事件会记录错误日志并停止任务执行

### 开发建议

- 新增事件时，先在对应节点类型的 `events` 中添加事件配置
- 中断节点应该是可独立识别和执行的任务
- 使用 OCR 选项识别时，`expected` 应包含所有可能的正确选项文本
- 复杂事件流程建议拆分为多个小动作，便于调试和维护
