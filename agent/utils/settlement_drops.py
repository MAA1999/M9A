"""结算页掉落行读取（库存保持的自读兜底）。

常量与流程对齐 drop_core 的 `run_drop_recognition`，便于两条路径结果一致：

- 在 `DropRegionRec` 的 roi 内用 `Items_processed/Item-<id>.png` 模板匹配图标；
- 数字区域固定为 `[box.x + 22, 613, box.w - 44, 17]`（720p 基线，已实机核对）；
- 读数字前先做 `filter_digit_colors`：只留近灰白像素，抹掉彩色图标，OCR 更稳；
- 掉落行会横向滚动，最多滑动 3 次；同一场战斗**取首次读到的数量**，与 drop_core 的语义一致。

命中失败按「本局没有该材料」处理：少计会导致多刷一点，方向安全。
"""

from __future__ import annotations

import re
import time

import numpy as np
from maa.context import Context
from utils import logger
from utils.maa_types import best_box, ocr_text

DROP_REGION_NODE = "DropRegionRec"
DROP_COUNT_NODE = "DropCountRec"
COUNT_ROI_TOP = 613
COUNT_ROI_HEIGHT = 17
COUNT_ROI_DX = 22
COUNT_ROI_DW = -44
MAX_SWIPES = 3
SWIPE_FROM = (1155, 572)
SWIPE_TO = (921, 571)
SWIPE_DURATION = 500
SWIPE_SETTLE_SECONDS = 0.3


def filter_digit_colors(img: np.ndarray) -> np.ndarray:
    """近灰白像素留黑、其余抹白，得到只含数字的二值图。"""
    max_channel = np.max(img, axis=2)
    min_channel = np.min(img, axis=2)
    gray_mask = (max_channel - min_channel) < 50
    brightness = np.mean(img, axis=2)
    brightness_mask = (brightness >= 100) & (brightness <= 240)
    mask = gray_mask & brightness_mask
    result = np.ones_like(img) * 255
    result[mask] = 0
    return result


def count_roi(box: list[int]) -> list[int]:
    """由图标 box 推数量文字区域。

    图标模板比 `-COUNT_ROI_DW` 窄时宽度会算成非正数；夹到 0 让 OCR 明确读空
    （按「本局没有该材料」处理，少计只会多刷一点，方向安全）。
    """
    x, _, w, _ = box
    return [x + COUNT_ROI_DX, COUNT_ROI_TOP, max(0, w + COUNT_ROI_DW), COUNT_ROI_HEIGHT]


def read_frame_count(context: Context, img: np.ndarray, item_id: str, label: str = "") -> int | None:
    """在当前帧读该材料的掉落数量；未命中或读不到数字返回 None。"""
    template = f"Items_processed/Item-{item_id}.png"
    detail = context.run_recognition(
        DROP_REGION_NODE,
        img,
        {DROP_REGION_NODE: {"recognition": {"param": {"template": [template]}}}},
    )
    box = best_box(detail)
    if box is None:
        return None

    roi = count_roi(list(box))
    filtered = filter_digit_colors(img)
    count_detail = context.run_recognition(
        DROP_COUNT_NODE,
        filtered,
        {DROP_COUNT_NODE: {"recognition": {"param": {"roi": roi}}}},
    )
    text = ocr_text(count_detail)
    digits = re.sub(r"\D", "", text)
    if not digits:
        logger.warning(f"结算页 {label or item_id} 数量识别失败: {text!r}（roi={roi}）")
        return None
    return int(digits)


def read_battle_drops(context: Context, item_id: str, label: str = "") -> int | None:
    """读一局战斗的掉落数量；读不到返回 None（按未掉落处理）。"""
    for swipe in range(MAX_SWIPES + 1):
        img = context.tasker.controller.post_screencap().wait().get()
        count = read_frame_count(context, img, item_id, label)
        if count is not None:
            return count
        if swipe >= MAX_SWIPES:
            break
        logger.debug(f"结算页未找到 {item_id}，横向滑动第 {swipe + 1} 次")
        context.tasker.controller.post_swipe(*SWIPE_FROM, *SWIPE_TO, SWIPE_DURATION).wait()
        time.sleep(SWIPE_SETTLE_SECONDS)
    return None
