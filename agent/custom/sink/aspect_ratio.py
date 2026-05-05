"""
分辨率检查器

在任务开始时检查模拟器分辨率是否为 16:9，如果不是则停止任务并输出警告。
"""

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink
from utils.logger import logger

# 目标宽高比：16:9
TARGET_RATIO = 16.0 / 9.0
# 容差范围（±2%）
TOLERANCE = 0.02
SWITCH_ACCOUNT_REQUIRED_RESOLUTION = (1280, 720)


def is_aspect_ratio_16x9(width: int, height: int) -> bool:
    """
    检查给定的尺寸是否大约为 16:9
    同时处理横屏（16:9）和竖屏（9:16）方向
    """
    if width <= 0 or height <= 0:
        return False

    ratio = calculate_aspect_ratio(width, height)

    # 检查比例是否在 16:9 的容差范围内
    return abs(ratio - TARGET_RATIO) <= TARGET_RATIO * TOLERANCE


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


def get_controller_resolution(
    controller, ensure_screencap: bool = True
) -> tuple[int, int]:
    if controller is None:
        return (0, 0)

    if ensure_screencap:
        try:
            img = controller.cached_image
            if img is None:
                controller.post_screencap().wait().get()
        except Exception as exc:
            logger.warning(f"初始化分辨率失败: {exc}")

    try:
        width, height = controller.resolution
    except Exception as exc:
        logger.warning(f"获取控制器分辨率失败: {exc}")
        return (0, 0)

    return (int(width), int(height))


def format_resolution(width: int, height: int) -> str:
    return f"{width}x{height}"


@AgentServer.tasker_sink()
class AspectRatioChecker(TaskerEventSink):
    """
    分辨率检查器
    在任务开始时检查设备分辨率是否为 16:9
    """

    def __init__(self):
        self._checked = False

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: NotificationType,
        detail: TaskerEventSink.TaskerTaskDetail,
    ):
        # 只在任务开始时检查
        if noti_type != NotificationType.Starting:
            return

        # 忽略停止任务事件
        if detail.entry == "MaaTaskerPostStop":
            logger.debug("收到 PostStop 事件，跳过分辨率检查")
            return

        # 每次任务开始时都检查（不再使用 _checked 标志）
        logger.debug(
            f"任务开始前检查分辨率 - task_id: {detail.task_id}, entry: {detail.entry}"
        )

        # 获取控制器
        controller = tasker.controller
        if controller is None:
            logger.error("无法获取控制器")
            return

        width, height = get_controller_resolution(controller, ensure_screencap=True)
        if width <= 0 or height <= 0:
            logger.error("无法获取控制器实际未缩放分辨率")
            tasker.post_stop()
            return

        logger.debug(f"实际未缩放分辨率: {format_resolution(width, height)}")

        if detail.entry == "SwitchAccount":
            if (width, height) != SWITCH_ACCOUNT_REQUIRED_RESOLUTION:
                logger.error(
                    f"切换账号仅支持 1280x720 实际未缩放分辨率，当前: {format_resolution(width, height)}"
                )
                tasker.post_stop()
            else:
                logger.debug(
                    f"切换账号分辨率检查通过: {format_resolution(width, height)}"
                )
            return

        # 检查宽高比
        if not is_aspect_ratio_16x9(width, height):
            actual_ratio = calculate_aspect_ratio(width, height)
            logger.error(
                f"🚨 分辨率比例不匹配！任务已停止。"
                f"当前: {format_resolution(width, height)} (比例: {actual_ratio:.4f})，"
                f"M9A 仅支持 16:9 比例，请调整为: 2560x1440, 1920x1080, 1600x900, 1280x720(推荐)"
            )

            # 停止任务
            tasker.post_stop()
        else:
            logger.debug(f"分辨率检查通过: {format_resolution(width, height)} (16:9)")
