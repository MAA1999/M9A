"""魔精诈唬牌 · M9A 自定义动作。

坐标约定：全部按 MaaFW 的 **720p（1280x720）基准**。截图与点击都走
``context.tasker.controller``（post_screencap / post_click），不自行调用 adb，
因此控制器兼容性、坐标缩放、以及任务停止都由框架负责。

参数（``custom_action_param``，JSON 字符串，均可省略）：
    {"max_games": 5, "max_rounds": 60, "after": "restart", "dry_run": false,
     "target": null, "remaining": [5, 5, 5, 3]}

说明：
- 目标牌按顶部图标色相自动识别（A/B/C），也可用 ``target`` 显式指定；
- ``remaining`` 为各花色剩余数初值（A/B/C/W），用于超几何概率；
- ``after=restart`` 打完一局自动点「再次挑战」继续；``exit`` 打到设定局数即退。
"""
from __future__ import annotations

import time
from math import comb
from typing import Any

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils.logger import logger
from utils.params import coerce_like, parse_params

# ---------------- 720p 基准坐标 ----------------
BASE_W, BASE_H = 1280, 720

HAND_BAND = (253, 880, 370, 443)        # x0, x1, y0, y1
CLAIM_BAND = (400, 813, 167, 333)
TARGET_ICON = (799, 835, 47, 97)
START_BTN = (847, 1133, 487, 567)
START_PT = (967, 553)
TRUST_PT = (400, 477)
DOUBT_PT = (720, 480)
CONFIRM_PT = (1003, 577)
RESTART_PT = (633, 630)
EXIT_PT = (480, 630)
CARD_DX, CARD_DY = -27, 13

# 按钮判定框（720p）
TRUST_BOX = (303, 510, 453, 513)
DOUBT_BOX = (583, 780, 453, 513)
CONFIRM_BOX = (867, 1140, 513, 580)

# 金色像素阈值（720p 口径）
BTN_GOLD_MIN = 90
CARD_GOLD_MIN = 133

HUE_RANGES = {"A": (12, 45), "B": (185, 235), "C": (75, 140), "W": (275, 345)}


# ---------------- 视觉 ----------------
def to_hsv(img: np.ndarray):
    a = img.astype(np.float32) / 255.0
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    diff = mx - mn + 1e-6
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    h = np.zeros_like(mx)
    m = (mx == r)
    h[m] = ((g[m] - b[m]) / diff[m]) % 6
    m = (mx == g)
    h[m] = (b[m] - r[m]) / diff[m] + 2
    m = (mx == b)
    h[m] = (r[m] - g[m]) / diff[m] + 4
    return (h * 60) % 360, diff / (mx + 1e-6), mx


def _card_mask(img: np.ndarray, box: tuple[int, int, int, int]):
    x0, x1, y0, y1 = box
    h, s, v = to_hsv(img[y0:y1, x0:x1])
    m = np.zeros(h.shape, dtype=bool)
    for lo, hi in HUE_RANGES.values():
        m |= (h >= lo) & (h <= hi)
    return m & (s > 0.15) & (v > 0.18) & (v < 0.95)


def find_cards(img: np.ndarray, band: tuple[int, int, int, int], min_width: int = 37):
    """在 band 内按色相列扫描切出手牌/对方声称的卡，逐张判型。"""
    x0, x1, y0, y1 = band
    m = _card_mask(img, band)
    col = m.sum(axis=0)
    if col.max() == 0:
        return []
    thr = max(4, col.max() * 0.22)
    runs, start = [], None
    for i, v in enumerate(col):
        if v > thr and start is None:
            start = i
        elif v <= thr and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(col)))
    runs = [r for r in runs if r[1] - r[0] >= min_width]

    h, s, _ = to_hsv(img[y0:y1, x0:x1])
    out = []
    for idx, (a, b) in enumerate(runs, 1):
        cnt = {name: int(((h[:, a:b] >= lo) & (h[:, a:b] <= hi) & (s[:, a:b] > 0.15)).sum())
               for name, (lo, hi) in HUE_RANGES.items()}
        tot = sum(cnt.values()) or 1
        best = max(cnt.items(), key=lambda kv: kv[1])[0]
        out.append({"index": idx, "box": (x0 + a, x0 + b, y0, y1),
                    "type": best, "conf": round(cnt[best] / tot, 3)})
    return out


def gold_pixels(img: np.ndarray, box: tuple[int, int, int, int], pad: int = 12) -> int:
    x0, x1, y0, y1 = box
    reg = img[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
    return int(((reg[:, :, 0] > 190) & (reg[:, :, 1] > 150) & (reg[:, :, 2] < 150)).sum())


def detect_target(img: np.ndarray, fallback: str = "B") -> str:
    x0, x1, y0, y1 = TARGET_ICON
    h, s, v = to_hsv(img[y0:y1, x0:x1])
    mask = (s > 0.2) & (v > 0.3)
    if mask.sum() < 18:
        return fallback
    hs = h[mask]
    centers = {"A": 25, "B": 205, "C": 100}
    best, bestd = fallback, 1e9
    for name, c in centers.items():
        d = float(np.abs((hs - c + 180) % 360 - 180).mean())
        if d < bestd:
            best, bestd = name, d
    return best


def detect(img: np.ndarray) -> dict[str, Any]:
    hand = find_cards(img, HAND_BAND)
    claimed = find_cards(img, CLAIM_BAND, 53)

    def gold_in(box: tuple[int, int, int, int]) -> int:
        x0, x1, y0, y1 = box
        reg = img[y0:y1, x0:x1]
        return int(((reg[:, :, 0] > 190) & (reg[:, :, 1] > 150) & (reg[:, :, 2] < 150)).sum())

    has_trust = gold_in(TRUST_BOX) > BTN_GOLD_MIN
    has_doubt = gold_in(DOUBT_BOX) > BTN_GOLD_MIN
    has_confirm = gold_in(CONFIRM_BOX) > 200
    dark = float((img.mean(axis=2) < 70).mean())

    sx0, sx1, sy0, sy1 = START_BTN
    start_reg = img[sy0:sy1, sx0:sx1]
    start_gold = int(((start_reg[:, :, 0] > 170) & (start_reg[:, :, 1] > 140) & (start_reg[:, :, 2] < 200)).sum())
    has_start = start_gold > 1200

    bx0, bx1, by0, by1 = (150, 1130, 420, 505)
    breg = img[by0:by1, bx0:bx1]
    br, bg, bb = breg[:, :, 0], breg[:, :, 1], breg[:, :, 2]
    banner = float((((br > 115) & (br > bg + 35) & (br > bb + 35)) |
                    ((br > 150) & (bg > 120) & (bb < 110))).mean())

    if dark > 0.5 and len(hand) <= 1 and banner < 0.25:
        state = "gameover"
    elif banner > 0.25:
        state = "reveal"
    elif has_trust and has_doubt:
        state = "adjudicate"
    elif (has_confirm and len(hand) >= 2) or len(hand) >= 5:
        state = "claim"
    elif has_start:
        state = "start"
    else:
        state = "other"
    return {"state": state, "hand": hand, "claimed": claimed,
            "trust_btn": has_trust, "doubt_btn": has_doubt,
            "confirm_btn": has_confirm, "start_btn": has_start, "banner": round(banner, 2)}


# ---------------- 策略 ----------------
class Observed:
    # 先验来自实机对局（对手信任 6:1、诚实 7:2）。在线更新后应替换为累计值。
    trust_true = 6
    trust_false = 1
    claim_true = 7
    claim_false = 2

    @property
    def trust_rate(self):
        return self.trust_true / (self.trust_true + self.trust_false)

    @property
    def truth_rate(self):
        return self.claim_true / (self.claim_true + self.claim_false)


OBS = Observed()


def p_at_least(deck: int, good: int, draw: int, k: int) -> float:
    if k > draw or k > good or draw > deck:
        return 0.0
    return sum(comb(good, i) * comb(deck - good, draw - i)
               for i in range(k, min(draw, good) + 1)) / comb(deck, draw)


def p_claim_true(n: int, remaining: dict[str, int], target: str) -> float:
    good = remaining.get(target, 0) + remaining.get("W", 0)
    deck = max(sum(remaining.values()), 18)
    return p_at_least(deck, good, 6, n) * OBS.truth_rate


def plan_claim(hand: list[dict[str, Any]], target: str):
    types = [c["type"] for c in hand]
    good = [i for i, t in enumerate(types) if t == target or t == "W"]
    bad = [i for i, t in enumerate(types) if t not in (target, "W")]
    if OBS.trust_rate >= 0.5 and bad and good:
        return [good[0], bad[0]], {"mode": "bluff", "n": 2}
    picks = good[:min(3, len(good))] or bad[:2]
    return picks, {"mode": "honest", "n": len(picks)}


# ---------------- 动作 ----------------
@AgentServer.custom_action("ZhapianAutoPlay")
class ZhapianAutoPlay(CustomAction):
    """魔精诈唬牌：读牌 + 出牌决策 + 判定信任/质疑 + 自动开下一局。"""

    def _shot(self, context: Context) -> np.ndarray:
        frame = context.tasker.controller.post_screencap().wait().get()
        # 控制器给的是 BGR；统一转 RGB 供 to_hsv 使用
        return np.ascontiguousarray(frame[:, :, ::-1])

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        params = parse_params(argv.custom_action_param)

        max_games = int(coerce_like(params.get("max_games", 5), 5, "max_games"))
        max_rounds = int(coerce_like(params.get("max_rounds", 60), 60, "max_rounds"))
        after = str(coerce_like(params.get("after", "restart"), "restart", "after"))
        dry_run = bool(coerce_like(params.get("dry_run", False), False, "dry_run"))

        target = params.get("target")
        if target not in (None, "A", "B", "C"):
            logger.warning(f"[zhapian] target={target!r} 非法，改为自动识别")
            target = None

        raw_rem = params.get("remaining", [5, 5, 5, 3])
        try:
            remaining = {"A": int(raw_rem[0]), "B": int(raw_rem[1]),
                         "C": int(raw_rem[2]), "W": int(raw_rem[3])}
        except Exception:
            logger.warning(f"[zhapian] remaining={raw_rem!r} 非法，用默认 [5,5,5,3]")
            remaining = {"A": 5, "B": 5, "C": 5, "W": 3}

        def click(x: int, y: int) -> None:
            if dry_run:
                logger.info(f"[dry] click ({x}, {y})")
                return
            context.tasker.controller.post_click(x, y).wait()

        def wait_state_not(states: set[str], timeout: float = 6.0) -> dict[str, Any] | None:
            end = time.time() + timeout
            while time.time() < end:
                st2 = detect(self._shot(context))
                if st2["state"] not in states:
                    return st2
                time.sleep(1.0)
            return None

        games = 0
        while True:
            if max_games and games >= max_games:
                click(*EXIT_PT)
                logger.info("[zhapian] 达到设定局数，退出")
                return CustomAction.RunResult(success=True)

            game_rounds = 0
            others = 0
            while True:
                if max_rounds and game_rounds >= max_rounds:
                    logger.warning(f"[zhapian] 单局回合数超过 {max_rounds}，退出")
                    return CustomAction.RunResult(success=False)
                game_rounds += 1

                img = self._shot(context)
                st = detect(img)
                n_hand = len(st["hand"])
                logger.info(f"[zhapian] 第{games + 1}局 第{game_rounds}轮 "
                            f"state={st['state']} hand={[c['type'] for c in st['hand']]}")

                if st["state"] == "claim" and n_hand >= 2:
                    others = 0
                    tgt = target or detect_target(img)
                    picks, info = plan_claim(st["hand"], tgt)
                    logger.info(f"[zhapian] claim {info} picks={picks} target={tgt}")
                    selected = 0
                    for i in picks:
                        if i < len(st["hand"]):
                            if self._select_card(context, st["hand"][i]["box"]):
                                selected += 1
                    if selected == 0:
                        logger.warning("[zhapian] 选牌全部失败，本轮不点确认")
                    else:
                        click(*CONFIRM_PT)
                        if not wait_state_not({"claim"}, 6):
                            logger.warning("[zhapian] 确认出牌后画面未推进，补点一次")
                            click(*CONFIRM_PT)
                    continue

                if st["state"] == "adjudicate":
                    others = 0
                    if st["trust_btn"] and st["doubt_btn"]:
                        n = max(2, len(st["claimed"]))
                        tgt = target or detect_target(img)
                        p = p_claim_true(n, remaining, tgt)
                        decision = "trust" if p >= 0.5 else "doubt"
                        logger.info(f"[zhapian] judge n={n} p_true={p:.2f} -> {decision}")
                        click(*(TRUST_PT if decision == "trust" else DOUBT_PT))
                        if not wait_state_not({"adjudicate"}, 6):
                            logger.warning("[zhapian] 判定点击后画面未推进，补点一次")
                            click(*(TRUST_PT if decision == "trust" else DOUBT_PT))
                    else:
                        # 声称牌没识别到，但信任/质疑按钮在，按保守怀疑打
                        logger.info("[zhapian] 声称牌未识别，按保守怀疑")
                        click(*DOUBT_PT)
                    continue

                if st["state"] == "reveal":
                    others = 0
                    continue

                if st["state"] == "start":
                    others = 0
                    logger.info("[zhapian] 在开始页面，点开始游戏")
                    click(*START_PT)
                    continue

                if st["state"] == "gameover":
                    others = 0
                    games += 1
                    limit = f"/{max_games}" if max_games else "/∞"
                    logger.info(f"[zhapian] 第 {games}{limit} 局结束")
                    if after != "restart" or (max_games and games >= max_games):
                        click(*EXIT_PT)
                        return CustomAction.RunResult(success=True)
                    click(*RESTART_PT)
                    continue

                # other：未知画面，不做任何盲目点击，等下一次识别
                others += 1
                if others >= 15:
                    logger.error("[zhapian] 连续 15 轮未识别到目标界面，结束任务")
                    return CustomAction.RunResult(success=False)
                time.sleep(1.5)

    def _select_card(self, context: Context, box: tuple[int, int, int, int]) -> bool:
        cx = int((box[0] + box[1]) / 2) + CARD_DX
        cy = int((box[2] + box[3]) / 2) + CARD_DY
        for dx, dy in ((0, 0), (0, 8), (0, -8), (12, 0), (-12, 0)):
            context.tasker.controller.post_click(cx + dx, cy + dy).wait()
            time.sleep(0.45)
            if gold_pixels(self._shot(context), box) > CARD_GOLD_MIN:
                return True
        return False
