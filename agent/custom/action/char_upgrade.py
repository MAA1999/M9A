import json
import math
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JActionType, JClick


@AgentServer.custom_action("CUB_StartAllIn")
class CUBStartAllIn(CustomAction):
    """启动复现战斗。

    前置条件：CompareNumbers 已识别出材料数量（first/second）。
    从 argv.reco_detail 读取 first/second，计算 target_count，
    然后导航到关卡并启动 AllIn。

    参数格式：
    {
        "drop_per_run": 2  // 每次战斗掉落数量（可选，默认 2）
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        # 1. 从 recognition detail 读取材料数量
        detail: dict[str, Any] | None = None
        try:
            detail = argv.reco_detail.raw_detail.get("best", {}).get("detail")
        except Exception:
            pass

        if not detail or "first" not in detail or "second" not in detail:
            return False

        first = detail["first"]
        second = detail["second"]

        # 2. 计算需要打几次
        params: dict[str, Any] = {}
        if argv.custom_action_param and argv.custom_action_param != "null":
            params = json.loads(argv.custom_action_param)
        drop_per_run = params.get("drop_per_run", 2)

        needed = second - first
        target_count = math.ceil(needed / drop_per_run)
        if target_count <= 0:
            return True  # 材料已够，不需要打
        context.run_action_direct(JActionType.Click, JClick(), argv.box)

        # 3. 判断是否为属性材料
        is_attribute_material = context.run_task("CUB_IsAttributeMaterial")

        if not is_attribute_material or not is_attribute_material.status.succeeded:
            context.log("识别失败：当前版本暂不支持刷取非属性突破材料，请手动刷取")
            return False

        # 4. 启动复现战斗
        context.run_task(
            "ReadyForAction",
            {
                "AllIn": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "target_count": target_count,
                            }
                        }
                    }
                },
                "TargetCountVictory": {
                    "action": {"type": "DoNothing"},
                    "next": [
                        "CUB_IsEnoughMaterial",
                        "TargetCountVictoryClick",
                    ],
                },
                "TargetCountVictoryClick": {
                    "recognition": {
                        "type": "OCR",
                        "param": {
                            "roi": [678, 10, 473, 240],
                            "expected": ["战斗", "胜利"],
                        },
                    },
                    "action": {"type": "Click"},
                    "next": [
                        "TargetCountWaitReplay",
                        "[JumpBack]CombatEntering",
                        "TargetCountVictoryClick",
                    ],
                },
                "EatCandyStart": {"attach": {"valid_period": "infinite"}},
            },
        )
        return True
