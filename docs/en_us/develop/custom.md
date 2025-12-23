---
order: 5
icon: material-symbols:inbox-customize-outline-rounded
---
# Custom Module Writing Guide

## Development Approach

M9A is based on **MaaFramework v5.1+** and adopts the [JSON + Custom Logic Extension](https://maafw.xyz/docs/1.1-QuickStart#approach-2-json-custom-logic-extension-recommended) approach, registering custom modules through `AgentServer`.

## Custom Module Types

M9A's custom modules are divided into three categories:

### 1. Custom Action

Location: `agent/custom/action/`

Purpose: Implement complex game operation logic, such as recognition result processing, multi-step operations, data analysis, etc.

**Basic Structure**:

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
        # Implement your logic
        return CustomAction.RunResult(success=True)
```

**Project Examples**:

- [`Screenshot`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - Save screenshot after task timeout
- [`DisableNode`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - Set specific node to disabled state
- [`NodeOverride`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - Dynamically override Pipeline configuration in node
- [`ResetCount`](https://github.com/MAA1999/M9A/blob/main/agent/custom/action/general.py) - Reset counter state

### 2. Custom Recognition

Location: `agent/custom/reco/`

Purpose: Implement complex recognition logic that cannot be accomplished with Pipeline JSON alone, such as dynamic OCR, color matching, multi-step recognition, etc.

**Basic Structure**:

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
        # Implement recognition logic
        return CustomRecognition.AnalyzeResult(box=[x, y, w, h], detail={})
```

**Project Examples**:

- [`MultiRecognition`](https://github.com/MAA1999/M9A/blob/main/agent/custom/reco/general.py) - Multi-algorithm combined recognition, supports AND/OR/custom logic
- [`Count`](https://github.com/MAA1999/M9A/blob/main/agent/custom/reco/general.py) - Recognition counter, stops after specified number of executions
- [`CheckStopping`](https://github.com/MAA1999/M9A/blob/main/agent/custom/reco/general.py) - Check if task is about to stop

### 3. Sink (Event Listener)

Location: `agent/custom/sink/`

Purpose: Listen to MaaFramework runtime events for logging, debug output, performance monitoring, etc.

**Basic Structure**:

```python
from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink

@AgentServer.context_sink()
class MyContextSink(ContextEventSink):
    def on_raw_notification(self, context: Context, msg: str, details: dict):
        # Handle event notifications
        pass
```

**Project Examples**:

- [Sink Module](https://github.com/MAA1999/M9A/blob/main/agent/custom/sink/__init__.py) - Implements Resource, Controller, Tasker, Context event listeners
- [Logger Module](https://github.com/MAA1999/M9A/blob/main/agent/custom/sink/logger.py) - Structured logging system(Deprecated)

## Common APIs

### Context Common Methods

```python
# Execute recognition
reco_detail = context.run_recognition("NodeName", image)

# Execute task
context.run_task("NodeName")

# Override pipeline configuration
context.override_pipeline({"NodeName": {"next": ["NewNode"]}})

# Override image
context.override_image("image_name", image_array)

# Get screenshot
img = context.tasker.controller.post_screencap().wait().get()
```

### Recognition Result Processing

```python
from maa.define import OCRResult, TemplateMatchResult

if reco_detail and reco_detail.hit:
    # OCR result
    ocr_result = reco_detail.best_result
    text = ocr_result.text
    box = reco_detail.box  # [x, y, w, h]
    
    # All recognition results
    all_results = reco_detail.all_results
```

## Development Resources

- **Getting Started**: [MaaFramework Quick Start](https://maafw.xyz/docs/1.1-QuickStart)
- **Integration API**: [Integration Interface](https://maafw.xyz/docs/2.2-IntegrationAPI)
- **Python Binding Source**: [maa/source/binding/Python](https://github.com/MaaXYZ/MaaFramework/tree/main/source/binding/Python/maa)
- **Project Examples**: Browse existing implementations in `agent/custom/`

:::tip Learning Recommendations

1. Read existing custom implementations in the project to understand common patterns
2. Refer to MaaFramework official documentation to understand core concepts
3. Study Python Binding source code for deeper API understanding

:::
