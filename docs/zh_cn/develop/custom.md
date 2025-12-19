---
order: 5
icon: material-symbols:inbox-customize-outline-rounded
---
# Custom 编写指南

## 开发方式

M9A 基于 **MaaFramework v5.1+**，采用 [JSON + 自定义逻辑扩展](https://maafw.xyz/docs/1.1-QuickStart#approach-2-json-custom-logic-extension-recommended) 方式开发，通过 `AgentServer` 注册自定义模块。

## Custom 模块类型

M9A 的 custom 模块分为三类：

### 1. Custom Action（自定义动作）

位置：`agent/custom/action/`

用途：实现复杂的游戏操作逻辑，如识别结果处理、多步骤操作、数据分析等。

**基本结构**：

```python
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

@AgentServer.custom_action("YourActionName")
class YourAction(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        # 实现你的逻辑
        return CustomAction.RunResult(success=True)
```

**项目实例**：

- [`Screenshot`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - 任务超时后截图保存
- [`DisableNode`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - 将特定节点设置为禁用状态
- [`NodeOverride`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - 在节点中动态覆盖 Pipeline 配置
- [`ResetCount`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - 重置计数器状态

### 2. Custom Recognition（自定义识别）

位置：`agent/custom/reco/`

用途：实现 Pipeline JSON 无法完成的复杂识别逻辑，如动态 OCR、颜色匹配、多步骤识别等。

**基本结构**：

```python
from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from typing import Union, Optional
from maa.define import RectType

@AgentServer.custom_recognition("YourRecognitionName")
class YourRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        # 实现识别逻辑
        return CustomRecognition.AnalyzeResult(box=[x, y, w, h], detail={})
```

**项目实例**：

- [`MultiRecognition`](https://github.com/MAA1999/M9A/blob/main/agent/custom/reco/general.py) - 多算法组合识别，支持 AND/OR/自定义逻辑
- [`Count`](https://github.com/MAA1999/M9A/blob/main/agent/custom/reco/general.py) - 识别计数器，执行指定次数后停止
- [`CheckStopping`](https://github.com/MAA1999/M9A/blob/main/agent/custom/reco/general.py) - 检查任务是否即将停止

### 3. Sink（事件监听器）

位置：`agent/custom/sink/`

用途：监听 MaaFramework 的运行事件，实现日志记录、调试输出、性能监控等。

**基本结构**：

```python
from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink

@AgentServer.context_sink()
class MyContextSink(ContextEventSink):
    def on_raw_notification(self, context: Context, msg: str, details: dict):
        # 处理事件通知
        pass
```

**项目实例**：

- [Sink 模块](https://github.com/MAA1999/M9A/blob/main/agent/custom/sink/__init__.py) - 实现了 Resource、Controller、Tasker、Context 四类事件监听
- [Logger 模块](https://github.com/MAA1999/M9A/blob/main/agent/custom/sink/logger.py) - 结构化日志系统（废弃）

## 常用 API

### Context 常用方法

```python
# 执行识别
reco_detail = context.run_recognition("NodeName", image)

# 执行任务
context.run_task("NodeName")

# 覆盖 Pipeline 配置
context.override_pipeline({"NodeName": {"next": ["NewNode"]}})

# 覆盖图片
context.override_image("image_name", image_array)

# 获取截图
img = context.tasker.controller.post_screencap().wait().get()
```

### 识别结果处理

```python
from maa.define import OCRResult, TemplateMatchResult

if reco_detail and reco_detail.hit:
    # OCR 结果
    ocr_result = reco_detail.best_result
    text = ocr_result.text
    box = reco_detail.box  # [x, y, w, h]
    
    # 所有识别结果
    all_results = reco_detail.all_results
```

## 开发资源

- **集成接口文档**：[Integration Interface](https://maafw.xyz/docs/2.2-IntegratedInterfaceOverview)
- **Python Binding 源码**：[maa/source/binding/Python](https://github.com/MaaXYZ/MaaFramework/tree/main/source/binding/Python/maa)
- **项目实例**：直接查看 `agent/custom/` 下的现有实现

:::tip 学习建议

1. 先阅读项目中现有的 custom 实现，了解常用模式
2. 参考 MaaFramework 官方文档理解核心概念
3. 结合 Python Binding 源码深入理解 API 行为

:::
