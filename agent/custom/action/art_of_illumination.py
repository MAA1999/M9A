"""光影栖身处 · 刮刮卡：每一轮扫出还没翻开的格子，**随机**挑一个点掉。

**等待与关页由 pipeline 节点承担，本模块不睡死时钟。** 一轮的完整链路是：

    AOI_FlipRound（页面标识 + 本动作：判断该不该继续、点一个未开格）
        └─next→ AOI_ObtainedAwards（识别「获得物品」全屏页 → Click 点掉）
                    └─next→ AOI_FlipRound（接着翻下一格）

翻牌后约 2.06~3.04s 出现「获得物品」页（实测），由 `AOI_FlipRound` 的 `timeout` 兜住这段
等待：页面出现即被 `AOI_ObtainedAwards` 认掉并点掉；**等不到就说明这一下没翻成——也就是
可折射次数已用完**，由 `AOI_FlipRound` 的 `on_error` 走到收尾节点，正常结束。
所以本模块只做两件事：**判断该不该点、点哪里**；该改流向时用 `override_next` 把本节点的
next 覆写成翻页或收尾节点，让引擎走正常流转，而不是靠超时收场。

**`override_next` 写的是持久补丁，不是一次性的**：它把节点当前定义物化后存进本任务的
`Context::pipeline_override_`，此后每次取该节点的定义都优先命中这份补丁，直到任务结束
（框架 5.14.3：`Context::override_next` → `pipeline_override_.insert_or_assign`，
`get_pipeline_data` 查补丁优先；引擎每轮命中节点后也是拿这份补丁读 `next`）。
所以**每条分支都要显式重设 next**，包括照常点击那条（重设回 `ROUND_NEXT`）：只在翻页/收尾
分支写的话，翻过一次页之后 `AOI_FlipRound.next` 就永久停在 `AOI_PageSwitch` —— 之后每次点击
都不再去 `AOI_ObtainedAwards`（引擎不再等、也不再点掉「获得物品」页，而是立刻又去翻页），
两种详情面板的兜底同时失效，剩下的折射次数白白扔掉。

判据（全部真机实测）：

- 格子板是 6×6=36 个槽位。槽位中心即 `COL_X` / `ROW_Y`（列距 ~91.3、行距 ~88.5）；
  1280×720 控制器分辨率空间，与项目 `display_short_side` 一致。
  **两幕布共用这一套坐标**：把 36 个格心框叠在同一帧上，幕布 I / II 的框都正落格内（实测）。
- **盖着的格子有呼吸/流光动画，已翻开的格子完全静止**：两帧的逐格帧间差（格心 68×64 的均值），
  已翻开的**恒为 0.00**，盖着的**随两帧间隔单调增长**（同一块棋盘 8 帧连拍实测，19 个未开格）：

  | 两帧间隔 | 未开格 最小/中位/最大 | 已翻开 最大 |
  | :--- | :--- | :--- |
  | 100ms | 0.40 / 0.41 / 0.42 | 0.00 |
  | 300ms | 3.28 / 3.45 / 3.59 | 0.00 |
  | 500ms | 7.93 / 8.49 / 8.86 | 0.00 |
  | 700ms | 22.77 / 24.83 / 25.30 | 0.00 |

  这条是「哪些格子还能翻」的唯一依据，不需要模板与 OCR。
  **结论是不能用固定阈值**：同一块棋盘，间隔从 100ms 变到 700ms，幅度差近两个数量级，
  任何固定阈值都会在某个间隔上失效。实测就踩过这一下——固定阈值 1.0 时，一次 **3.0**
  的瞬态（正对应 ~300ms 的间隔）被判成「未开」，于是点了已翻开的格子。
  判据改为**相对**的：未开格彼此幅度一致（19 格极差 < 10%）、已开格恒为 0，
  所以拿「最动的那格 × `MOTION_PEAK_FRACTION`」当分界，跨间隔自洽。
- 点盖着的格子 → 翻开并消耗 1 次折射；点已翻开的格子 → 弹**详情面板**（不消耗次数）。
  所以本模块永远只点扫描判为「未开」的格子；面板这一侧由 pipeline 的
  `AOI_PanelCloseItem` / `AOI_PanelCloseCollection` 兜底关掉（实测两种面板、两个 ✕ 位置），
  不至于卡在那里没有出口。
- **棋盘有两幕布（两页），翻页就是点棋盘左 / 右那个「>」**：幕布 I 时「>」在棋盘**右侧**（点它 →
  幕布 II），幕布 II 时「>」在棋盘**左侧**（点它 → 回幕布 I）。两页各是一块全新的 6×6、
  **共用同一个计数条**；两个「>」是两个不同尺寸的图形（85×96 / 59×93），识别矩阵互不误命中。
  幕布 II 由「获得大奖」解锁（游戏原文：*通过折射观测到大奖的任意一角即可获得大奖，
  获得大奖后解锁多格光影幕布 II*）——本模块**不判断解锁与否**，只按「本页翻完、计数条还有次数」
  推进；没得翻时 `AOI_PageSwitch` 的两个候选都认不到，等满它的 timeout 后由 on_error 收尾
  （保留这段宽限是有意的：候选只有一帧机会时，瞬时遮挡会静默少翻一页，详见该节点注释）。

终止条件（三层，都不依赖「次数用完时界面长什么样」这个未观测状态）：

1. 计数条读到 0 → 直接收尾（这一条**必须先查**，见下）；
2. 扫描到 0 个未开格 → **本页翻完了**：计数条还有次数就交给 `AOI_PageSwitch` 去翻另一幕布，
   没有次数才收尾；
3. 上面两条都不成立时照常点一格，由 pipeline 节点等「获得物品」页——**等不到就是次数用完**，
   走 `AOI_FlipRound` 的 `on_error` 收尾。

**「未开格数」只在还有折射次数时有效**：实测次数归零后，盖着格子的呼吸动画会停
（×0 那一轮用同一判据扫出「0 格未开」，而棋盘上其实还有 21 格没翻）。所以上面第 1 条
必须排在第 2 条之前，否则「次数用完」会被记成「已无未开格子」，把真实情况说错。
好在两条都通向同一个正常收尾，不影响行为，只影响日志说不说得对。

计数条（`COUNTER_ROI`）只作**优化与诊断**，不作为唯一依据：它的 ROI 是实测调出来的
（`[440,650,70,50]` 在 ×5/×4/×3/×2 四帧上分别读出 `×5^`/`X4`/`×3`/`X2`，score 0.77~0.80；
而更大或更小的 ROI 都只会挑出「射次数」那片文字、把数字整个漏掉）。读不到时**继续点击**，
由第 3 层兜底，绝不因为读不到就停。

本动作**无参数**（`custom_action_param` 留空）。
"""

import random
import re
import time

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.define import OCRResult
from maa.pipeline import JOCR, JRecognitionType
from utils import logger
from utils.maa_types import is_hit, results_as

__all__ = ["ArtOfIlluminationScratch"]

FINISH_NODE = "AOI_ScratchCardDone"
# 本页翻完、但计数条还有次数时交给它：去点棋盘的翻页「>」翻到另一幕布（多格光影幕布 I / II）
SWITCH_NODE = "AOI_PageSwitch"
# `AOI_FlipRound` 在 pipeline 里的出口三选一（正常翻牌弹「获得物品」页；误点已翻开的格子弹两种
# 详情面板，各有一个关闭节点）。这是 JSON 那份列表的**副本**：补丁是持久的，所以点击分支每轮都
# 得把它显式盖回去，否则上一轮的翻页/收尾补丁会一直生效（见模块 docstring）。
# tests/test_art_of_illumination.py 有一条用例把这份副本与 JSON 钉在一起。
ROUND_NEXT: tuple[str, ...] = ("AOI_ObtainedAwards", "AOI_PanelCloseItem", "AOI_PanelCloseCollection")


@AgentServer.custom_action("ArtOfIlluminationScratch")
class ArtOfIlluminationScratch(CustomAction):
    """扫出未翻开的格子、**随机**点掉一个；每轮都重设本节点的 next（收尾 / 翻页 / 照常点击）。"""

    # ---- 实测几何（1280×720 控制器分辨率空间）：6×6 槽位中心 ----
    COL_X: tuple[int, ...] = (168, 261, 352, 444, 535, 626)
    ROW_Y: tuple[int, ...] = (162, 247, 336, 424, 512, 601)
    # 取格心一小块做判据，避开格线与相邻格的插画外溢
    PATCH_HALF_W: int = 34
    PATCH_HALF_H: int = 32

    # ---- 实测判据：已翻开的格子帧间差**恒为 0.00**；盖着的格子幅度随两帧间隔单调增长
    #      （见表：间隔 700ms 时未开格 22.77~25.30）。跨间隔都成立的绝对阈值不存在，故用相对判据。----
    # 未开格彼此幅度一致（19 格极差 < 10%），拿最动的那格当基准，取它的这个比例作分界。
    MOTION_PEAK_FRACTION: float = 0.25
    # 基准本身小于这个数就说明这一测不可信（两帧实际挨得太近、或画面根本没在渲染）
    MOTION_PEAK_FLOOR: float = 5.0
    # 扫描两帧的间隔（秒；700ms 实测未开格 ≥22.8）
    SCAN_GAP_S: float = 0.7
    # 基准过小时拉长到这个间隔重测一次（间隔越大幅度越大）
    SCAN_GAP_RETRY_S: float = 1.5

    # ---- 底部计数条：「×N」那一段（实测四帧均读对；ROI 放大或缩小都会漏掉数字）----
    COUNTER_ROI: tuple[int, int, int, int] = (440, 650, 70, 50)
    COUNTER_PATTERN: re.Pattern[str] = re.compile(r"[×xX]\s*(\d+)")
    COUNTER_TAIL_PATTERN: re.Pattern[str] = re.compile(r"(\d+)\s*$")

    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        node_name = str(getattr(argv, "node_name", "") or "")
        try:
            ok = self._round(context, node_name)
        except Exception:
            logger.exception(f"[ArtOfIllumination] {node_name} 扫描/点击过程中出现未预期异常")
            return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=ok)

    # ---------------------------------------------------------------- 基础操作

    @staticmethod
    def _grab(context: Context) -> np.ndarray:
        """取一帧新画面（走框架截图链路，与控制器同一分辨率空间）。"""
        return context.tasker.controller.post_screencap().wait().get()

    @classmethod
    def _patch(cls, img: np.ndarray, cx: int, cy: int) -> np.ndarray:
        """取某格中心的一小块像素。"""
        return img[
            cy - cls.PATCH_HALF_H : cy + cls.PATCH_HALF_H,
            cx - cls.PATCH_HALF_W : cx + cls.PATCH_HALF_W,
        ].astype(np.int32)

    @classmethod
    def _motion(cls, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """逐格帧间差（6×6）：盖着的格子有动画 → 远大于 0；已翻开的静止 → 0。"""
        out = np.zeros((len(cls.ROW_Y), len(cls.COL_X)), dtype=np.float64)
        for j, cy in enumerate(cls.ROW_Y):
            for i, cx in enumerate(cls.COL_X):
                out[j, i] = float(np.abs(cls._patch(a, cx, cy) - cls._patch(b, cx, cy)).mean())
        return out

    @classmethod
    def _scan(cls, context: Context, gap_s: float) -> tuple[np.ndarray, np.ndarray]:
        """抓两帧（相隔 gap_s），返回 (逐格帧间差, 后一帧)。"""
        first = cls._grab(context)
        time.sleep(gap_s)
        second = cls._grab(context)
        return cls._motion(first, second), second

    @classmethod
    def _unopened(cls, motion: np.ndarray) -> list[tuple[int, int, int, int]]:
        """按行优先返回未开格子 (行, 列, x, y)。

        这个**顺序只供阅读与日志**：实际翻哪一格由 `_pick` 随机决定，不是从头取第一个。

        判据是**相对**的：盖着的格子同一次扫描里幅度一致，已翻开的恒为 0，
        所以用「最动的那格 × `MOTION_PEAK_FRACTION`」当分界，而不是一个跨间隔都成立的绝对阈值。
        基准低于 `MOTION_PEAK_FLOOR` 时返回空——那说明这一测根本没采到动画（画面没在渲染、
        或格子全翻开了），此时「未开 0 格」是实话，不是漏判。
        """
        peak = float(motion.max())
        if peak < cls.MOTION_PEAK_FLOOR:
            return []
        cutoff = peak * cls.MOTION_PEAK_FRACTION
        cells: list[tuple[int, int, int, int]] = []
        for j, cy in enumerate(cls.ROW_Y):
            for i, cx in enumerate(cls.COL_X):
                if float(motion[j, i]) >= cutoff:
                    cells.append((j + 1, i + 1, cx, cy))
        return cells

    @staticmethod
    def _pick(cells: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        """在未开格里**随机**挑一个。

        不按行列顺序：机械地从左上角开始翻既没必要，也不像人在刮。随机不改变任何判据
        （盖着的格子彼此等价，见 `_unopened` 的幅度一致性），只是把「翻哪一格」分散开。
        """
        return random.choice(cells)

    @classmethod
    def _read_counter(cls, context: Context, img: np.ndarray) -> int | None:
        """读底部计数条的「可折射次数」。读不到返回 None，调用方按第 3 层兜底继续。"""
        detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(roi=cls.COUNTER_ROI, expected=[r"\d+"]),
            img,
        )
        if not is_hit(detail):
            return None
        text = "".join(str(result.text or "") for result in results_as(detail, OCRResult))
        match = cls.COUNTER_PATTERN.search(text) or cls.COUNTER_TAIL_PATTERN.search(text)
        return int(match.group(1)) if match is not None else None

    @staticmethod
    def _set_next(context: Context, node_name: str, targets: tuple[str, ...]) -> None:
        """把本节点的 next 覆写成 targets：由引擎走正常流转，而不是靠超时/异常。

        注意 `override_next` 写的是**持久补丁**（物化节点定义 → 存进本任务的 Context → 此后每次取
        节点定义都优先命中它，直到任务结束），不是一次性的，所以**本模块每条分支都要调**——尤其
        是照常点击那条，必须重设回 `ROUND_NEXT`。只在翻页/收尾分支调的话，翻过一次页之后本节点的
        next 就永久停在 `AOI_PageSwitch`：点击分支不再去 `AOI_ObtainedAwards`，引擎不再等也不再点
        掉「获得物品」页，两种详情面板的兜底同时失效。
        """
        if node_name:
            context.override_next(node_name, list(targets))

    @classmethod
    def _finish(cls, context: Context, node_name: str, target: str = FINISH_NODE) -> None:
        """收尾：把本节点的 next 覆写成收尾节点，由引擎走正常结束。"""
        cls._set_next(context, node_name, (target,))

    # ---------------------------------------------------------------- 本轮决策

    @classmethod
    def _round(cls, context: Context, node_name: str) -> bool:
        motion, frame = cls._scan(context, cls.SCAN_GAP_S)
        # 基准过小 → 这一测的两帧实际可能挨得太近（截图链路有延迟），拉长间隔重测一次再说。
        # 这条只在文件日志里（控制台是 INFO），正常跑看不到。
        if float(motion.max()) < cls.MOTION_PEAK_FLOOR:
            logger.debug(
                f"[ArtOfIllumination] {node_name} 帧间差峰值仅 {float(motion.max()):.2f}"
                f"（< {cls.MOTION_PEAK_FLOOR}），把两帧间隔拉到 {cls.SCAN_GAP_RETRY_S}s 重测一次"
            )
            motion, frame = cls._scan(context, cls.SCAN_GAP_RETRY_S)
        cells = cls._unopened(motion)
        counter = cls._read_counter(context, frame)
        # 细节（帧间差峰值 / 每格读数）只落文件日志，控制台每轮就一行：还剩几格、几次、点了哪格。
        logger.debug(
            f"[ArtOfIllumination] {node_name} 扫描详情：未开 {len(cells)} 格 / 36 格，"
            f"帧间差峰值 {float(motion.max()):.2f}，计数条读数 {counter}"
        )

        # 先看计数条，再看扫描：次数为 0 时盖着格子的呼吸动画会停（实测 ×0 那一轮用同一判据
        # 扫出「0 格未开」，而棋盘上其实还有 21 格没翻），所以「未开格数」只在还有次数时有效。
        # 这个顺序不能颠倒，否则「次数用完」会被记成「已无未开格子」，把真实情况说错。
        if counter == 0:
            logger.info("[ArtOfIllumination] 可折射次数为 0，收尾")
            cls._finish(context, node_name)
            return True

        if not cells:
            # 本页翻完了。还有折射次数 → 很可能还有另一幕布（多格光影幕布 II）没翻：
            # 实测两页共用一个计数条、共用同一套格心坐标，翻页就是点棋盘左/右那个「>」。
            # 交给 AOI_PageSwitch 去切；切过去要是新的一页还有格子，下一轮就会接着翻；
            # 两页都翻完时它的两个候选都认不到 / max_hit 用尽 → 等满 timeout 后由它的
            # on_error 收尾到 AOI_ScratchCardDone。
            if counter is not None and counter >= 1:
                logger.info(f"[ArtOfIllumination] 本页翻完（还有 {counter} 次）→ 翻另一幕布")
                cls._finish(context, node_name, SWITCH_NODE)
                return True
            logger.info("[ArtOfIllumination] 已无未开格子，收尾")
            cls._finish(context, node_name)
            return True

        row, col, cx, cy = cls._pick(cells)
        logger.info(f"[ArtOfIllumination] {node_name} 未开 {len(cells)} 格，次数 {counter} → 点 ({row},{col})")
        logger.debug(f"[ArtOfIllumination] 该格像素 ({cx},{cy})，帧间差 {float(motion[row - 1, col - 1]):.1f}")
        # **必须显式把 next 重设回原始出口三选一**：上一轮若是翻页/收尾分支，它留下的补丁还在，
        # 不重设的话这一跳会走成 AOI_PageSwitch（于是引擎不等「获得物品」页、直接又去翻页）。
        # 重设之后，等页面出现仍由引擎的 next 轮询承担，本模块不等。
        cls._set_next(context, node_name, ROUND_NEXT)
        context.tasker.controller.post_click(cx, cy).wait()
        return True
