"""魔精诈唬牌 · M9A 自定义动作

坐标约定：全部以 MaaFW 的 **720p（1280x720）为基准**，运行时按截图宽度自动换算
（MuMu 编码流常见 1280x720，逻辑 1920x1080）。

用法（M9A 任务「魔精诈唬牌（自动）」），参数均可省略：
    {"max_rounds": 20, "max_games": 1, "after": "exit", "dry_run": false}

说明：
- 目标牌自动按顶部图标色相识别（A/B/C），无需手填；
- 剩余牌数暂无 OCR，用初始值估算，不影响主要策略；
- MuMu 失焦会丢弃合成点击，点击前会自动把模拟器窗口置前。
"""
from __future__ import annotations

import time
from math import comb

import numpy as np
from PIL import Image

try:  # M9A agent 环境
    from maa.agent.agent_server import AgentServer
    from maa.context import Context
    from maa.custom_action import CustomAction
    from utils import logger
except Exception:  # 独立自测
    AgentServer = None
    Context = None
    CustomAction = object

    class _L:
        @staticmethod
        def info(*a, **k): print(*a)

        @staticmethod
        def warning(*a, **k): print(*a)

        @staticmethod
        def error(*a, **k): print(*a)

    logger = _L()

# ---------------- 720p 基准坐标 ----------------
BASE_W, BASE_H = 1280, 720

HAND_BAND = (253, 880, 370, 443)        # x0,x1,y0,y1
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

# 按钮判定框（720p，用金色描边像素数判断，比平均色可靠）
TRUST_BOX = (303, 510, 453, 513)
DOUBT_BOX = (583, 780, 453, 513)
CONFIRM_BOX = (867, 1140, 513, 580)

# 阈值（720p 像素口径，运行时 ×k²）
START_GOLD_MIN = 1200
BTN_GOLD_MIN = 90
CARD_GOLD_MIN = 133

HUE_RANGES = {"A": (12, 45), "B": (185, 235), "C": (75, 140), "W": (275, 345)}


# ---------------- 基础 ----------------
def to_hsv(img: np.ndarray):
    a = img.astype(np.float32) / 255.0
    mx = a.max(axis=2); mn = a.min(axis=2)
    diff = mx - mn + 1e-6
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    h = np.zeros_like(mx)
    m = (mx == r); h[m] = ((g[m] - b[m]) / diff[m]) % 6
    m = (mx == g); h[m] = (b[m] - r[m]) / diff[m] + 2
    m = (mx == b); h[m] = (r[m] - g[m]) / diff[m] + 4
    return (h * 60) % 360, diff / (mx + 1e-6), mx


def scale_of(img: np.ndarray) -> float:
    return img.shape[1] / BASE_W


def px(box, k):
    x0, x1, y0, y1 = box
    return int(x0 * k), int(x1 * k), int(y0 * k), int(y1 * k)


def pt(p, k):
    return int(p[0] * k), int(p[1] * k)


def _card_mask(img, box720, k):
    x0, x1, y0, y1 = px(box720, k)
    h, s, v = to_hsv(img[y0:y1, x0:x1])
    m = np.zeros(h.shape, dtype=bool)
    for lo, hi in HUE_RANGES.values():
        m |= (h >= lo) & (h <= hi)
    return m & (s > 0.15) & (v > 0.18) & (v < 0.95)


def find_cards(img, band720=HAND_BAND, min_width_720=37):
    k = scale_of(img)
    x0, x1, y0, y1 = px(band720, k)
    m = _card_mask(img, band720, k)
    col = m.sum(axis=0)
    if col.max() == 0:
        return []
    thr = max(4, col.max() * 0.22)
    runs, start = [], None
    for i, v in enumerate(col):
        if v > thr and start is None:
            start = i
        elif v <= thr and start is not None:
            runs.append((start, i)); start = None
    if start is not None:
        runs.append((start, len(col)))
    min_w = int(min_width_720 * k)
    runs = [r for r in runs if r[1] - r[0] >= min_w]

    h, s, _ = to_hsv(img[y0:y1, x0:x1])
    out = []
    for idx, (a, b) in enumerate(runs, 1):
        cnt = {name: int(((h[:, a:b] >= lo) & (h[:, a:b] <= hi) & (s[:, a:b] > 0.15)).sum())
               for name, (lo, hi) in HUE_RANGES.items()}
        tot = sum(cnt.values()) or 1
        best = max(cnt, key=cnt.get)
        out.append({"index": idx, "box": (x0 + a, x0 + b, y0, y1),
                    "type": best, "conf": round(cnt[best] / tot, 3)})
    return out


def gold_pixels(img, box, pad_720=12):
    k = scale_of(img)
    x0, x1, y0, y1 = box
    p = int(pad_720 * k)
    reg = img[max(0, y0 - p):y1 + p, max(0, x0 - p):x1 + p]
    return int(((reg[:, :, 0] > 190) & (reg[:, :, 1] > 150) & (reg[:, :, 2] < 150)).sum())


def detect_target(img, fallback="B"):
    k = scale_of(img)
    x0, x1, y0, y1 = px(TARGET_ICON, k)
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


def detect(img):
    k = scale_of(img)
    hand = find_cards(img, HAND_BAND)
    claimed = find_cards(img, CLAIM_BAND, 53)

    def gold_in(box720):
        x0, x1, y0, y1 = px(box720, k)
        reg = img[y0:y1, x0:x1]
        return int(((reg[:, :, 0] > 190) & (reg[:, :, 1] > 150) & (reg[:, :, 2] < 150)).sum())

    btn_thr = int(BTN_GOLD_MIN * k * k)
    has_trust = gold_in(TRUST_BOX) > btn_thr
    has_doubt = gold_in(DOUBT_BOX) > btn_thr
    has_confirm = gold_in(CONFIRM_BOX) > int(200 * k * k)
    dark = float((img.mean(axis=2) < 70).mean())

    sx0, sx1, sy0, sy1 = px(START_BTN, k)
    start_reg = img[sy0:sy1, sx0:sx1]
    start_gold = int(((start_reg[:, :, 0] > 170) & (start_reg[:, :, 1] > 140) & (start_reg[:, :, 2] < 200)).sum())
    has_start = start_gold > int(START_GOLD_MIN * k * k)

    if dark > 0.5 and len(hand) <= 1:
        state = "gameover"
    elif has_trust and has_doubt:
        state = "adjudicate"
    elif (has_confirm and len(hand) >= 2) or len(hand) >= 5:
        state = "claim"
    elif has_start:
        state = "start"
    else:
        state = "other"
    return {"state": state, "hand": hand, "claimed": claimed,
            "trust_btn": bool(has_trust), "doubt_btn": bool(has_doubt),
            "confirm_btn": bool(has_confirm), "start_btn": has_start}


# ---------------- 策略 ----------------
class Observed:
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


def p_at_least(deck, good, draw, k):
    if k > draw or k > good or draw > deck:
        return 0.0
    return sum(comb(good, i) * comb(deck - good, draw - i) for i in range(k, min(draw, good) + 1)) / comb(deck, draw)


def p_claim_true(n, remaining, target):
    good = remaining.get(target, 0) + remaining.get("W", 0)
    deck = max(sum(remaining.values()), 18)
    return p_at_least(deck, good, 6, n) * OBS.truth_rate


def plan_claim(hand, target):
    types = [c["type"] for c in hand]
    good = [i for i, t in enumerate(types) if t == target or t == "W"]
    bad = [i for i, t in enumerate(types) if t not in (target, "W")]
    if OBS.trust_rate >= 0.5 and bad and good:
        return [good[0], bad[0]], {"mode": "bluff", "n": 2}
    picks = good[:min(3, len(good))] or bad[:2]
    return picks, {"mode": "honest", "n": len(picks)}


# ---------------- adb（M9A 控制器点击对 MuMu 不生效） ----------------
ADB_PATH = r"C:\Program Files\Netease\MuMu\nx_main\adb.exe"
ADB_DEV = "127.0.0.1:16384"


def adb_shot():
    import subprocess, os, tempfile
    tmp = os.path.join(tempfile.gettempdir(), "zhapian_shot.png")
    subprocess.run([ADB_PATH, "-s", ADB_DEV, "shell", "screencap", "-p", "/sdcard/zp.png"],
                   capture_output=True)
    subprocess.run([ADB_PATH, "-s", ADB_DEV, "pull", "/sdcard/zp.png", tmp], capture_output=True)
    return np.asarray(Image.open(tmp).convert("RGB")).astype(np.int16)


def focus_mumu():
    """MuMu 失焦会丢弃合成点击，点击前按进程名置前。"""
    try:
        import ctypes, ctypes.wintypes as wt, subprocess
        u = ctypes.windll.user32
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MuMuNxDevice.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="ignore").stdout
        pids = {int(x.split('","')[1]) for x in out.strip().splitlines() if '","' in x}
        if not pids:
            return False
        wins = []
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

        def cb(hwnd, _):
            pid = wt.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and u.IsWindowVisible(hwnd):
                wins.append(hwnd)
            return True

        u.EnumWindows(CB(cb), 0)
        for h in wins:
            u.ShowWindow(h, 9)
            u.SetForegroundWindow(h)
        return bool(wins)
    except Exception:
        return False


def adb_click(x, y):
    import subprocess
    focus_mumu()
    subprocess.run([ADB_PATH, "-s", ADB_DEV, "shell", "input", "tap", str(int(x)), str(int(y))],
                   capture_output=True)


GAME_PKG = "com.shenlan.m.reverse1999"


def adb_shell(args, timeout=25):
    import subprocess
    try:
        r = subprocess.run([ADB_PATH, "-s", ADB_DEV, "shell"] + list(args),
                           capture_output=True, text=True, errors="ignore", timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"<adb error: {e}>"


def _current_focus():
    out = adb_shell(["dumpsys", "window"])
    for line in out.splitlines():
        if "mCurrentFocus" in line:
            return line.strip()
    return ""


def ensure_env():
    """启动前体检：设备在线 / 游戏在前台 / M9A 存活。返回可读的状态 dict。"""
    import subprocess
    info = {}
    try:
        info["m9a"] = "alive" if subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq m9a.exe", "/NH"],
            capture_output=True, text=True, errors="ignore").stdout.lower().count("m9a.exe") else "missing"
    except Exception:
        info["m9a"] = "unknown"

    boot = adb_shell(["getprop", "sys.boot_completed"]).strip()
    if boot.splitlines()[-1:] != ["1"]:
        subprocess.run([ADB_PATH, "connect", ADB_DEV], capture_output=True)
        time.sleep(3)
        boot = adb_shell(["getprop", "sys.boot_completed"]).strip()
    info["boot"] = boot.splitlines()[-1] if boot.strip() else "?"

    focus = _current_focus()
    if GAME_PKG not in focus:
        logger.warning(f"[zhapian] 游戏不在前台（{focus or '未知'}），尝试拉起")
        adb_shell(["monkey", "-p", GAME_PKG, "-c", "android.intent.category.LAUNCHER", "1"], timeout=30)
        time.sleep(12)
        focus = _current_focus()
        info["launched"] = True
    info["focus"] = focus
    return info


# ---------------- 动作 ----------------
if AgentServer is not None:
    @AgentServer.custom_action("ZhapianAutoPlay")
    class ZhapianAutoPlay(CustomAction):
        def run(self, context: Context, argv) -> "CustomAction.RunResult":
            params = {}
            try:
                raw = getattr(argv, "custom_action_param", None)
                if isinstance(raw, dict):
                    params = raw
            except Exception:
                pass
            max_rounds = int(params.get("max_rounds", 60))   # 单局最多回合
            max_games = int(params.get("max_games", 5))      # 总局数，0 = 无限
            after = params.get("after", "restart")
            dry = bool(params.get("dry_run", False))
            raw_rem = params.get("remaining") or [5, 5, 5, 3]
            if isinstance(raw_rem, (list, tuple)) and len(raw_rem) == 4:
                remaining = {"A": int(raw_rem[0]), "B": int(raw_rem[1]),
                             "C": int(raw_rem[2]), "W": int(raw_rem[3])}
            elif isinstance(raw_rem, dict):
                remaining = raw_rem
            else:
                remaining = {"A": 5, "B": 5, "C": 5, "W": 3}

            def shot():
                return adb_shot()

            def click(p720, k):
                x, y = pt(p720, k)
                if dry:
                    logger.info(f"[dry] click {p720} -> ({x},{y})")
                    return
                adb_click(x, y)
                time.sleep(0.5)

            def select_card(img, box, k):
                cx = int((box[0] + box[1]) / 2) + int(CARD_DX * k)
                cy = int((box[2] + box[3]) / 2) + int(CARD_DY * k)
                for dx, dy in ((0, 0), (0, int(8 * k)), (0, -int(8 * k)),
                               (int(12 * k), 0), (-int(12 * k), 0)):
                    adb_click(cx + dx, cy + dy)
                    time.sleep(0.45)
                    if gold_pixels(shot(), box) > int(CARD_GOLD_MIN * k * k):
                        return True
                return False

            def wait_state(want, timeout=25.0, label=""):
                """轮询到期望状态；超时返回 None。"""
                end = time.time() + timeout
                last = None
                while time.time() < end:
                    img2 = shot()
                    st2 = detect(img2)
                    last = st2["state"]
                    if last in want:
                        return st2
                    time.sleep(1.2)
                logger.warning(f"[zhapian] 等待 {sorted(want)} 超时（{label}），最后={last}")
                return None

            def restart_round(k):
                """一局结束后开下一局：先点「再次挑战」，不行就退出重进。"""
                click(RESTART_PT, k)
                st2 = wait_state({"claim", "adjudicate"}, 20, "再次挑战")
                if st2:
                    return st2
                logger.warning("[zhapian] 再次挑战未进对局，改为退出重进")
                click(EXIT_PT, k)
                time.sleep(2)
                if wait_state({"start"}, 12, "退出回活动页"):
                    click(START_PT, k)
                    time.sleep(5)
                return wait_state({"claim", "adjudicate"}, 25, "重新开始")

            # ---- 启动前体检：设备 / 游戏前台 / M9A ----
            env = ensure_env()
            logger.info(f"[zhapian] 环境 {env}")

            # 如果上次停在结算页，先退出回活动页
            st0 = wait_state({"claim", "adjudicate", "start", "gameover"}, 8, "初始画面")
            if st0 and st0["state"] == "gameover":
                logger.info("[zhapian] 初始就在结算页，先退出")
                k0 = scale_of(shot())
                click(EXIT_PT, k0)
                time.sleep(2)
                if wait_state({"start"}, 12, "回活动页"):
                    click(START_PT, scale_of(shot()))
                    time.sleep(5)

            games = 0
            while True:
                game_rounds = 0
                others = 0
                while True:
                    if max_rounds and game_rounds >= max_rounds:
                        logger.warning(f"[zhapian] 单局回合数超过 {max_rounds}，退出")
                        click(EXIT_PT, scale_of(shot()))
                        return CustomAction.RunResult(success=False)
                    game_rounds += 1

                    img = shot()
                    k = scale_of(img)
                    st = detect(img)
                    n_hand = len(st["hand"])
                    logger.info(f"[zhapian] 第{games + 1}局 第{game_rounds}轮 "
                                f"state={st['state']} hand={[c['type'] for c in st['hand']]}")

                    if st["state"] == "claim" and n_hand >= 2:
                        others = 0
                        target = params.get("target") or detect_target(img)
                        picks, info = plan_claim(st["hand"], target)
                        logger.info(f"[zhapian] claim {info} picks={picks} target={target}")
                        for i in picks:
                            if i < len(st["hand"]):
                                select_card(img, st["hand"][i]["box"], k)
                                time.sleep(0.3)
                        click(CONFIRM_PT, k)
                        time.sleep(3)

                    elif st["state"] == "adjudicate" and len(st["claimed"]) >= 1:
                        others = 0
                        n = max(2, len(st["claimed"]))
                        target = params.get("target") or detect_target(img)
                        p = p_claim_true(n, remaining, target)
                        decision = "trust" if p >= 0.5 else "doubt"
                        logger.info(f"[zhapian] judge n={n} p_true={p:.2f} -> {decision}")
                        click(TRUST_PT if decision == "trust" else DOUBT_PT, k)
                        time.sleep(3)

                    elif st["state"] == "start":
                        others = 0
                        logger.info("[zhapian] 在开始页面，点开始游戏")
                        click(START_PT, k)
                        time.sleep(6)

                    elif st["state"] == "gameover":
                        others = 0
                        games += 1
                        limit = f"/{max_games}" if max_games else "/∞"
                        logger.info(f"[zhapian] 第 {games}{limit} 局结束")
                        if after != "restart" or (max_games and games >= max_games):
                            click(EXIT_PT, k)
                            logger.info("[zhapian] 达到设定局数，退出")
                            return CustomAction.RunResult(success=True)
                        nxt = restart_round(k)
                        if not nxt:
                            logger.error("[zhapian] 重开下一局失败，结束任务")
                            click(EXIT_PT, k)
                            return CustomAction.RunResult(success=False)
                        logger.info("[zhapian] 已进入下一局")
                        break

                    else:
                        others += 1
                        if others in (10, 20):
                            logger.warning(f"[zhapian] 连续 {others} 次未识别画面，尝试置前/重进")
                            focus_mumu()
                            if others == 20:
                                click(EXIT_PT, k)
                                time.sleep(2)
                                click(START_PT, k)
                                time.sleep(5)
                        if others >= 30:
                            logger.error("[zhapian] 长时间无法识别画面，结束任务")
                            return CustomAction.RunResult(success=False)
                        time.sleep(1.5)


# ---------------- 独立自测 ----------------
def _selftest(frames=3):
    import os
    os.environ.setdefault("MAAFW_BINARY_PATH",
                          r"C:\Users\35771\Downloads\M9A-win-x86_64-v4.5.3\runtimes\win-x64\native")
    for i in range(frames):
        img = adb_shot()
        st = detect(img)
        logger.info(f"frame{i}: state={st['state']} hand={[c['type'] for c in st['hand']]} "
                    f"claimed={len(st['claimed'])} target={detect_target(img)}")
        time.sleep(1.5)


if __name__ == "__main__":
    _selftest()


