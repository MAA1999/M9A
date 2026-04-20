import os
import json
from datetime import datetime

from PIL import Image
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger
from custom.reco import Count


@AgentServer.custom_action("DisableNode")
class DisableNode(CustomAction):
    """
    将特定 node 设置为 disable 状态 。

    参数格式:
    {
        "node_name": "结点名称"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        node_name = json.loads(argv.custom_action_param)["node_name"]

        context.override_pipeline({f"{node_name}": {"enabled": False}})

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("NodeOverride")
class NodeOverride(CustomAction):
    """
    在 node 中执行 pipeline_override 。

    参数格式:
    {
        "node_name": {"被覆盖参数": "覆盖值",...},
        "node_name1": {"被覆盖参数": "覆盖值",...}
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        ppover = json.loads(argv.custom_action_param)

        if not ppover:
            logger.warning("No ppover")
            return CustomAction.RunResult(success=True)

        logger.debug(f"NodeOverride: {ppover}")
        context.override_pipeline(ppover)

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ResetCount")
class ResetCount(CustomAction):
    """
    重置计数器。

    参数格式:
    {
        "node_name": String # 目标计数器节点名称，不存在时重置全部节点
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if not argv.custom_action_param:
            Count.reset_count()
            return CustomAction.RunResult(success=True)

        param = json.loads(argv.custom_action_param)
        if not param:
            Count.reset_count()
            return CustomAction.RunResult(success=True)

        node_name = param.get("node_name", None)
        Count.reset_count(node_name)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SubTask")
class SubTask(CustomAction):
    """
    按顺序执行子任务。

    参数格式:
    {
        "sub": ["任务名称1", "任务名称2"],
        "continue": false, # 任一子任务失败后是否继续执行后续子任务
        "strict": true # 任一子任务失败时，当前 action 是否视为失败
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if not argv.custom_action_param:
            logger.error("SubTask requires non-empty custom_action_param")
            return CustomAction.RunResult(success=False)

        try:
            param = json.loads(argv.custom_action_param)
        except json.JSONDecodeError:
            logger.exception("SubTask failed to parse custom_action_param")
            return CustomAction.RunResult(success=False)

        sub = param.get("sub", None)
        if not isinstance(sub, list) or not sub:
            logger.error("SubTask requires non-empty custom_action_param.sub")
            return CustomAction.RunResult(success=False)

        continue_on_failure = bool(param.get("continue", False))
        strict = bool(param.get("strict", True))
        has_sub_failure = False

        for index, task_name in enumerate(sub):
            if not isinstance(task_name, str) or not task_name:
                logger.error(
                    f"SubTask received invalid task name in custom_action_param.sub[{index}]: {task_name!r}"
                )
                has_sub_failure = True
                if not continue_on_failure:
                    break
                continue

            task_detail = context.run_task(task_name)
            if task_detail and task_detail.status._status.name == "failed":
                logger.error(f"子任务运行失败: index={index}, task={task_name}")
                has_sub_failure = True
                if not continue_on_failure:
                    break

        return CustomAction.RunResult(success=not (has_sub_failure and strict))
