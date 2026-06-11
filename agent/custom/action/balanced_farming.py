import json
import re
import time

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import best_box, ocr_text


@AgentServer.custom_action("BalancedFarmingAnalyze")
class BalancedFarmingAnalyze(CustomAction):
    _DATA_PATH = "resource/data/combat/balanced_farming.json"
    # 仓库列表最多翻页次数，防止滑动判断异常时死循环
    _MAX_SCROLL_PAGES = 5
    # 数量文字相对图标 box 的偏移：(dx, dy, dw, dh)，dy 基于图标底边；
    # 横向收窄到图标内部，避免把格子两侧装饰认成数字
    _COUNT_ROI_OFFSET = (8, 0, -16, 36)

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        try:
            with open(self._DATA_PATH, encoding="utf-8") as f:
                materials: dict[str, dict] = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"读取材料映射表失败: {self._DATA_PATH}, {e}")
            return CustomAction.RunResult(success=False)

        # 每页都对全部材料做匹配，收集多次读数；
        # 图标艺术边缘偶尔使 OCR 多认一位（膨胀型误读），取最小读数纠正
        readings: dict[str, list[int]] = {item_id: [] for item_id in materials}
        # 图标已找到但数量识别失败的材料，不能按 0 计，需排除出候选
        unreadable: set[str] = set()

        for page in range(self._MAX_SCROLL_PAGES):
            img = context.tasker.controller.post_screencap().wait().get()
            for item_id in materials:
                found, count = self._recognize_item(context, img, item_id)
                if not found:
                    continue
                if count is None:
                    unreadable.add(item_id)
                else:
                    readings[item_id].append(count)
            pending = [item_id for item_id in materials if not readings[item_id]]
            if not pending:
                break
            # 还有材料没读到数量，向下翻一屏继续找
            logger.debug(f"第 {page + 1} 屏未读到: {pending}，向下滚动")
            context.tasker.controller.post_swipe(640, 560, 640, 230, 1000).wait()
            time.sleep(1.5)

        counts: dict[str, int] = {}
        for item_id, values in readings.items():
            if values:
                counts[item_id] = min(values)
                if len(set(values)) > 1:
                    logger.warning(
                        f"材料 {materials[item_id]['name']}({item_id}) "
                        f"多次读数不一致 {values}，取最小值 {min(values)}"
                    )
            elif item_id in unreadable:
                logger.warning(
                    f"材料 {materials[item_id]['name']}({item_id}) "
                    "数量识别失败，本次不参与均衡"
                )
            else:
                logger.warning(
                    f"仓库中未找到材料 {materials[item_id]['name']}({item_id})，按 0 计"
                )
                counts[item_id] = 0

        if not counts:
            logger.error("没有任何材料识别成功，终止任务")
            return CustomAction.RunResult(success=False)

        summary = ", ".join(
            f"{materials[item_id]['name']}x{counts[item_id]}"
            for item_id in sorted(counts)
        )
        logger.info(f"仓库材料数量: {summary}")

        target_id = min(sorted(counts), key=lambda item_id: counts[item_id])
        target = materials[target_id]
        logger.info(
            f"数量最少的材料: {target['name']}({counts[target_id]})，"
            f"目标关卡: {target['stage']} {target['level']}"
        )

        context.override_pipeline(
            {
                "SelectCombatStage": {
                    "action": {
                        "param": {
                            "custom_action_param": {"stage": target["stage"]}
                        }
                    },
                    "attach": {"level": target["level"]},
                }
            }
        )

        return CustomAction.RunResult(success=True)

    def _recognize_item(
        self, context: Context, img, item_id: str
    ) -> tuple[bool, int | None]:
        """匹配单个材料图标并识别其下方数量。

        Returns:
            (是否找到图标, 数量)，图标找到但数量识别失败时数量为 None。
        """
        reco_detail = context.run_recognition(
            "BF_ItemIcon",
            img,
            {
                "BF_ItemIcon": {
                    "recognition": {
                        "param": {"template": f"Warehouse/Item-{item_id}.png"}
                    }
                }
            },
        )
        box = best_box(reco_detail)
        if box is None:
            return False, None

        x, y, w, h = box
        dx, dy, dw, dh = self._COUNT_ROI_OFFSET
        if y + h + dy + dh > 718:
            # 数量条被屏幕底部裁切，本屏不读，等滚动后完整出现再读
            return False, None
        count_roi = [x + dx, y + h + dy, w + dw, dh]
        count_detail = context.run_recognition(
            "BF_ItemCount",
            img,
            {"BF_ItemCount": {"recognition": {"param": {"roi": count_roi}}}},
        )
        text = ocr_text(count_detail)
        # 取最长数字组：真实数量位数多于边缘噪声误认的零散数字
        groups = re.findall(r"\d+", text.replace(",", ""))
        logger.debug(f"{item_id} box={list(box)} text='{text}'")
        if not groups:
            logger.warning(f"材料 {item_id} 图标已找到但数量识别失败: '{text}'")
            return True, None
        return True, int(max(groups, key=len))
