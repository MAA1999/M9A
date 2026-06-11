"""自定义识别最近分析帧缓存。

调度节点超时走 on_error 兜底节点时，兜底节点本身没有识别帧，
重新截图可能拍到已变化的游戏状态。自定义识别在每次 analyze 时
把当前帧存入此缓存，兜底存图动作优先取缓存帧，保证保存的是
触发超时判定时的确切画面。
"""

import time

import numpy as np

_frame: np.ndarray | None = None
_timestamp: float = 0.0


def remember(image: np.ndarray) -> None:
    global _frame, _timestamp
    _frame = np.array(image, copy=True)
    _timestamp = time.monotonic()


def latest(max_age_sec: float = 120.0) -> np.ndarray | None:
    """返回缓存帧；无缓存或缓存过旧（场景早已切换）时返回 None。"""
    if _frame is None or time.monotonic() - _timestamp > max_age_sec:
        return None
    return _frame
