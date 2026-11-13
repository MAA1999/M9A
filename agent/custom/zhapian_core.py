"""魔精诈唬牌 · 共享视觉与策略。

坐标约定：MaaFW **720p（1280x720）基准**。本模块不 import MaaFW，只做纯像素与
概率计算，供 ``custom.reco.zhapian``（状态识别）与 ``custom.action.zhapian_auto``
（出牌/判定决策）复用。

输入图像约定为 **RGB**（调用方把控制器的 BGR 帧转好再传）。
"""
from __future__ import annotations

from math import comb
from typing import Any

import numpy as np

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

TRUST_BOX = (303, 510, 453, 513)
DOUBT_BOX = (583, 780, 453, 513)
CONFIRM_BOX = (867, 1140, 513, 580)

BTN_GOLD_MIN = 90
CARD_GOLD_MIN = 133

HUE_RANGES = {"A": (12, 45), "B": (185, 235), "C": (75, 140), "W": (275, 345)}


def to_hsv(img: np.ndarray):
    a = img.astype(np.float32) / 255.0
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    diff = mx - mn + 1e-6
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    h = np.zeros_like(mx)
    m = mx == r
    h[m] = ((g[m] - b[m]) / diff[m]) % 6
    m = mx == g
    h[m] = (b[m] - r[m]) / diff[m] + 2
    m = mx == b
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
