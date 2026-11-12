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


@AgentServer.custom_recognition("StageLookupFarLeft")
class StageLookupFarLeft(CustomRecognition):
    """均衡刷材料：确认扫描已经滑到**本章第一关**，并记下这个事实。

    ## 为什么需要它

    原版判「关卡列表里没有目标关卡」靠的是扫描尾节点的 `timeout`（2 秒没匹配到
    后继就失败）。但 MaaFW 的 `on_error` 同时覆盖 **`next` 超时**和**动作失败** ——
    于是 Swipe 动作偶发失败、截图偶发失败也会走进 `StageLookupTimeout`，
    被误判成「这个关卡没解锁」，把明明能打的关卡永久记成不可用。

    ## 判定依据

    游戏里点开一个大章后，列表从**已解锁的最后一关**开始；M9A 的滑动一直往第一关走。
    原版的 `TheFarLeftOfStageList` 就是这件事的判定（OCR 关卡编号行 `^01`）。
    所以：**只要滑到过 01，就说明整章确实扫完了**；此时仍没找到目标关卡，
    才能确认它真的没解锁。

    本识别做的是同一判定（复用同一个 ROI 与 `^01` 规则），命中时置位
    `state.reached_far_left`，然后照原版一样回 `SwipeRightForStageList`。

    ## 默认禁用

    它是 Custom 识别，启用后每轮扫描都要多一次 agent 回调。所以
    `balanced_fallback.json` 里 `enabled: false`，只有均衡刷材料任务在入口
    override 成 `enabled: true` —— 其它作战任务的扫描链完全不受影响。
    """

    # 与 combat.json 的 TheFarLeftOfStageList 保持同一 ROI 与规则：
    # 只在关卡编号行取 `^01`（`^` 锚定，避免 "201..." 这类粘连误判，见 issue #990）。
    _ROI = (0, 539, 1280, 46)

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | RectType | None:
        state = _planner()
        if not state.active:
            # 非均衡任务：不匹配，原版 TheFarLeftOfStageList 照常接管
            return None

        box = self._find_first_stage(context, argv)
        if box is None:
            return None

        state.note_reached_far_left()
        logger.debug(f"扫描已到本章第一关（关卡 {state.current_stage} 未找到）")
        return CustomRecognition.AnalyzeResult(box=box, detail={"node": "StageLookupFarLeft"})

    def _find_first_stage(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> RectType | None:
        """在关卡编号行找 `^01`；找不到返回 None。

        用 `only_rec=True` 只要一行文本（与 `RecordID` 同一写法），再用 `ocr_text`
        取内容 —— `run_recognition_direct` 返回的是**单个** detail，不是列表。
        """
        from maa.pipeline import JOCR, JRecognitionType
        from utils.maa_types import ocr_text

        try:
            detail = context.run_recognition_direct(
                JRecognitionType.OCR,
                JOCR(roi=self._ROI, only_rec=True),
                argv.image,
            )
        except Exception as exc:  # noqa: BLE001 - 识别失败只表示「没到最左」，不该中断扫描
            logger.debug(f"StageLookupFarLeft 识别失败: {exc}")
            return None

        text = ocr_text(detail).strip()
        # 与原版 TheFarLeftOfStageList 的 `expected: "^01"` 同一判定
        if not text.startswith("01"):
            return None
        box = getattr(detail, "box", None)
        if not box:
            return None
        return (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
