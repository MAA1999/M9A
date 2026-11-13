"""游戏内 UID 的多次采样。

## 为什么要采样多次

`RecordId` 节点在主界面读一次 UID 就写进缓存。单次 OCR 有几个不可靠的地方：

- 主页动画还没结束，UID 区域可能只显示了一半；
- OCR 偶发把某个数字认错（尤其是 `0`/`8`、`1`/`7`）；
- 切号过程中画面处于过渡态。

一个错的 UID 会让状态文件多出一个**永远用不到的桶**，而且用户很难察觉。
所以这里连续读多次，只有**完全一致**才采信。

## 采样规则（用户指定）

- 每轮读 3 次，每次间隔 1 秒；
- **第一轮 3 次全一致 → 立即返回**（不读第二轮，省时间）；
- 第一轮不一致 → 再读 3 次，共 6 次；
- **6 次全部一致才算可信**；出现任何不一致（包括 5:1、4:2）都判为读不到。

比「多数表决」严格：宁可这一轮不记录，也不要记到一个可能是错的 UID 名下。

## 读不到怎么办

返回空串。调用方（`BalancedTaskEntry`）据此走「顺延但不落盘」的分支，
并保存一张现场截图便于排查。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from utils.logger import logger

if TYPE_CHECKING:
    from maa.context import Context

# 每轮采样次数
ROUND_SIZE = 3
# 最多几轮（3 × 2 = 6 次）
MAX_ROUNDS = 2
# 每次采样之间的间隔（秒）
SAMPLE_INTERVAL_SEC = 1.0

# 与 `RecordID` 保持一致：主页 UID 区域
_ID_ROI: tuple[int, int, int, int] = (54, 116, 92, 20)


def sample_uid(context: Context) -> str:
    """连续采样游戏内 UID，返回可信值；读不到返回空串。

    第一轮 3 次全一致就提前返回；否则读满 6 次，要求全部一致。
    """
    samples: list[str] = []

    for round_no in range(MAX_ROUNDS):
        for index in range(ROUND_SIZE):
            # 第一轮第一次之前不需要等待；之后每次都等一个间隔
            if round_no > 0 or index > 0:
                time.sleep(SAMPLE_INTERVAL_SEC)
            samples.append(_read_once(context))

        if round_no == 0:
            # 第一轮就全一致 → 提前返回，不必再花 3 秒
            if _all_same(samples):
                logger.info(f"UID 采样一致（第 1 轮 {ROUND_SIZE} 次）: {samples[0]}")
                return samples[0]
            logger.debug(f"UID 第 1 轮不一致，继续采样: {samples}")

    if _all_same(samples):
        logger.info(f"UID 采样一致（{len(samples)} 次）: {samples[0]}")
        return samples[0]

    logger.warning(f"UID 采样不一致，判为读不到（共 {len(samples)} 次）: {samples}")
    return ""


def _all_same(samples: list[str]) -> bool:
    """是否全部一致，且不是空串。"""
    if not samples:
        return False
    first = samples[0]
    if not first:
        return False
    return all(value == first for value in samples)


def _read_once(context: Context) -> str:
    """取一帧新画面并读 UID 区域；失败返回空串。

    ⚠️ 用 `post_screencap()` 取**新帧**，不用 `cached_image` ——
    缓存帧可能是上一次识别留下的，连续读它会一直读到同一个（可能是错的）值，
    采样就失去意义了。
    """
    from maa.pipeline import JOCR, JRecognitionType
    from utils.maa_types import ocr_text

    try:
        image = context.tasker.controller.post_screencap().wait().get()
    except Exception as exc:  # noqa: BLE001 - 截图失败只表示本次没读到
        logger.debug(f"UID 采样取帧失败: {exc}")
        return ""

    try:
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=_ID_ROI, only_rec=True),
            image,
        )
    except Exception as exc:  # noqa: BLE001 - OCR 失败只表示本次没读到
        logger.debug(f"UID 采样识别失败: {exc}")
        return ""

    return ocr_text(detail).strip()


__all__ = ["SAMPLE_INTERVAL_SEC", "sample_uid"]
