"""Aspect ratio helpers without runtime framework dependencies."""

# 目标宽高比：16:9
TARGET_RATIO = 16.0 / 9.0
# 允许常见分辨率四舍五入带来的 1 像素误差，例如 1366x768。
MAX_ASPECT_RATIO_PIXEL_ERROR = 1


def is_aspect_ratio_16x9(width: int, height: int) -> bool:
    """
    检查给定的尺寸是否大约为 16:9
    同时处理横屏（16:9）和竖屏（9:16）方向
    """
    if width <= 0 or height <= 0:
        return False

    long_side = max(width, height)
    short_side = min(width, height)
    error = abs(long_side * 9 - short_side * 16)

    return error <= 16 * MAX_ASPECT_RATIO_PIXEL_ERROR


def calculate_aspect_ratio(width: int, height: int) -> float:
    """
    计算宽高比，始终返回 较大/较小 的比值
    这样可以统一处理横屏和竖屏方向
    """
    w = float(width)
    h = float(height)

    # 始终返回较大值/较小值，以统一方向
    if w > h:
        return w / h
    return h / w
