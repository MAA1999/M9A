import time
from pathlib import Path

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from PIL import Image
from utils import logger


@AgentServer.custom_action("APSaveDebug")
class APSaveDebug(CustomAction):
    """
    推图遇到未知界面的兜底：保存当前截图到 debug/auto_promotion/，
    便于事后补充识别规则。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.post_screencap().wait().get()
        out_dir = Path("debug/auto_promotion")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"unknown_{time.strftime('%Y%m%d_%H%M%S')}.png"
        Image.fromarray(np.asarray(img)[..., ::-1]).save(path)
        logger.error(
            f"[AutoPromotion] 长时间未识别到任何已知界面，截图已保存: {path.resolve()}"
        )
        return CustomAction.RunResult(success=True)
