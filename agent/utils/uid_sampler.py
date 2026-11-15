"""游戏内 UID 的多次采样。

## 为什么要采样多次

单次 OCR 有几个不可靠的地方：

- 主页动画还没结束，UID 区域可能只显示了一半；
- OCR 偶发把某个数字认错（尤其是 `0`/`8`、`1`/`7`）；
- 切号过程中画面处于过渡态。

一个错的 UID 会让状态文件多出一个**永远用不到的桶**，而且用户很难察觉。
所以这里连续读多次，只有**完全一致**才采信。

## 读哪一块

**直接复用 `RecordID._id_roi`**，不另写一份 ROI：两份各写死一个数字时，
主页 UI 一移位就只改一处，失效方式是采样永远返回空串、所有记录都不再落盘，
而用户只看到「未能读取游戏内 UID」，极难排查。

## 只取数字

UID 区域里可能同时扫到账号名（玩家名允许中文、字母、数字混排），
所以识别结果**只保留 ASCII 数字**：

    原始 OCR: "小径 ID:118404470"  →  取值: "118404470"
    原始 OCR: "118404470"          →  取值: "118404470"
    原始 OCR: "LV.73 46040/46300"  →  取值: "734604046300"（不合规，被后续校验拒绝）

长度校验：游戏 UID 是 9 位数字。这里放宽到 6~12 位，避免不同服务器位数差异，
但**必须全是数字**，出现任何字母/标点都算这一帧没读到。

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

import re
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

# UID 区域：**必须包含 `ID:` 前缀**。
#
# `RecordID._id_roi = (54,116,92,20)` 只覆盖数字部分（实测读到 `107354242`，
# 不含 `ID:`）。而现在的取值规则是「有 ID 标签才取冒号后的数字，没有就判定
# 读不到」，所以采样要往左多留一点，把 `ID:` 一起框进来。
#
# 真机实测（2026-11-14，1280x720 基准）：整行为 `ID:107354242`，从 x≈28 开始，
# 到 x≈146 结束。
_ID_ROI: tuple[int, int, int, int] = (20, 110, 140, 24)

# 与 `RecordID._id_roi` 保持一致（那张模块图没加载时用同一份字面值兜底）
_FALLBACK_ID_ROI: tuple[int, int, int, int] = _ID_ROI

# 游戏 UID 的合理长度区间。放宽到 6~12 位以兼容不同服务器，
# 但**必须全是数字** —— 这是过滤「扫到账号名」的关键。
UID_MIN_LEN = 6
UID_MAX_LEN = 12


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


def _id_roi() -> tuple[int, int, int, int]:
    """采样用的 UID 区域。

    **不复用 `RecordID._id_roi`**：那个值 `(54,116,92,20)` 只框数字部分，不含
    `ID:` 前缀；而取值规则要求必须有 `ID` 标签才认（见 `extract_digits`），
    用它会让采样稳定返回空串。这里用自己的、往左多留一点的范围。
    """
    return _ID_ROI


def extract_digits(text: str) -> str:
    """从 `ID:数字` 里取 UID；**没有 `ID` 标签、或标签后不是纯数字都返回空串**。

    用户 2026-11-14 明确要求：「有 ID 就取 ID 字符和冒号后的，没有 ID 直接当成
    读不到 UID，不记录只顺延」。

    两条都不能省：

    1. **必须带 `ID` 标签** —— UID 区域会同时扫到**玩家名**，而玩家名允许包含数字：

           原始 OCR: "Player123 ID:118404470"
           直接剥离: "123118404470"   ← 13 位，玩家名的 123 被拼到前面

    2. **标签之后必须是纯数字，不能删掉非法字符** —— 否则 OCR 把字母认成别的样子时
       会被"修"成一个看似合法的 UID：

           原始 OCR: "ID:1184O4470"   （字母 O 冒充数字 0）
           删非数字: "11844470"       ← 8 位，正好通过长度校验
           正确结果: ""               ← 这一帧作废，让 6 次采样去决定

    第 2 条比「删掉非数字」严格：宁可这一帧读不到，也不能把一个可能错的 UID
    写进账号桶 —— 三帧一致会把错误"确认"下来，用户几乎不可能察觉。
    """

    # 找 `ID` 标签（大小写不敏感，兼容中英文冒号）
    match = re.search(r"ID\s*[:：]\s*", text, re.IGNORECASE)
    if match is None:
        # 没有 ID 标签 → 无法确定哪一段是 UID，按「读不到」处理
        return ""

    # 标签之后：取第一个连续数字段，但**要求它一直延伸到尾部**。
    # 只取前缀是不够的 —— `ID:1184044O70` 会取到 `1184044`（7 位，能通过长度校验），
    # 而那是一个被 OCR 认错的 UID。中间夹了字母说明这一帧整体不可信。
    tail = text[match.end() :].strip()
    if not tail or not tail.isascii() or not tail.isdigit():
        return ""
    return tail


def _looks_like_uid(value: str) -> bool:
    """长度在合理区间且全是数字。"""
    return value.isascii() and value.isdigit() and UID_MIN_LEN <= len(value) <= UID_MAX_LEN


# 早前这里有个 `_reject_markers()`，靠「文本里有没有 LV / 斜杠」来排除等级、体力行。
# 现在不需要了：`extract_digits()` 要求必须有 `ID:` 标签且其后是纯数字，
# `LV.73 46040/46300` 这类文本**根本没有 ID 标签**，天然返回空串。
# 那个检查反而有害 —— 玩家名 `Silver` 含 `LV` 子串，会把合法的一帧误杀
# （CodeRabbit 本地复查 2026-11-14 指出）。


def _read_once(context: Context) -> str:
    """取一帧新画面并读 UID 区域；失败返回空串。

    ⚠️ 用 `post_screencap()` 取**新帧**，不用 `cached_image` ——
    缓存帧可能是上一次识别留下的，连续读它会一直读到同一个（可能是错的）值，
    采样就失去意义了。

    ⚠️ 异常分两类，不能一律降级成「本次没读到」：

    - **截图 / 识别偶发失败**（超时、画面还没准备好）→ 返回空串，让采样继续；
    - **接口不存在 / 参数错误**（编程或环境错误）→ 必须抛出来。
      这类错误如果也返回空串，`sample_uid()` 会稳定返回空、所有记录都不再落盘，
      而用户只看到一句「未能读取游戏内 UID」，排查时毫无线索。
    """
    from maa.pipeline import JOCR, JRecognitionType
    from utils.maa_types import ocr_text

    try:
        image = context.tasker.controller.post_screencap().wait().get()
    except (AttributeError, TypeError) as exc:
        # 接口签名不对 = 代码或框架版本问题，不是「这一帧没截到」。
        # 和下面识别块的处理保持一致：这类错误必须抛出去，否则会稳定返回空、
        # 所有按账号分桶的记录都不再落盘，而用户只看到「未能读取游戏内 UID」。
        logger.exception(f"UID 采样无法调用截图接口（这是程序错误，不是截图失败）: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001 - 截图偶发失败，本次算没读到
        logger.warning(f"UID 采样取帧失败（本次跳过）: {exc}")
        return ""

    try:
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=_id_roi(), only_rec=True),
            image,
        )
    except (AttributeError, TypeError) as exc:
        # 接口签名不对 = 代码或框架版本问题，不是「这一帧没读到」。
        logger.exception(f"UID 采样无法调用识别接口（这是程序错误，不是识别失败）: {exc}")
        raise
    except Exception as exc:  # noqa: BLE001 - 识别偶发失败，本次算没读到
        logger.warning(f"UID 采样识别失败（本次跳过）: {exc}")
        return ""

    raw = ocr_text(detail).strip()

    # 只认 `ID:` 标签之后的纯数字。等级行（`LV.73 46040/46300`）没有 ID 标签，
    # 会自然返回空串，不需要额外的「排除 LV」检查。
    digits = extract_digits(raw)
    if not _looks_like_uid(digits):
        if raw:
            logger.debug(f"UID 区域读到非 UID 文本（已忽略）: {raw!r} → 数字 {digits!r}")
        return ""
    return digits


__all__ = [
    "SAMPLE_INTERVAL_SEC",
    "UID_MAX_LEN",
    "UID_MIN_LEN",
    "extract_digits",
    "sample_uid",
]
