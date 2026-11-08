"""均衡刷材料：寻找单个目标关卡的**总预算**检查（自定义识别）。

## 为什么是自定义识别而不是自定义动作

原版的扫描尾节点（`SwipeLeftForStageList` / `SwipeRightForStageList`）的 `next` 是
「滑动一次后回到扫描头」的调度链。加一个**没有 recognition** 的动作节点到 `next` 里，
它每次都会「命中」并打断原版的调度 —— 那会改坏原版行为。

所以预算检查做成**自定义识别**（与 `general.json` 的 `CheckStopping` 同一形状）：

- 未超预算 → 返回 `None`（不匹配）→ 框架继续按原版走 `next` 的下一个候选；
- 超预算 → 返回匹配 → 框架执行该节点 → 走 `StageLookupTimeout` 顺延。

## 为什么这是「总预算」而不是「两个尾节点各两分钟」

尾节点自己的 `timeout` 仍是原版的 2000ms（那只是「滑动尾节点没匹配到后继」的单次等待）。
本模块的预算从**本次选关开始**算起（`begin_stage_lookup`），覆盖前置导航、卷内扫描与
等待的全过程 —— 也就是「寻找这个关卡」这件事本身的耗时上限。

非均衡刷材料的流程里本识别直接返回 `None`，**原版行为完全不变**。
"""

from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from utils.logger import logger


def _planner() -> Any:
    """取顺延状态机。

    `agent.custom.*` 与 `custom.*` 是两张模块图（同一份源码、两个模块对象），
    这里不能直接 `from custom.action...` 顶层导入 —— 导入时机不保证，
    而且两张图会拿到**各自**的状态机实例。

    所以按**文件路径**在 `sys.modules` 里找到当前这张图的那份，
    保证识别与动作用的是同一个状态机。
    """
    import sys

    module = sys.modules.get("custom.action.balanced_fallback")
    if module is None:
        # 还没注册（自定义识别的 analyze 早于动作模块导入）→ 延迟到调用时再取
        from custom.action.balanced_fallback import planner as _p

        return _p()
    return module.planner()


@AgentServer.custom_recognition("StageLookupBudget")
class StageLookupBudget(CustomRecognition):
    """寻找单个目标关卡是否已超过总预算（两分钟）。

    仅在「均衡刷材料」的顺延状态机激活时才可能命中；其它流程一律不匹配。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:
        state = _planner()
        if not state.active:
            return None

        # 每次被问就意味着「又要滑动一次」—— 扫描链上这个节点每轮都会被问，
        # 所以这里的累加值就是**实际滑动次数**（用来判断是不是真的扫过了整章）。
        state.note_swipe()

        if not state.budget_exceeded():
            return None

        logger.warning(
            f"寻找关卡 {state.current_stage} 超过 {state.lookup_budget_ms // 1000} 秒预算，"
            f"判定为找不到（已滑动 {state.swipe_count} 次）"
        )
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 0, 0],
            detail={
                "node": "StageLookupBudget",
                "stage": state.current_stage,
                "swipes": state.swipe_count,
            },
        )
