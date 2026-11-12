"""把当前游戏画面存成 PNG，便于排查。

## 用途

均衡刷材料任务里有两个「需要留证」的场合：

1. **读不到游戏内 UID** —— 此时无法确定账号归属，任务会走「顺延但不落盘」分支。
   存一张主页截图，用户可以把 `debug/` 下的这张图发给维护者，看看是不是主页
   没有正常显示账号信息、或者停在别的界面。
2. **该 UID 已被标记为「所有候选关卡都不可用」** —— 存一张图记录跳过时的界面。

## 存到哪里

复用框架已有的 `debug/` 目录（`agent/utils/logger.py` 的日志也写在 `debug/custom/`，
`.gitignore` 已忽略整个 `debug/`）。文件名带时间戳，日志里打印完整路径。

**不做清理**：这类图只在异常路径产生，数量很少（正常使用一年也不会有几张），
不值得为它引入删除逻辑。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from utils.logger import logger

if TYPE_CHECKING:
    from maa.context import Context

# 与框架日志同级的调试目录（`.gitignore` 已忽略）
DEBUG_DIR = Path("debug")


def save_debug_screenshot(context: Context, tag: str) -> str | None:
    """存一张当前画面的截图，返回路径；失败返回 None。

    Args:
        context: 动作上下文（用它的控制器取新帧）。
        tag: 文件名里的场景标记，例如 `no_uid` / `skipped`。

    Returns:
        图片路径字符串；任何一步失败都返回 None（**截图失败不该影响任务流程**）。
    """
    try:
        image = context.tasker.controller.post_screencap().wait().get()
    except Exception as exc:  # noqa: BLE001 - 取帧失败只表示这次没留成证据
        logger.warning(f"保存现场截图失败（取帧出错）: {exc}")
        return None

    path = DEBUG_DIR / f"balanced_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_png(path, image)
    except Exception as exc:  # noqa: BLE001 - 写盘失败同上
        logger.warning(f"保存现场截图失败（写盘出错）: {exc}")
        return None

    logger.warning(f"已保存现场截图: {path}")
    return str(path)


def _write_png(path: Path, image: object) -> None:
    """把框架给的 BGR 图像写成 PNG。

    框架截图是 BGR 的 numpy 数组（见 `custom/action/eight_bit.py` 的注释），
    所以存盘前要转成 RGB，否则颜色会偏。
    """
    import numpy as np
    from PIL import Image

    array = np.asarray(image)
    if array.ndim == 3 and array.shape[2] >= 3:
        # BGR → RGB
        array = array[:, :, ::-1]
    Image.fromarray(array).save(path)


__all__ = ["DEBUG_DIR", "save_debug_screenshot"]
