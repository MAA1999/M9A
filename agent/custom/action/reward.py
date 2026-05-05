from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.pipeline import JOCR, JActionType, JClick, JRecognitionType
from utils import logger


@AgentServer.custom_action("RewardHandler")
class RewardHandler(CustomAction):
    """
    日历处理

    - 仅首次执行时，对固定区域做 OCR 并按垂直方向拼接输出
    - OCR 完成后执行原有 target 点击
    """

    _global_count: int = 0
    _ocr_roi: tuple[int, int, int, int] = (445, 205, 338, 99)
    _click_target: tuple[int, int, int, int] = (362, 279, 37, 39)

    @classmethod
    def _ocr_once(cls, context: Context) -> None:
        img = context.tasker.controller.cached_image

        reco_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=cls._ocr_roi, order_by="Vertical"),
            img,
        )

        if reco_detail and reco_detail.hit:
            text_items: list[str] = []
            for item in getattr(reco_detail, "filtered_results", []) or []:
                text = (getattr(item, "text", "") or "").strip()
                if not text:
                    continue
                text_items.append(text)
            # filtered_results 已按顺序返回，直接拼接即可。
            merged_text = "".join(text_items)
            logger.info(f"签到日历文本:\n{merged_text}")
        else:
            logger.info("未识别到签到日历文本")
        return

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if RewardHandler._global_count == 0:
            RewardHandler._global_count += 1
            RewardHandler._ocr_once(context)

        context.run_action_direct(
            JActionType.Click,
            JClick(target=RewardHandler._click_target),
        )

        return CustomAction.RunResult(success=True)
