"""魔精诈唬牌 · 决策/点击动作。

状态机在 pipeline 里（``resource/base/pipeline/zhapian.json``）：每个状态一个识别节点
（``ZhapianState`` 识别），命中后落到这里的 ``ZhapianAct``，按 ``mode`` 只做
「读手牌 → 决策 → 点击」这一件事，不再自己跑整局循环——循环由 pipeline 的 ``next``
与 ``override_next`` 表达，框架因此可见状态、可随时停止。

参数（``custom_action_param``，JSON 字符串）：
    {"mode": "claim"}                                     # 出牌
    {"mode": "judge"}                                     # 判定
    {"mode": "gameover", "max_games": 5, "after": "restart"}
    {"mode": "start"}                                     # 开始页：复位计数并点开始
    通用可选：target / remaining / dry_run
"""
from __future__ import annotations

import numpy as np
from custom.zhapian_core import (
    CARD_DX,
    CARD_DY,
    CARD_GOLD_MIN,
    CONFIRM_PT,
    DOUBT_PT,
    EXIT_PT,
    RESTART_PT,
    START_PT,
    TRUST_PT,
    detect,
    detect_target,
    gold_pixels,
    p_claim_true,
    plan_claim,
)
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils.logger import logger
from utils.params import coerce_like, parse_params

_GAME_OVER_NODE = "zhapianGameover"


def _rgb(context: Context) -> np.ndarray:
    frame = context.tasker.controller.cached_image
    return np.ascontiguousarray(frame[:, :, ::-1])


@AgentServer.custom_action("ZhapianAct")
class ZhapianAct(CustomAction):
    games: int = 0

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = parse_params(argv.custom_action_param, "mode")
        mode = params["mode"]
        dry_run = bool(coerce_like(params.get("dry_run", False), False, "dry_run"))

        target = params.get("target")
        if target not in (None, "A", "B", "C"):
            target = None
        remaining = {"A": 5, "B": 5, "C": 5, "W": 3}
        raw_rem = params.get("remaining")
        if isinstance(raw_rem, (list, tuple)) and len(raw_rem) == 4:
            remaining = {"A": int(raw_rem[0]), "B": int(raw_rem[1]),
                         "C": int(raw_rem[2]), "W": int(raw_rem[3])}

        def click(x: int, y: int) -> None:
            if dry_run:
                logger.info(f"[zhapian][dry] click ({x}, {y})")
                return
            context.tasker.controller.post_click(x, y).wait()

        if mode == "start":
            ZhapianAct.games = 0
            click(*START_PT)
            return CustomAction.RunResult(success=True)

        img = _rgb(context)
        st = detect(img)

        if mode == "claim":
            tgt = target or detect_target(img)
            picks, info = plan_claim(st["hand"], tgt)
            logger.info(f"[zhapian] claim {info} picks={picks} target={tgt} hand={[c['type'] for c in st['hand']]}")
            selected = 0
            for i in picks:
                if i < len(st["hand"]) and self._select_card(context, st["hand"][i]["box"]):
                    selected += 1
            if selected > 0:
                click(*CONFIRM_PT)
            else:
                logger.warning("[zhapian] 选牌全部失败，不点确认")
            return CustomAction.RunResult(success=True)

        if mode == "judge":
            if st["trust_btn"] and st["doubt_btn"]:
                n = max(2, len(st["claimed"]))
                tgt = target or detect_target(img)
                p = p_claim_true(n, remaining, tgt)
                decision = "trust" if p >= 0.5 else "doubt"
                logger.info(f"[zhapian] judge n={n} p_true={p:.2f} -> {decision}")
                click(*(TRUST_PT if decision == "trust" else DOUBT_PT))
            else:
                logger.info("[zhapian] 声称牌未识别，按保守怀疑")
                click(*DOUBT_PT)
            return CustomAction.RunResult(success=True)

        if mode == "gameover":
            max_games = int(coerce_like(params.get("max_games", 5), 5, "max_games"))
            after = str(coerce_like(params.get("after", "restart"), "restart", "after"))
            ZhapianAct.games += 1
            limit = f"/{max_games}" if max_games else "/∞"
            logger.info(f"[zhapian] 第 {ZhapianAct.games}{limit} 局结束")
            if max_games and ZhapianAct.games >= max_games:
                click(*EXIT_PT)
                # 停止循环：让本节点不再回到入口，任务自然结束
                context.override_next(_GAME_OVER_NODE, [])
                return CustomAction.RunResult(success=True)
            if after == "restart":
                click(*RESTART_PT)
            else:
                click(*EXIT_PT)
            return CustomAction.RunResult(success=True)

        logger.error(f"[zhapian] 未知 mode={mode!r}")
        return CustomAction.RunResult(success=False)

    def _select_card(self, context: Context, box: tuple[int, int, int, int]) -> bool:
        cx = int((box[0] + box[1]) / 2) + CARD_DX
        cy = int((box[2] + box[3]) / 2) + CARD_DY
        for dx, dy in ((0, 0), (0, 8), (0, -8), (12, 0), (-12, 0)):
            context.tasker.controller.post_click(cx + dx, cy + dy).wait()
            import time
            time.sleep(0.45)
            if gold_pixels(_rgb(context), box) > CARD_GOLD_MIN:
                return True
        return False
