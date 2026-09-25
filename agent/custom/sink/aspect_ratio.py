"""
分辨率检查器

在任务开始时检查模拟器分辨率是否为 16:9，如果不是则停止任务并输出警告。
"""

import time
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink
from utils.aspect_ratio import calculate_aspect_ratio, is_aspect_ratio_16x9
from utils.logger import logger

SWITCH_ACCOUNT_REQUIRED_RESOLUTION = (1280, 720)
# maa 的 resolution 只有在本帧已有截图后才有值，缓存为空时读取会得到 (0, 0)。
# 补截图后最多再重试这么多轮，仍读不到就由调用方跳过本次检查。
MAX_RESOLUTION_RETRIES = 20
RESOLUTION_RETRY_INTERVAL_SECONDS = 1.0


def read_controller_resolution(controller: Any) -> tuple[int, int]:
    try:
        width, height = controller.resolution
    except Exception as exc:
        logger.warning(f"获取控制器分辨率失败: {exc}")
        return (0, 0)

    return (int(width), int(height))


def get_controller_resolution(controller: Any, ensure_screencap: bool = True) -> tuple[int, int]:
    if controller is None:
        return (0, 0)

    width, height = read_controller_resolution(controller)
    if not ensure_screencap:
        return (width, height)

    for _ in range(MAX_RESOLUTION_RETRIES):
        if width > 0 and height > 0:
            return (width, height)

        try:
            controller.post_screencap().wait().get()
        except Exception as exc:
            logger.warning(f"初始化分辨率失败: {exc}")
            return (0, 0)

        width, height = read_controller_resolution(controller)
        if width <= 0 or height <= 0:
            time.sleep(RESOLUTION_RETRY_INTERVAL_SECONDS)

    return (width, height)


def format_resolution(width: int, height: int) -> str:
    return f"{width}x{height}"


@AgentServer.tasker_sink()
class AspectRatioChecker(TaskerEventSink):
    """
    分辨率检查器
    在任务开始时检查设备分辨率是否为 16:9
    """

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

        logger.debug(f"任务开始前检查分辨率 - task_id: {detail.task_id}, entry: {detail.entry}")

        # 获取控制器
        controller = tasker.controller

        width, height = get_controller_resolution(controller, ensure_screencap=True)
        if width <= 0 or height <= 0:
            # 读不到分辨率不等于分辨率不合规，跳过本次检查而不是停掉整条任务链
            logger.warning("无法获取控制器实际未缩放分辨率，跳过本次分辨率检查")
            return

        logger.debug(f"实际未缩放分辨率: {format_resolution(width, height)}")

        if detail.entry == "SwitchAccount":
            if (width, height) != SWITCH_ACCOUNT_REQUIRED_RESOLUTION:
                logger.error(f"切换账号仅支持 1280x720 实际未缩放分辨率，当前: {format_resolution(width, height)}")
                tasker.post_stop()
            else:
                logger.debug(f"切换账号分辨率检查通过: {format_resolution(width, height)}")
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
