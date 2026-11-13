"""魔精诈唬牌 · 状态识别（CustomRecognition）。

把对局状态机搬到 pipeline：每个状态一个识别节点，靠这里的 ``ZhapianState``
（参数 ``state``）判定「当前画面是否处于该状态」。命中返回全屏 box（只是给框架
一个 hit 信号），决策与点击由 ``custom.action.zhapian_auto`` 完成。

参数（``custom_recognition_param``，JSON 字符串）：
    {"state": "claim"}   # claim / adjudicate / gameover / start / reveal
"""
from __future__ import annotations

import numpy as np
from custom.zhapian_core import detect
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from utils.logger import logger
from utils.params import parse_params

_STATES = ("claim", "adjudicate", "gameover", "start", "reveal")


@AgentServer.custom_recognition("ZhapianState")
class ZhapianState(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | None:
        params = parse_params(argv.custom_recognition_param, "state")
        state = params["state"]
        if state not in _STATES:
            logger.error(f"[ZhapianState] 未知 state={state!r}")
            return None

        # 控制器给的是 BGR，detect 内部按 RGB 处理
        img = np.ascontiguousarray(argv.image[:, :, ::-1])
        st = detect(img)
        if st["state"] == state:
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 1, 1],
                detail={"state": state, "hand": [c["type"] for c in st["hand"]],
                        "claimed": len(st["claimed"])},
            )
        return None
