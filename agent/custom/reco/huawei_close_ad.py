"""华为服启动广告关闭按钮识别：多尺度笔画掩码匹配。

程序化生成「圆圈 + X」笔画掩码，与二值化后的屏幕笔画做多尺度 F1 匹配，
不依赖位图素材，对按钮尺寸（实测 27~51px）与渲染差异都不敏感。

参数（roi / threshold / min_scale / max_scale / scale_step / min_brightness）全部可选，
含义与默认值见 tools/schema/custom.recognition.schema.json。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from utils.logger import logger
from utils.params import parse_params

DEFAULT_ROI: tuple[int, int, int, int] = (800, 0, 480, 400)
DEFAULT_THRESHOLD = 0.65
DEFAULT_MIN_SCALE = 0.25
# 上限 1.0 ⇒ 模板最大 64px。实测广告按钮最大 51px，仍有尺寸余量；
# 更高的上限（1.6 时约 102px）只增加扫描尺度数、拖慢未命中的帧，无实测收益。
DEFAULT_MAX_SCALE = 1.0
DEFAULT_SCALE_STEP = 0.015
DEFAULT_MIN_BRIGHTNESS = 100

TEMPLATE_BASE_SIZE = 64  # 模板基准直径，实际匹配时按 scale 缩放
# 笔画宽度/直径。实测按钮笔画密度约 24%，该比例下模板与真实笔画最接近
STROKE_RATIO = 1.0 / 18.0
MIN_HIT_RATIO = 0.3  # 命中至少要覆盖这么多模板笔画，避免极小模板匹配到零星噪点
MIN_HIT_PIXELS = 6


def _build_close_icon_mask(size: int = TEMPLATE_BASE_SIZE) -> np.ndarray:
    """生成「圆圈 + X」笔画掩码，X 的四个端点落在圆环的 45° 方向上。"""
    if size < 8:
        raise ValueError(f"模板尺寸过小: {size}")

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    center = (size - 1) / 2.0
    radius = size / 2.0 - 1.0
    half_stroke = max(0.5, size * STROKE_RATIO / 2.0)

    dist_center = np.sqrt((xx - center) ** 2 + (yy - center) ** 2)
    ring = np.abs(dist_center - radius) <= half_stroke

    # 内部 X：两条对角线
    offset = radius / math.sqrt(2.0)
    cross = np.zeros((size, size), dtype=bool)
    for (x1, y1), (x2, y2) in (
        ((-offset, -offset), (offset, offset)),
        ((offset, -offset), (-offset, offset)),
    ):
        ax, ay = center + x1, center + y1
        vx, vy = x2 - x1, y2 - y1
        wx, wy = xx - ax, yy - ay
        denom = vx * vx + vy * vy
        t = np.clip((wx * vx + wy * vy) / denom, 0.0, 1.0)
        px, py = ax + t * vx, ay + t * vy
        cross |= np.sqrt((xx - px) ** 2 + (yy - py) ** 2) <= half_stroke

    return ring | cross


def _resize_mask(mask: np.ndarray, size: int) -> np.ndarray:
    """把 bool 掩码最近邻缩放到 ``size × size``。"""
    if size < 4:
        return np.zeros((0, 0), dtype=bool)
    src = mask.shape[0]
    idx = np.clip((np.arange(size) * src) // size, 0, src - 1)
    return mask[idx][:, idx]


def _next_fast_len(size: int) -> int:
    """返回不小于 ``size`` 的「快速 FFT 长度」（只含 2/3/5 因子）。

    直接补到 2 的幂会带来数倍无谓开销。
    """
    if size <= 16:
        return 16
    best = 1 << (size - 1).bit_length()
    value = 1
    while value < size:
        value *= 2
    best = min(best, value)
    value = 1
    while value < size:
        value *= 3
    best = min(best, value)
    value = 1
    while value < size:
        value *= 5
    best = min(best, value)
    for twos in (1, 2, 4, 8, 16, 32, 64):
        value = twos
        while value < size:
            value *= 3
        best = min(best, value)
        value = twos
        while value < size:
            value *= 5
        best = min(best, value)
    return best


def _correlate2d_with_spectrum(
    spectrum_image: np.ndarray,
    kernel: np.ndarray,
    fft_shape: tuple[int, int],
    out_shape: tuple[int, int],
) -> np.ndarray:
    """用预先算好的图像频谱做 valid 模式相关（图像频谱对所有尺度相同，只需算一次）。"""
    ker_h, ker_w = kernel.shape
    spectrum_ker = np.fft.rfft2(kernel[::-1, ::-1].astype(np.float32), fft_shape)
    full = np.fft.irfft2(spectrum_image * spectrum_ker, fft_shape)
    return full[ker_h - 1 : ker_h - 1 + out_shape[0], ker_w - 1 : ker_w - 1 + out_shape[1]]


def _integral(mask: np.ndarray) -> np.ndarray:
    """计算积分图，便于 O(1) 求任意矩形内的像素和。"""
    return np.pad(mask.astype(np.int64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))


def _window_sums(integral: np.ndarray, height: int, width: int) -> np.ndarray:
    """由积分图求出每个 ``height × width`` 窗口内的像素和。"""
    return (
        integral[height:, width:]
        - integral[:-height, width:]
        - integral[height:, :-width]
        + integral[:-height, :-width]
    )


def _coerce_roi(value: Any, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """把 JSON 里的 roi 转成 4 元组，非法值回落默认。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        logger.warning(f"[HuaweiCloseAd] roi 非法（{value!r}），回落默认 {fallback}")
        return fallback
    try:
        return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    except (TypeError, ValueError):
        logger.warning(f"[HuaweiCloseAd] roi 元素无法转为整数（{value!r}），回落默认 {fallback}")
        return fallback


def _coerce_float(value: Any, fallback: float, key: str) -> float:
    """把 JSON 里的数值参数转成 float，非法值回落默认。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            logger.warning(f"[HuaweiCloseAd] {key} 非法（{value!r}），回落默认 {fallback}")
        return fallback
    return float(value)


@AgentServer.custom_recognition("HuaweiCloseAd")
class HuaweiCloseAd(CustomRecognition):
    """识别华为服启动广告弹窗的关闭按钮，未命中返回 ``box=None``。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = parse_params(argv.custom_recognition_param)

        roi = _coerce_roi(params.get("roi"), DEFAULT_ROI)
        threshold = _coerce_float(params.get("threshold"), DEFAULT_THRESHOLD, "threshold")
        min_scale = _coerce_float(params.get("min_scale"), DEFAULT_MIN_SCALE, "min_scale")
        max_scale = _coerce_float(params.get("max_scale"), DEFAULT_MAX_SCALE, "max_scale")
        scale_step = _coerce_float(params.get("scale_step"), DEFAULT_SCALE_STEP, "scale_step")
        min_brightness = _coerce_float(params.get("min_brightness"), DEFAULT_MIN_BRIGHTNESS, "min_brightness")

        # scale_step 非正会让尺度循环走不完，必须挡住
        if scale_step <= 0:
            logger.warning(f"[HuaweiCloseAd] scale_step 必须为正（{scale_step}），改用 {DEFAULT_SCALE_STEP}")
            scale_step = DEFAULT_SCALE_STEP
        if min_scale > max_scale:
            min_scale, max_scale = max_scale, min_scale

        image = argv.image
        if image.size == 0:
            logger.error(f"[HuaweiCloseAd] 图像为空 | node={argv.node_name}")
            return CustomRecognition.AnalyzeResult(box=None, detail={"reason": "图像为空"})

        gray = self._to_gray(image)
        if gray is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"reason": "图像通道异常"})

        # roi 可能越界，先裁剪
        roi_x, roi_y, roi_w, roi_h = roi
        img_h, img_w = gray.shape[:2]
        x0 = max(0, min(roi_x, img_w))
        y0 = max(0, min(roi_y, img_h))
        x1 = max(x0, min(roi_x + roi_w, img_w))
        y1 = max(y0, min(roi_y + roi_h, img_h))
        if x1 - x0 < 8 or y1 - y0 < 8:
            logger.error(f"[HuaweiCloseAd] roi 有效区域过小 | roi={roi} image={gray.shape[:2]}")
            return CustomRecognition.AnalyzeResult(box=None, detail={"reason": "roi 有效区域过小"})

        region = gray[y0:y1, x0:x1]
        screen_mask = region > min_brightness
        if not screen_mask.any():
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "区域内没有达到亮度阈值的笔画像素"},
            )

        integral = _integral(screen_mask)
        template = _build_close_icon_mask()
        # 「圆圈+X」的 X 在框中心交叉，故中心近旁必有笔画像素。小尺度下大圆弧的局部
        # 也能蹭到高分，靠这条淘汰。3x3 邻域与尺度无关，整幅算一次即可。
        stroke_near_center = _window_sums(integral, 3, 3)

        region_h, region_w = screen_mask.shape
        max_side = int(round(TEMPLATE_BASE_SIZE * max_scale))
        max_side = min(max_side, region_h, region_w)
        if max_side < 8:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "缩放上限下模板尺寸过小"},
            )
        # 收敛到区域能容纳的尺度，避免无效尺度空转
        max_scale = min(max_scale, max_side / TEMPLATE_BASE_SIZE)
        # 屏幕掩码的频谱只算一次，供所有尺度复用
        fft_h = _next_fast_len(region_h + max_side - 1)
        fft_w = _next_fast_len(region_w + max_side - 1)
        screen_spectrum = np.fft.rfft2(screen_mask.astype(np.float32), (fft_h, fft_w))

        best_score = 0.0
        best_box: tuple[int, int, int, int] | None = None
        best_detail: dict[str, Any] = {}

        scale = min_scale
        while scale <= max_scale + 1e-9:
            side = int(round(TEMPLATE_BASE_SIZE * scale))
            if side < 8:
                scale += scale_step
                continue

            scaled = _resize_mask(template, side)
            template_count = int(scaled.sum())
            if template_count < MIN_HIT_PIXELS:
                scale += scale_step
                continue

            out_h, out_w = region_h - side + 1, region_w - side + 1
            hits = _correlate2d_with_spectrum(screen_spectrum, scaled, (fft_h, fft_w), (out_h, out_w))
            window = _window_sums(integral, side, side)
            # F1 = 2·命中 / (模板笔画数 + 窗口内笔画数)
            denom = template_count + window
            with np.errstate(divide="ignore", invalid="ignore"):
                f1 = np.where(denom > 0, 2.0 * hits / np.maximum(denom, 1), 0.0)
            f1 = np.where(hits >= max(MIN_HIT_PIXELS, template_count * MIN_HIT_RATIO), f1, 0.0)
            corner = side // 2 - 1
            f1 = np.where(stroke_near_center[corner : corner + out_h, corner : corner + out_w] > 0, f1, 0.0)

            flat_index = int(np.argmax(f1))
            score = float(f1.flat[flat_index])
            if score > best_score:
                row, col = divmod(flat_index, f1.shape[1])
                best_score = score
                best_box = (x0 + col, y0 + row, side, side)
                best_detail = {
                    "score": round(score, 4),
                    "scale": round(scale, 3),
                    "side": side,
                    "hit": int(hits.flat[flat_index]),
                    "template_pixels": template_count,
                }
            scale += scale_step

        if best_box is None or best_score < threshold:
            logger.debug(
                f"[HuaweiCloseAd] 未命中 | best={best_score:.4f} threshold={threshold} | node={argv.node_name}"
            )
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "未达到阈值", "best_score": round(best_score, 4), **best_detail},
            )

        logger.debug(f"[HuaweiCloseAd] 命中 | box={best_box} {best_detail} | node={argv.node_name}")
        return CustomRecognition.AnalyzeResult(box=best_box, detail=best_detail)

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray | None:
        """把 BGR / BGRA / 灰度图统一转成二维灰度数组。"""
        if image.ndim == 2:
            return image.astype(np.float32, copy=False)
        if image.ndim != 3 or image.shape[2] < 3:
            logger.error(f"[HuaweiCloseAd] 不支持的图像形状: {image.shape}")
            return None
        bgr = image[:, :, :3].astype(np.float32, copy=False)
        # BT.601 亮度权重（BGR 顺序）
        return bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299
