import json
import time
from typing import Union, Optional, cast, Any

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType, OCRResult

from utils import logger


@AgentServer.custom_recognition("SOSSelectEncounterOptionFindSelected")
class SOSSelectEncounterOptionFindSelected(CustomRecognition):
    """
    局外演绎：无声综合征-途中偶遇选项识别已选中的选项
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        reco_detail = context.run_recognition(
            "SOSSelectEncounterOptionRec_Template", argv.image
        )
        if reco_detail and reco_detail.best_result:
            # 放大镜图标的 roi，扩大一点，方便后面颜色匹配
            Magnifier_rois = [
                [i.box[0] - 10, i.box[1] - 10, i.box[2] + 20, i.box[3] + 12]
                for i in reco_detail.filterd_results
            ]
        else:
            return CustomRecognition.AnalyzeResult(box=None, detail="")

        for roi in Magnifier_rois:
            # 对每个roi进行颜色匹配，查看选中状态
            selected_detail = context.run_recognition(
                "SOSSelectEncounterOption_HSV_Selected",
                argv.image,
                {
                    "SOSSelectEncounterOption_HSV_Selected": {
                        "recognition": {"param": {"roi": roi}}
                    }
                },
            )

            if selected_detail and selected_detail.best_result:
                return CustomRecognition.AnalyzeResult(
                    box=roi, detail=str({"roi": roi})
                )

        return CustomRecognition.AnalyzeResult(box=None, detail="")


@AgentServer.custom_recognition("SOSSelectEncounterOptionList")
class SOSSelectEncounterOptionList(CustomRecognition):
    """
    局外演绎：无声综合征-途中偶遇选项内容识别
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        reco_detail = context.run_recognition(
            "SOSSelectEncounterOptionRec_Template", argv.image
        )
        if reco_detail and reco_detail.best_result:
            # 放大镜图标的 roi，扩大一点
            Magnifier_rois = [
                [i.box[0] - 10, i.box[1] - 10, i.box[2] + 20, i.box[3] + 12]
                for i in reco_detail.filterd_results
            ]
        else:
            return CustomRecognition.AnalyzeResult(box=None, detail="")

        options: list[dict[str, Any]] = []

        for roi in Magnifier_rois:
            # 先进行颜色匹配，判断选项状态
            unselected_detail = context.run_recognition(
                "SOSSelectEncounterOption_HSV_Unselected",
                argv.image,
                {
                    "SOSSelectEncounterOption_HSV_Unselected": {
                        "recognition": {"param": {"roi": roi}}
                    }
                },
            )

            status = None
            if unselected_detail and unselected_detail.best_result:
                status = 0
            else:
                # 未选中检测失败，再检测是否已选中
                selected_detail = context.run_recognition(
                    "SOSSelectEncounterOption_HSV_Selected",
                    argv.image,
                    {
                        "SOSSelectEncounterOption_HSV_Selected": {
                            "recognition": {"param": {"roi": roi}}
                        }
                    },
                )
                if selected_detail and selected_detail.best_result:
                    status = 1

            # 匹配到有效状态后,执行 OCR 识别选项内容
            if status is not None:
                roi = [roi[0] + 40, roi[1], roi[2] + 150, roi[3]]
                ocr_detail = context.run_recognition(
                    "SOSSelectEncounterOptionRec_OCR",
                    argv.image,
                    {
                        "SOSSelectEncounterOptionRec_OCR": {
                            "recognition": {"param": {"roi": roi}}
                        }
                    },
                )

                content = ""
                if ocr_detail and ocr_detail.best_result:
                    ocr_result = cast(OCRResult, ocr_detail.best_result)
                    content = ocr_result.text

                    options.append({"roi": roi, "status": status, "content": content})
                    logger.debug(
                        f"识别到选项 - 状态: {status}, 内容: {content}, ROI: {roi}"
                    )

        return CustomRecognition.AnalyzeResult(
            box=options[0]["roi"] if options else [0, 0, 0, 0],
            detail=json.dumps({"options": options}, ensure_ascii=False),
        )


@AgentServer.custom_recognition("SOSSelectNode")
class SOSSelectNode(CustomRecognition):
    """
    局外演绎：无声综合征-节点选择
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:

        # 如果目标在禁止区域范围内，向右滑动
        forbidden_roi = [0, 140, 348, 284]

        reco_detail = context.run_recognition("SOSEntrustrRec", argv.image)
        if reco_detail and reco_detail.best_result:
            reco_detail = context.run_recognition("SOSSelectNode_rec", argv.image)
            if reco_detail and reco_detail.best_result:
                # 获取识别到的节点位置
                node_box = reco_detail.best_result.box

                # 判断是否在禁止区域内
                x, y, w, h = node_box
                fx, fy, fw, fh = forbidden_roi

                # 检查节点是否与禁止区域相交（只要相交就算）
                if x < fx + fw and x + w > fx and y < fy + fh and y + h > fy:
                    # 在禁止区域内，返回滑动指令
                    context.run_task(
                        "Click",
                        {
                            "Click": {
                                "action": {
                                    "type": "Swipe",
                                    "param": {
                                        "begin": [402, 564, 34, 36],
                                        "end": [902, 569, 34, 36],
                                        "duration": 500,
                                    },
                                }
                            }
                        },
                    )
                    return CustomRecognition.AnalyzeResult(
                        box=None,
                        detail=json.dumps(
                            {
                                "action": "swipe_right",
                                "reason": "node_in_forbidden_area",
                                "node_box": node_box,
                            },
                            ensure_ascii=False,
                        ),
                    )
                else:
                    # 不在禁止区域内，返回节点位置供点击
                    return CustomRecognition.AnalyzeResult(
                        box=node_box, detail=str(reco_detail.raw_detail)
                    )
        else:
            reco_detail = context.run_recognition("SOSSelectNode_rec", argv.image)
            if reco_detail and reco_detail.best_result:
                # 获取识别到的节点位置
                node_box = reco_detail.best_result.box
                # 不在禁止区域内，返回节点位置供点击
                return CustomRecognition.AnalyzeResult(
                    box=node_box, detail=str(reco_detail.raw_detail)
                )
            return CustomRecognition.AnalyzeResult(box=None, detail="")
