"""回主界面失败后，后续任务走到 ReturnMain 时才探测画面，决定继续还是结束当前任务。"""

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType
from maa.pipeline import JActionType, JStopTask
from utils.logger import logger

# ReturnMain 节点名：失败时武装，探测时复用它的 next 作为「画面是否已恢复」的判据
RETURN_MAIN_NODE = "ReturnMain"

# 探测用的临时识别节点，只存在于 run_recognition 的 override 里，不进 resource
PROBE_NODE = "ReturnMainGuardProbe"


def _always_hits(context: Context, reco: Any, seen: set[str]) -> bool:
    """判断一个识别是否「恒命中」——恒命中放进 Or 会让探针永远判已恢复，必须剔除。

    只在「缺省识别 / DirectHit」这两种真正不依赖画面的情形返回 True：
    - Or：任一子项恒命中即恒真；
    - And：所有子项都恒命中才恒真（只要有一个子项要识图，它就不会恒真，例如 HomeLoading
      含模板匹配、SignInReward 含模板匹配）。
    """
    if reco is None:
        # 缺省识别即 DirectHit（任意画面全屏命中），恒真
        return True
    if isinstance(reco, str):
        return reco == "DirectHit"
    if not isinstance(reco, dict):
        return False
    rtype = reco.get("type")
    if rtype == "DirectHit":
        return True

    param = reco.get("param") or {}
    if rtype == "Or":
        subs = param.get("any_of") or []
    elif rtype == "And":
        subs = param.get("all_of") or []
    else:
        return False
    if not subs:
        return False

    results: list[bool] = []
    for sub in subs:
        if isinstance(sub, str):
            results.append(_node_always_hits(context, sub, set(seen)))
        elif isinstance(sub, dict):
            results.append(_always_hits(context, sub.get("recognition"), set(seen)))
        else:
            results.append(False)
    return any(results) if rtype == "Or" else all(results)


def _node_always_hits(context: Context, name: str, seen: set[str]) -> bool:
    if name in seen:
        return False
    seen.add(name)
    data = context.get_node_data(name)
    if data is None:
        return False
    reco = data.get("recognition")
    if reco is None:
        # 节点没写识别即默认 DirectHit，同样恒命中
        return True
    return _always_hits(context, reco, seen)


def _probe_candidates(context: Context) -> list[str]:
    """取 ReturnMain 当前 next 里可用来判断「画面是否恢复」的候选。

    跟随 override / 资源更新自动取清单，不硬编码；并剔除恒命中（DirectHit、含 DirectHit 的
    Or、全恒命中的 And、缺省识别）的候选，避免未来改资源时保护被静默架空。
    """
    data = context.get_node_data(RETURN_MAIN_NODE)
    if not data:
        return []
    names: list[str] = []
    for item in data.get("next") or []:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            continue
        if _node_always_hits(context, name, set()):
            logger.warning(f"探针跳过恒命中候选 {name}（DirectHit 会让探测失去意义）")
            continue
        names.append(name)
    return names


def _screen_recovered(context: Context) -> bool:
    """截一张当前画面，用 ReturnMain 的 next 候选探一次；任一命中即认为画面已恢复。

    任何探测环节失败（候选为空、截图作业失败、截图异常、截图为空、识别异常）都保守地当作
    「未恢复」，即继续跳过——宁可多拦一轮，也不能在认不出的画面上放行任务。
    """
    names = _probe_candidates(context)
    if not names:
        logger.error(f"探测回主界面状态失败：{RETURN_MAIN_NODE} 没有可用的 next 候选")
        return False

    try:
        job = context.tasker.controller.post_screencap()
        job.wait()
        # 截图作业失败时 get() 仍会返回上一帧（cached_image），必须先判作业状态，否则会拿
        # 旧画面误判「已恢复」。
        if not job.status.succeeded:
            logger.error("探测回主界面状态失败：截图作业失败（可能是旧帧，拒绝据此判定）")
            return False
        image = job.get()
    except Exception as exc:  # noqa: BLE001 - 截图链异常只影响本次判定
        logger.error(f"探测回主界面状态失败：截图异常: {exc}")
        return False
    if image.size == 0:
        logger.error("探测回主界面状态失败：截图为空")
        return False

    override = {PROBE_NODE: {"recognition": {"type": "Or", "param": {"any_of": names}}}}
    try:
        detail = context.run_recognition(PROBE_NODE, image, override)
    except Exception as exc:  # noqa: BLE001 - 识别异常只影响本次判定
        logger.error(f"探测回主界面状态失败：识别异常: {exc}")
        return False
    return bool(detail and detail.hit)


@AgentServer.context_sink()
class ReturnMainGuard(ContextEventSink):
    def __init__(self) -> None:
        self.failed_task_id: int | None = None

    def on_node_pipeline_node(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodePipelineNodeDetail,
    ) -> None:
        if detail.name != RETURN_MAIN_NODE:
            return
        if self.failed_task_id is None:
            if noti_type == NotificationType.Failed:
                # run_task 的子流程有独立的事件 ID，Context 保留最外层任务号。
                self.failed_task_id = context.get_task_job().job_id
                logger.warning("回主界面失败，后续任务执行到 ReturnMain 时将检查画面")
            return

        if noti_type != NotificationType.Starting:
            return
        task_id = context.get_task_job().job_id
        if task_id == self.failed_task_id:
            return

        if _screen_recovered(context):
            self.failed_task_id = None
            logger.warning(f"画面已恢复，解除回主界面失败保护 (task_id={task_id})")
            return

        logger.warning(f"回主界面画面仍未恢复，结束当前任务 (task_id={task_id})")
        result = context.run_action_direct(JActionType.StopTask, JStopTask())
        if result is None or not result.success:
            logger.error(f"停止任务失败 (task_id={task_id})")
