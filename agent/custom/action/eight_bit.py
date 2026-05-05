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


@AgentServer.custom_action("EightBitCombatInit")
class EightBitCombatInit(CustomAction):
    """
    8-bit 战斗初始化，检测是否需要开启碰壁检测
    """

    _bottom_roi: tuple[int, int, int, int] = (352, 579, 613, 97)
    _tp_roi: tuple[int, int, int, int] = (343, 57, 624, 621)
    _boss_roi: tuple[int, int, int, int] = (341, 495, 630, 188)
    wall_detection_enabled: bool = False
    start_time: float = float("inf")

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        context.wait_freezes(time=1000, box=(37, 34, 302, 632))
        time.sleep(3)  # 等待战斗界面稳定
        EightBitCombatInit.start_time = time.time()
        img = context.tasker.controller.post_screencap().wait().get()

        reco_bottom = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                roi=self._bottom_roi,
                template=["8-bit/Bottom.png"],
                threshold=[0.7],
            ),
            img,
        )

        reco_tp = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                roi=self._tp_roi,
                template=["8-bit/TPEntry/"],
                threshold=[0.7],
            ),
            img,
        )

        reco_boss = context.run_recognition_direct(
            JRecognitionType.TemplateMatch,
            JTemplateMatch(
                roi=self._boss_roi,
                template=["8-bit/Boss.png"],
                threshold=[0.8],
            ),
            img,
        )

        if reco_boss and reco_boss.hit:
            logger.debug("[8bit] 识别到 Boss，退出到主页面")
            context.run_task("8bitExit")
            return CustomAction.RunResult(success=True)

        EightBitCombatInit.wall_detection_enabled = (
            reco_bottom is not None and reco_bottom.hit
        ) or (reco_tp is not None and reco_tp.hit)
        if EightBitCombatInit.wall_detection_enabled:
            logger.debug("[8bit] 开启碰壁检测")

        EightBitCombatMove._reset_wall_state()
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("EightBitCombatMove")
class EightBitCombatMove(CustomAction):
    """
    8-bit 街机秀战斗中移动

    逻辑：
    1. 识别 TP（传送点）位置
    2. 如果没有识别到 TP，随机左右移动
    3. 如果识别到 TP，识别人物位置，判断人物在 TP 的左边还是右边，进行相应的移动
    4. 碰壁后记录状态，下次进来继续尝试脱离
    """

    _people_roi: tuple[int, int, int, int] = (407, 109, 564, 571)
    _tp_roi: tuple[int, int, int, int] = (343, 57, 624, 621)
    _same_grid_threshold: int = 70
    _left_boundary: int = 450
    _right_boundary: int = 939
    _wall_threshold: int = 10
    _timeout: int = 150

    _is_wall_stuck: bool = False
    _stuck_pos: tuple[int, int] | None = None
    _tried_escape_directions: list[int] = []
    _escape_priority: list[int] = [
        KEYCODE_DPAD_DOWN,
        KEYCODE_DPAD_LEFT,
        KEYCODE_DPAD_RIGHT,
        KEYCODE_DPAD_UP,
    ]
    _last_move_key: int | None = None

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if time.time() - EightBitCombatInit.start_time > self._timeout:
            logger.warning("[8bit] 战斗超时，退出到主界面")
            EightBitCombatMove._reset_wall_state()
            context.run_task("8bitExit")
            return CustomAction.RunResult(success=True)

        img = context.tasker.controller.cached_image

        if EightBitCombatMove._is_wall_stuck:
            if self._try_escape(context, img):
                return CustomAction.RunResult(success=True)

        tp_pos = self._detect_tp(context, img)
        people_pos = self._detect_people(context, img)

        if tp_pos is not None:
            if people_pos is None:
                logger.debug("[8bit] 未识别到人物，向下移动")
                self._move_and_check_wall(context, KEYCODE_DPAD_DOWN, people_pos)
            elif people_pos[0] < tp_pos[0]:
                logger.debug("[8bit] 人物在 TP 左边，向右移动")
                self._move_and_check_wall(context, KEYCODE_DPAD_RIGHT, people_pos)
            elif abs(people_pos[0] - tp_pos[0]) <= self._same_grid_threshold:
                if people_pos[1] < tp_pos[1]:
                    logger.debug("[8bit] 人物与 TP 同列，人物在上方，向下移动")
                    self._move_and_check_wall(context, KEYCODE_DPAD_DOWN, people_pos)
                else:
                    logger.debug("[8bit] 人物与 TP 同列，人物在下方，向上移动")
                    self._move_and_check_wall(context, KEYCODE_DPAD_UP, people_pos)
            else:
                logger.debug("[8bit] 人物在 TP 右边，向左移动")
                self._move_and_check_wall(context, KEYCODE_DPAD_LEFT, people_pos)
        else:
            if people_pos is not None and not EightBitCombatInit.wall_detection_enabled:
                if people_pos[0] <= self._left_boundary:
                    logger.debug("[8bit] 人物在最左边，向右移动")
                    self._move(context, KEYCODE_DPAD_RIGHT, times=4)
                    return CustomAction.RunResult(success=True)
                if people_pos[0] >= self._right_boundary:
                    logger.debug("[8bit] 人物在最右边，向左移动")
                    self._move(context, KEYCODE_DPAD_LEFT, times=4)
                    return CustomAction.RunResult(success=True)

            logger.debug("[8bit] 未识别到 TP，随机移动")
            self._random_move(context)

        return CustomAction.RunResult(success=True)

    def _move_and_check_wall(
        self, context: Context, key: int, pos_before: tuple[int, int] | None
    ):
        """移动并检测是否碰壁"""
        if not EightBitCombatInit.wall_detection_enabled:
            self._move(context, key)
            return

        self._move(context, key)
        time.sleep(1)  # 等待移动动画

        img = context.tasker.controller.post_screencap().wait().get()
        pos_after = self._detect_people(context, img)

        if (
            pos_before is not None
            and pos_after is not None
            and abs(pos_after[0] - pos_before[0]) < self._wall_threshold
            and abs(pos_after[1] - pos_before[1]) < self._wall_threshold
        ):
            logger.debug("[8bit] 碰壁，进入脱离模式")
            EightBitCombatMove._is_wall_stuck = True
            EightBitCombatMove._stuck_pos = pos_before
            EightBitCombatMove._last_move_key = key
            # 排除来时的方向（反方向）
            opposite_key = self._get_opposite_key(key)
            EightBitCombatMove._tried_escape_directions = [opposite_key]

    def _get_opposite_key(self, key: int) -> int:
        """获取反方向按键"""
        opposites = {
            KEYCODE_DPAD_UP: KEYCODE_DPAD_DOWN,
            KEYCODE_DPAD_DOWN: KEYCODE_DPAD_UP,
            KEYCODE_DPAD_LEFT: KEYCODE_DPAD_RIGHT,
            KEYCODE_DPAD_RIGHT: KEYCODE_DPAD_LEFT,
        }
        return opposites.get(key, key)

    def _try_escape(self, context: Context, img) -> bool:
        """尝试脱离碰壁状态，每次调用只尝试一个方向，返回是否继续"""
        for escape_key in self._escape_priority:
            if escape_key in EightBitCombatMove._tried_escape_directions:
                continue

            logger.debug(f"[8bit] 尝试向{self._key_name(escape_key)}脱离")
            EightBitCombatMove._tried_escape_directions.append(escape_key)
            self._move(context, escape_key)
            time.sleep(1)  # 等待移动动画

            img = context.tasker.controller.post_screencap().wait().get()
            new_pos = self._detect_people(context, img)

            # 根据移动方向判断是否脱离
            if escape_key in (KEYCODE_DPAD_LEFT, KEYCODE_DPAD_RIGHT):
                pos_diff = (
                    abs(new_pos[0] - EightBitCombatMove._stuck_pos[0])
                    if new_pos and EightBitCombatMove._stuck_pos
                    else 0
                )
            else:
                pos_diff = (
                    abs(new_pos[1] - EightBitCombatMove._stuck_pos[1])
                    if new_pos and EightBitCombatMove._stuck_pos
                    else 0
                )

            logger.debug(
                f"[8bit] 脱离检测: new_pos={new_pos}, stuck_pos={EightBitCombatMove._stuck_pos}, 位移={pos_diff}"
            )
            if (
                new_pos is None
                or EightBitCombatMove._stuck_pos is None
                or pos_diff >= self._wall_threshold
            ):
                logger.debug("[8bit] 脱离成功")
                EightBitCombatMove._reset_wall_state()
                return True

            logger.debug(f"[8bit] 向{self._key_name(escape_key)}脱离失败")
            EightBitCombatMove._stuck_pos = new_pos
            return True

        logger.debug("[8bit] 所有方向均碰壁，重置状态")
        EightBitCombatMove._reset_wall_state()
        return False

    @staticmethod
    def _reset_wall_state():
        """重置碰壁状态"""
        EightBitCombatMove._is_wall_stuck = False
        EightBitCombatMove._stuck_pos = None
        EightBitCombatMove._tried_escape_directions = []
        EightBitCombatMove._last_move_key = None

    def _key_name(self, key: int) -> str:
        """获取按键名称"""
        names = {
            KEYCODE_DPAD_UP: "上",
            KEYCODE_DPAD_DOWN: "下",
            KEYCODE_DPAD_LEFT: "左",
            KEYCODE_DPAD_RIGHT: "右",
        }
        return names.get(key, "未知")

    def _detect_tp(self, context: Context, img) -> tuple[int, int] | None:
        """识别 TP 位置，返回中心 (x, y) 坐标，未识别到返回 None"""
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
            return (box[0] + box[2] // 2, box[1] + box[3] // 2)

        return None

    def _detect_people(self, context: Context, img) -> tuple[int, int] | None:
        """识别人物位置，返回中心 (x, y) 坐标，未识别到返回 None"""
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

        if reco_people and reco_people.hit and reco_people.filtered_results:
            if len(reco_people.filtered_results) == 1:
                box = reco_people.filtered_results[0].box
                return (box[0] + box[2] // 2, box[1] + box[3] // 2)

            # 多个结果时，根据上一次移动方向选择
            if EightBitCombatMove._last_move_key == KEYCODE_DPAD_RIGHT:
                # 上次往右，选最左边的
                best = min(reco_people.filtered_results, key=lambda r: r.box[0])
            elif EightBitCombatMove._last_move_key == KEYCODE_DPAD_LEFT:
                # 上次往左，选最右边的
                best = max(reco_people.filtered_results, key=lambda r: r.box[0])
            elif EightBitCombatMove._last_move_key == KEYCODE_DPAD_DOWN:
                # 上次往下，选最上面的
                best = min(reco_people.filtered_results, key=lambda r: r.box[1])
            elif EightBitCombatMove._last_move_key == KEYCODE_DPAD_UP:
                # 上次往上，选最下面的
                best = max(reco_people.filtered_results, key=lambda r: r.box[1])
            else:
                # 没有上次操作，默认选第一个
                best = reco_people.filtered_results[0]

            box = best.box
            return (box[0] + box[2] // 2, box[1] + box[3] // 2)

        return None

    def _random_move(self, context: Context):
        """随机左右移动"""
        key = KEYCODE_DPAD_LEFT if random.random() < 0.5 else KEYCODE_DPAD_RIGHT
        self._move(context, key, times=4)

    def _move(self, context: Context, key: int, times: int = 1):
        """通用移动方法"""
        for _ in range(times):
            context.tasker.controller.post_click_key(key).wait()
        EightBitCombatMove._last_move_key = key


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
