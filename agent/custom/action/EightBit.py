import random
import time

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from maa.pipeline import JRecognitionType, JTemplateMatch, JOCR

from utils import logger

KEYCODE_DPAD_UP = 19
KEYCODE_DPAD_DOWN = 20
KEYCODE_DPAD_LEFT = 21
KEYCODE_DPAD_RIGHT = 22


@AgentServer.custom_action("EightBitCombatMove")
class EightBitCombatMove(CustomAction):
    """
    8-bit 街机秀战斗中移动

    逻辑：
    1. 识别 TP（传送点）位置
    2. 如果没有识别到 TP，随机左右移动
    3. 如果识别到 TP，识别人物位置，判断人物在 TP 的左边还是右边，进行相应的移动
    """

    # _people_roi: tuple[int, int, int, int] = (414, 643, 553, 35)  # 只识别最下面一行
    _people_roi: tuple[int, int, int, int] = (407, 186, 564, 494)  # 基本全屏
    _tp_roi: tuple[int, int, int, int] = (343, 57, 624, 621)
    _same_grid_threshold: int = 70
    _left_boundary: int = 450
    _right_boundary: int = 939

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.cached_image

        people_x = self._detect_people(context, img)

        if people_x is not None:
            if people_x <= self._left_boundary:
                logger.debug("[8bit] 人物在最左边，向右移动")
                self._move(context, KEYCODE_DPAD_RIGHT)
                return CustomAction.RunResult(success=True)
            if people_x >= self._right_boundary:
                logger.debug("[8bit] 人物在最右边，向左移动")
                self._move(context, KEYCODE_DPAD_LEFT)
                return CustomAction.RunResult(success=True)

        tp_x = self._detect_tp(context, img)

        if tp_x is None:
            logger.debug("[8bit] 未识别到 TP，随机移动")
            self._random_move(context)
        elif people_x is None:
            logger.debug("[8bit] 未识别到人物，向下移动")
            self._move(context, KEYCODE_DPAD_DOWN)
        elif people_x < tp_x:
            logger.debug("[8bit] 人物在 TP 左边，向右移动")
            self._move(context, KEYCODE_DPAD_RIGHT)
        elif abs(people_x - tp_x) <= self._same_grid_threshold:
            logger.debug(f"[8bit] 人物与 TP 同格，向上移动")
            self._move(context, KEYCODE_DPAD_UP)
        else:
            logger.debug(f"[8bit] 人物在 TP 右边，向左移动")
            self._move(context, KEYCODE_DPAD_LEFT)

        return CustomAction.RunResult(success=True)

    def _detect_tp(self, context: Context, img) -> int | None:
        """识别 TP 位置，返回中心 x 坐标，未识别到返回 None"""
        reco_tp = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                roi=self._tp_roi,
                template=["8-bit/TPEntry/"],
                threshold=[0.7],
                order_by="Score",
                method=10001,
            ),
            img,
        )

        if reco_tp and reco_tp.hit and reco_tp.best_result:
            box = reco_tp.best_result.box
            return box[0] + box[2] // 2

        return None

    def _detect_people(self, context: Context, img) -> int | None:
        """识别人物位置，返回中心 x 坐标，未识别到返回 None"""
        reco_people = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                roi=self._people_roi,
                template=["8-bit/People/"],
                threshold=[0.6],
                order_by="Score",
            ),
            img,
        )

        if reco_people and reco_people.hit and reco_people.best_result:
            box = reco_people.best_result.box
            return box[0] + box[2] // 2

        return None

    def _random_move(self, context: Context):
        """随机左右移动"""
        key = KEYCODE_DPAD_LEFT if random.random() < 0.5 else KEYCODE_DPAD_RIGHT
        self._move(context, key)

    def _move(self, context: Context, key: int, times: int = 1):
        """通用移动方法"""
        for _ in range(times):
            context.tasker.controller.post_click_key(key).wait()


@AgentServer.custom_action("EightBitScoreRecord")
class EightBitScoreRecord(CustomAction):
    """
    8-bit 战斗结束后记录获得代币数量并统计效率

    逻辑：
    1. 识别代币位置，进行 OCR 识别
    2. 第一次执行只记录代币数和时间
    3. 后续执行计算代币效率（代币增量 / 时间增量）
    """

    _score_roi: tuple[int, int, int, int] = (846, 493, 65, 30)
    _first_time: float = 0
    _first_score: int = 0
    _total_score: int = 0
    _record_count: int = 0

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.cached_image

        score_detail = context.run_recognition_direct(
            JRecognitionType.OCR,
            JOCR(
                roi=self._score_roi,
                expected=["^\\d+$"],
                only_rec=True,
            ),
            img,
        )

        if not (score_detail and score_detail.hit):
            logger.warning("[8bit] 未识别到获得代币")
            context.tasker.controller.post_click(
                700, 600
            ).wait()  # 点击空白处关闭可能的弹窗
            return CustomAction.RunResult(success=True)

        current_score = int(score_detail.best_result.text)
        current_time = time.time()
        self._record_count += 1

        if self._record_count == 1:
            self._first_time = current_time
            self._first_score = current_score
            self._total_score = current_score
            logger.info(f"[8bit] 本次战斗获得代币：{current_score}")
        else:
            self._total_score += current_score
            score_diff = self._total_score - self._first_score
            time_diff = current_time - self._first_time
            if time_diff > 0:
                efficiency = score_diff / time_diff * 60
                logger.info(
                    f"[8bit] 本次战斗获得代币：{current_score}，"
                    f"累计：{self._total_score}，"
                    f"效率：{efficiency:.1f} 代币/分钟"
                )
            else:
                logger.info(
                    f"[8bit] 本次战斗获得代币：{current_score}，累计：{self._total_score}"
                )

        context.tasker.controller.post_click(
            700, 600
        ).wait()  # 点击空白处关闭可能的弹窗
        return CustomAction.RunResult(success=True)
