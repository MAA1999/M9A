"""渠道服启动广告关闭按钮识别：多尺度笔画掩码匹配。

程序化生成「圆圈 + X」与纯「X」两种笔画掩码，与二值化后的屏幕笔画做多尺度 F1 匹配，
不依赖位图素材，对按钮尺寸（华为服实测 27~51px）与渲染差异都不敏感。

节点默认关闭，由有启动广告的渠道在自身资源包覆盖 enabled 开启（见 resource/base
的 CloseAd 节点）。

参数（shapes / roi / threshold / x_threshold / min_scale / max_scale / scale_step /
min_brightness）全部可选，含义与默认值见 tools/schema/custom.recognition.schema.json。
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

# 两种广告关闭按钮形态：「圆圈 + X」（华为服实测）与纯「X」（无外圈的那种）
SHAPE_CIRCLE_X = "circle_x"
SHAPE_X = "x"
DEFAULT_SHAPES: tuple[str, ...] = (SHAPE_CIRCLE_X, SHAPE_X)
# 纯 X 少了一圈笔画做佐证、误配空间更大，故用更高阈值。实测：真按钮 0.73~0.99
# （含 20px 小按钮与 3px 粗笔画），纯色底/纯噪点最高 0.41
DEFAULT_X_THRESHOLD = 0.7


def _capsule(
    xx: np.ndarray,
    yy: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    half: float,
) -> np.ndarray:
    """到线段距离 ≤ half 的像素集合，即一条两端圆头的笔画。"""
    (x1, y1), (x2, y2) = start, end
    vx, vy = x2 - x1, y2 - y1
    t = np.clip(((xx - x1) * vx + (yy - y1) * vy) / (vx * vx + vy * vy), 0.0, 1.0)
    return np.sqrt((xx - (x1 + t * vx)) ** 2 + (yy - (y1 + t * vy)) ** 2) <= half


def _build_close_icon_mask(size: int = TEMPLATE_BASE_SIZE) -> np.ndarray:
    """生成「圆圈 + X」笔画掩码，X 的四个端点落在圆环的 45° 方向上。"""
    if size < 8:
        raise ValueError(f"模板尺寸过小: {size}")

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    center = (size - 1) / 2.0
    radius = size / 2.0 - 1.0
    half_stroke = max(0.5, size * STROKE_RATIO / 2.0)

    ring = np.abs(np.sqrt((xx - center) ** 2 + (yy - center) ** 2) - radius) <= half_stroke
    # 内部 X：两条对角线
    offset = radius / math.sqrt(2.0)
    cross = _capsule(
        xx, yy, (center - offset, center - offset), (center + offset, center + offset), half_stroke
    ) | _capsule(xx, yy, (center + offset, center - offset), (center - offset, center + offset), half_stroke)
    return ring | cross


def _build_cross_mask(size: int = TEMPLATE_BASE_SIZE) -> np.ndarray:
    """生成纯「X」笔画掩码：两条对角线端点内缩半个笔画，外接框正好铺满模板。"""
    if size < 8:
        raise ValueError(f"模板尺寸过小: {size}")

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    half_stroke = max(0.5, size * STROKE_RATIO / 2.0)
    low, high = half_stroke, size - 1 - half_stroke
    return _capsule(xx, yy, (low, low), (high, high), half_stroke) | _capsule(
        xx, yy, (high, low), (low, high), half_stroke
    )


def _build_mask(shape: str, size: int = TEMPLATE_BASE_SIZE) -> np.ndarray:
    """按形态取模板掩码；未知形态按「圆圈 + X」处理。"""
    return _build_cross_mask(size) if shape == SHAPE_X else _build_close_icon_mask(size)


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
        logger.warning(f"[CloseAd] roi 非法（{value!r}），回落默认 {fallback}")
        return fallback
    try:
        return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    except (TypeError, ValueError):
        logger.warning(f"[CloseAd] roi 元素无法转为整数（{value!r}），回落默认 {fallback}")
        return fallback


def _coerce_shapes(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """把 JSON 里的 shapes 转成合法形态元组（去重保序），非法项剔除后回落默认。"""
    if not isinstance(value, (list, tuple)):
        if value is not None:
            logger.warning(f"[CloseAd] shapes 非法（{value!r}），回落默认 {fallback}")
        return fallback

    shapes: list[str] = []
    for item in value:
        if item not in DEFAULT_SHAPES:
            logger.warning(f"[CloseAd] shapes 含未知形态（{item!r}），已忽略；可选 {DEFAULT_SHAPES}")
            continue
        if item not in shapes:
            shapes.append(item)
    if not shapes:
        logger.warning(f"[CloseAd] shapes 为空，回落默认 {fallback}")
        return fallback
    return tuple(shapes)


def _coerce_float(value: Any, fallback: float, key: str) -> float:
    """把 JSON 里的数值参数转成 float，非法值回落默认。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is not None:
            logger.warning(f"[CloseAd] {key} 非法（{value!r}），回落默认 {fallback}")
        return fallback
    return float(value)


@AgentServer.custom_recognition("CloseAd")
class CloseAd(CustomRecognition):
    """识别渠道服启动广告弹窗的关闭按钮，未命中返回 ``box=None``。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        params = parse_params(argv.custom_recognition_param)

        roi = _coerce_roi(params.get("roi"), DEFAULT_ROI)
        shapes = _coerce_shapes(params.get("shapes"), DEFAULT_SHAPES)
        # 每个形态各自的命中阈值：纯 X 少一圈笔画做佐证，需要更高分
        shape_thresholds = {
            SHAPE_CIRCLE_X: _coerce_float(params.get("threshold"), DEFAULT_THRESHOLD, "threshold"),
            SHAPE_X: _coerce_float(params.get("x_threshold"), DEFAULT_X_THRESHOLD, "x_threshold"),
        }
        min_scale = _coerce_float(params.get("min_scale"), DEFAULT_MIN_SCALE, "min_scale")
        max_scale = _coerce_float(params.get("max_scale"), DEFAULT_MAX_SCALE, "max_scale")
        scale_step = _coerce_float(params.get("scale_step"), DEFAULT_SCALE_STEP, "scale_step")
        min_brightness = _coerce_float(params.get("min_brightness"), DEFAULT_MIN_BRIGHTNESS, "min_brightness")

        # scale_step 非正会让尺度循环走不完，必须挡住
        if scale_step <= 0:
            logger.warning(f"[CloseAd] scale_step 必须为正（{scale_step}），改用 {DEFAULT_SCALE_STEP}")
            scale_step = DEFAULT_SCALE_STEP
        if min_scale > max_scale:
            min_scale, max_scale = max_scale, min_scale

        image = argv.image
        if image.size == 0:
            logger.error(f"[CloseAd] 图像为空 | node={argv.node_name}")
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
            logger.error(f"[CloseAd] roi 有效区域过小 | roi={roi} image={gray.shape[:2]}")
            return CustomRecognition.AnalyzeResult(box=None, detail={"reason": "roi 有效区域过小"})

        region = gray[y0:y1, x0:x1]
        screen_mask = region > min_brightness
        if not screen_mask.any():
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "区域内没有达到亮度阈值的笔画像素"},
            )

        integral = _integral(screen_mask)
        # 两种形态的笔画都在框中心交叉，故中心近旁必有笔画像素。小尺度下大圆弧的局部
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

        # 形态 → (最高分, box, detail)
        best_by_shape: dict[str, tuple[float, tuple[int, int, int, int], dict[str, Any]]] = {}

        for shape in shapes:
            template = _build_mask(shape)
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
                if score > best_by_shape.get(shape, (0.0, (0, 0, 0, 0), {}))[0]:
                    row, col = divmod(flat_index, f1.shape[1])
                    best_by_shape[shape] = (
                        score,
                        (x0 + col, y0 + row, side, side),
                        {
                            "score": round(score, 4),
                            "shape": shape,
                            "scale": round(scale, 3),
                            "side": side,
                            "hit": int(hits.flat[flat_index]),
                            "template_pixels": template_count,
                        },
                    )
                scale += scale_step

        accepted = [
            (score, box, detail)
            for shape, (score, box, detail) in best_by_shape.items()
            if score >= shape_thresholds[shape]
        ]
        if not accepted:
            missed = {shape: detail for shape, (_, _, detail) in best_by_shape.items()}
            logger.debug(f"[CloseAd] 未命中 | {missed} | node={argv.node_name}")
            return CustomRecognition.AnalyzeResult(box=None, detail={"reason": "未达到阈值", "missed": missed})

        _, best_box, best_detail = max(accepted, key=lambda item: item[0])
        logger.debug(f"[CloseAd] 命中 | box={best_box} {best_detail} | node={argv.node_name}")
        return CustomRecognition.AnalyzeResult(box=best_box, detail=best_detail)

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray | None:
        """把 BGR / BGRA / 灰度图统一转成二维灰度数组。"""
        if image.ndim == 2:
            return image.astype(np.float32, copy=False)
        if image.ndim != 3 or image.shape[2] < 3:
            logger.error(f"[CloseAd] 不支持的图像形状: {image.shape}")
            return None
        bgr = image[:, :, :3].astype(np.float32, copy=False)
        # BT.601 亮度权重（BGR 顺序）
        return bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299
