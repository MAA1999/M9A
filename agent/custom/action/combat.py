import re
import time
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from utils import logger
from utils.maa_types import boxed_results, is_hit, ocr_result, ocr_text
from utils.params import parse_params

# 尝试导入掉落识别模块（仅官方发布版可用）
DropRecognitionState: Any = None
run_drop_recognition: Any = None
_drop_recognition_available: bool = False
try:
    from libs.drop_core import (  # pyright: ignore[reportMissingImports]
        DropRecognitionState,
        run_drop_recognition,
    )  # pyright: ignore[reportMissingImports]

    _drop_recognition_available = True
except ImportError:
    logger.warning("掉落识别模块不可用，掉落上报功能已禁用")


@AgentServer.custom_action("SwitchCombatTimes")
class SwitchCombatTimes(CustomAction):
    """
    选择战斗次数 。

    参数格式:
    {
        "times": "目标次数"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        times = parse_params(argv.custom_action_param, "times")["times"]

        context.run_task("OpenReplaysTimes", {"OpenReplaysTimes": {"next": []}})
        context.run_task(
            "SetReplaysTimes",
            {
                "SetReplaysTimes": {
                    "template": [
                        f"Combat/SetReplaysTimesX{times}.png",
                        f"Combat/SetReplaysTimesX{times}_selected.png",
                    ],
                    "order_by": "Score",
                    "next": ["SetReplaysTimes", "FlagInStartReplay"],
                }
            },
        )

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("PsychubeDoubleTimes")
class PsychubeDoubleTimes(CustomAction):
    """
    "识别加成次数，根据结果覆盖 PsychubeVictoryOverrideTask 中参数"
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition(
            "PsychubeDouble",
            img,
        )

        if is_hit(reco_detail):
            text = ocr_text(reco_detail)
            pattern = "(\\d)/4"
            m = re.search(pattern, text)
            if not m:
                logger.error("未能解析 Psychube 加成次数: {}", text)
                return CustomAction.RunResult(success=True)
            times = int(m.group(1))
            expected = self._int2Chinese(times)
            context.override_pipeline(
                {
                    "PsychubeVictoryOverrideTask": {
                        "custom_action_param": {
                            "PsychubeFlagInReplayTwoTimes": {"expected": f"{expected}"},
                            "SwitchCombatTimes": {"custom_action_param": {"times": times}},
                            "PsychubeVictory": {
                                "next": [
                                    "HomeFlag",
                                    "PsychubeVictory",
                                    "[JumpBack]HomeButton",
                                    "[JumpBack]CombatEntering",
                                    "[JumpBack]HomeLoading",
                                ]
                            },
                            "PsychubeDouble": {"enabled": False},
                        }
                    }
                }
            )

        return CustomAction.RunResult(success=True)

    def _int2Chinese(self, times: int) -> str:
        Chinese = ["一", "二", "三", "四"]
        return Chinese[times - 1]


@AgentServer.custom_action("TeamSelect")
class TeamSelect(CustomAction):
    """
    队伍选择

    参数格式：
    {
        "team": "队伍选择"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        team = parse_params(argv.custom_action_param, "team")["team"]

        img = context.tasker.controller.post_screencap().wait().get()

        reco_off_old = context.run_recognition(
            "TeamlistOff",
            img,
            {"TeamlistOff": {"recognition": {"param": {"template": "Combat/TeamList_Off_old.png"}}}},
        )
        reco_open_old = context.run_recognition(
            "TeamlistOpen",
            img,
            {
                "TeamlistOpen": {
                    "recognition": {
                        "param": {
                            "roi": [940, 631, 48, 48],
                            "template": "Combat/TeamList_Open_old.png",
                        }
                    }
                }
            },
        )

        if is_hit(reco_off_old) or is_hit(reco_open_old):
            # 旧版
            target_list = [
                [794, 406],
                [794, 466],
                [797, 525],
                [798, 586],
            ]
            target = target_list[team - 1]
            flag = False
            while not flag:
                img = context.tasker.controller.post_screencap().wait().get()

                reco_open_old = context.run_recognition(
                    "TeamlistOpen",
                    img,
                    {
                        "TeamlistOpen": {
                            "recognition": {
                                "param": {
                                    "roi": [940, 631, 48, 48],
                                    "template": "Combat/TeamList_Open_old.png",
                                }
                            }
                        }
                    },
                )
                if is_hit(reco_open_old):
                    context.tasker.controller.post_click(target[0], target[1]).wait()
                    time.sleep(1)
                    flag = True
                else:
                    reco_off_old = context.run_recognition(
                        "TeamlistOff",
                        img,
                        {"TeamlistOff": {"recognition": {"param": {"template": "Combat/TeamList_Off_old.png"}}}},
                    )
                    if is_hit(reco_off_old):
                        context.tasker.controller.post_click(965, 650).wait()
                        time.sleep(1)
        else:
            # 新版
            reco_off_new = context.run_recognition(
                "TeamlistOff",
                img,
                {"TeamlistOff": {"recognition": {"param": {"template": "Combat/TeamList_Off.png"}}}},
            )
            if not is_hit(reco_off_new):
                logger.debug("未识别到队伍选择界面")
                return CustomAction.RunResult(success=False)
            flag = False
            team_names, team_uses = [], {}
            while not flag:
                img = context.tasker.controller.post_screencap().wait().get()

                reco_open_new = context.run_recognition(
                    "TeamlistOpen",
                    img,
                    {
                        "TeamlistOpen": {
                            "recognition": {
                                "param": {
                                    "roi": [36, 63, 137, 141],
                                    "template": "Combat/TeamList_Open.png",
                                }
                            }
                        }
                    },
                )
                if is_hit(reco_open_new):
                    # 识别到在队伍选择界面
                    time.sleep(2)  # 等待界面稳定
                    img = context.tasker.controller.post_screencap().wait().get()
                    reco_result = context.run_recognition("TeamListEditRoi", img)
                    if not is_hit(reco_result) or not reco_result.filtered_results:
                        logger.error("未识别到成员队列")
                        return CustomAction.RunResult(success=False)
                    else:
                        # 识别到每个队伍左上角标志，获取每个队伍的名称和按键位置
                        team_rois = boxed_results(reco_result)
                        team_name_rois, team_confirm_rois = [], []
                        for team_roi in team_rois:
                            x, y, w, h = team_roi.box
                            team_name_rois.append([x + 38, y, w + 72, h])
                            team_confirm_rois.append([x + 708, y + 73, w + 108, h + 32])
                        for i in range(len(team_name_rois)):
                            # 识别每个队伍名称
                            reco_detail = context.run_recognition(
                                "TeamListOCR",
                                img,
                                {
                                    "TeamListOCR": {
                                        "recognition": {
                                            "param": {
                                                "roi": team_name_rois[i],
                                                "ecpected": ".*",
                                                "only_rec": True,
                                            }
                                        }
                                    }
                                },
                            )
                            team_name = ocr_text(reco_detail)
                            if team_name not in team_names:
                                team_names.append(team_name)
                            # 队伍名称为新增，识别使用&使用中状态
                            reco_detail = context.run_recognition(
                                "TeamListOCR",
                                img,
                                {
                                    "TeamListOCR": {
                                        "recognition": {
                                            "param": {
                                                "roi": team_confirm_rois[i],
                                                "ecpected": "使用",
                                                "only_rec": False,
                                            }
                                        }
                                    }
                                },
                            )
                            team_use_result = ocr_result(reco_detail)
                            if not is_hit(reco_detail) or team_use_result is None:
                                team_use_text = ""
                                team_use_roi = None
                            else:
                                team_use_text = team_use_result.text
                                team_use_roi = team_use_result.box
                            team_use_status = -1
                            if "使用中" in team_use_text:
                                team_use_status = 1
                            elif "使用" in team_use_text:
                                team_use_status = 0
                            team_uses.update(
                                {
                                    team_name: {
                                        "roi": team_use_roi,
                                        "status": team_use_status,
                                    }
                                }
                            )
                        # 识别完当页所有队伍信息，判断目标队伍是否存在
                        if team > len(team_names):
                            # 目标队伍不在当页，翻页并进行下一轮识别
                            context.tasker.controller.post_swipe(980, 630, 980, 190, 1000).wait()
                            time.sleep(1)
                            continue
                        elif team <= len(team_names):
                            # 目标队伍在当前页，进行队伍选择
                            target_team_name = team_names[team - 1]
                            target_team_use = team_uses[target_team_name]
                            if target_team_use["status"] == 1:
                                # 目标队伍已是使用中，直接退出
                                exit_retry = 0
                                while exit_retry < 5:
                                    context.run_task("BackButton")
                                    time.sleep(1)
                                    img = context.tasker.controller.post_screencap().wait().get()
                                    reco_open_new = context.run_recognition(
                                        "TeamlistOpen",
                                        img,
                                        {
                                            "TeamlistOpen": {
                                                "recognition": {
                                                    "param": {
                                                        "roi": [36, 63, 137, 141],
                                                        "template": "Combat/TeamList_Open.png",
                                                    }
                                                }
                                            }
                                        },
                                    )
                                    if not is_hit(reco_open_new):
                                        # 已退出选择界面
                                        flag = True
                                        break
                                    exit_retry += 1
                                break
                            elif target_team_use["status"] == 0:
                                # 目标队伍非使用中，点击使用并自动退出当前界面
                                retry = 0
                                while True:
                                    retry += 1
                                    if retry > 5:
                                        logger.warning("队伍选择失败，超过最大重试次数")
                                        return CustomAction.RunResult(success=True)
                                    x, y, w, h = target_team_use["roi"]
                                    context.tasker.controller.post_click(x + w // 2, y + h // 2).wait()
                                    time.sleep(1)
                                    img = context.tasker.controller.post_screencap().wait().get()
                                    reco_detail = context.run_recognition("ReadyForAction", img)

                                    if is_hit(reco_detail):
                                        break

                                flag = True
                                break
                else:
                    reco_off_new = context.run_recognition(
                        "TeamlistOff",
                        img,
                        {"TeamlistOff": {"recognition": {"param": {"template": "Combat/TeamList_Off.png"}}}},
                    )
                    if is_hit(reco_off_new):
                        # 识别到不在队伍选择界面，点击打开
                        context.tasker.controller.post_click(965, 650).wait()
                        time.sleep(1)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CombatTargetLevel")
class CombatTargetLevel(CustomAction):
    """
    主线目标难度

    参数格式：
    {
        "level": "难度选择"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        valid_levels = {"童话", "故事", "厄险"}
        level = parse_params(argv.custom_action_param, "level")["level"]

        if not level or level not in valid_levels:
            logger.error("目标难度不存在")
            return CustomAction.RunResult(success=False)

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("TargetLevelRec", img)

        reco_text = ocr_text(reco_detail)
        if not reco_text or not any(difficulty in reco_text for difficulty in valid_levels):
            logger.warning("未识别到当前难度")
            return CustomAction.RunResult(success=False)

        text = reco_text

        if level == "厄险":
            if "厄险" not in text:
                context.tasker.controller.post_click(1175, 265).wait()
        elif level == "故事":
            if "厄险" in text:
                context.tasker.controller.post_click(1130, 265).wait()
            elif "童话" in text:
                context.tasker.controller.post_click(1095, 265).wait()
        else:
            if "童话" not in text:
                context.tasker.controller.post_click(945, 265).wait()

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ActivityTargetLevel")
class ActivityTargetLevel(CustomAction):
    """
    活动目标难度

    参数格式：
    {
        "level": "难度选择"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        valid_levels = {"故事", "意外", "艰难"}
        level = parse_params(argv.custom_action_param, "level")["level"]

        node = context.get_node_data("ActivityTargetLevel")
        click = None
        if isinstance(node, dict):
            click = node.get("attach", {}).get("clicks")
        if not click:
            click = [[945, 245], [1190, 245]]

        if not level or level not in valid_levels:
            logger.error("目标难度不存在")
            return CustomAction.RunResult(success=False)

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("ActivityTargetLevelRec", img)

        reco_text = ocr_text(reco_detail)
        if not reco_text or not any(difficulty in reco_text for difficulty in valid_levels):
            logger.warning("未识别到当前难度")
            return CustomAction.RunResult(success=False)

        cur_level = reco_text

        retry = 0

        while cur_level != level:
            retry += 1
            if retry > 10:
                logger.error("切换难度失败，超过最大重试次数，请检查选择难度是否正确")
                return CustomAction.RunResult(success=False)
            if cur_level == "故事":
                context.tasker.controller.post_click(click[1][0], click[1][1]).wait()
                time.sleep(0.5)
            elif cur_level == "艰难":
                context.tasker.controller.post_click(click[0][0], click[0][1]).wait()
                time.sleep(0.5)
            else:
                if level == "故事":
                    context.tasker.controller.post_click(click[0][0], click[0][1]).wait()
                    time.sleep(0.5)
                else:
                    context.tasker.controller.post_click(click[1][0], click[1][1]).wait()
                    time.sleep(0.5)

            img = context.tasker.controller.post_screencap().wait().get()
            reco_detail = context.run_recognition("ActivityTargetLevelRec", img)

            cur_level = ocr_text(reco_detail) or None

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SelectChapter")
class SelectChapter(CustomAction):
    """
    章节选择 。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 返回大章节
        context.run_task("ReturnMainStoryChapter", {"ReturnMainStoryChapter": {}})

        flag, count = False, 0
        while not flag:
            context.run_task(
                "SelectMainStoryChapter",
                {
                    "SelectMainStoryChapter": {
                        "template": f"Combat/MainStoryChapter_{SelectCombatStage.mainStoryChapter}.png"
                    }
                },
            )
            img = context.tasker.controller.post_screencap().wait().get()
            count += 1
            # 判断是否还能匹配上大章节（位置不同/角度不同）
            rec = context.run_recognition(
                "SelectMainStoryChapter",
                img,
                {
                    "SelectMainStoryChapter": {
                        "template": f"Combat/MainStoryChapter_{SelectCombatStage.mainStoryChapter}.png"
                    }
                },
            )
            if not is_hit(rec) or count >= 5:
                flag = True

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SelectCombatStage")
class SelectCombatStage(CustomAction):
    # 类静态变量，用于跨任务传递关卡信息
    stage = None
    # stageName = None
    level = None
    mainStoryChapter = None

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 获取关卡信息
        param = parse_params(argv.custom_action_param, "stage")
        stage = param["stage"]

        node_obj = context.get_node_object("SelectCombatStage")
        if node_obj is None:
            logger.error("SelectCombatStage 节点不存在")
            return CustomAction.RunResult(success=False)
        level = node_obj.attach.get("level", "Hard")
        logger.info(f"当前关卡: {stage}, 难度: {level}")

        # 拆分关卡编号，如 "5-19" 拆为 ["5", "19"]
        parts = stage.split("-")
        if len(parts) < 2:
            logger.error(f"关卡格式错误: {stage}")
            return CustomAction.RunResult(success=False)

        mainChapter = parts[0]  # 主章节编号或资源关卡
        targetStageName = parts[1]  # 关卡序号或资源关卡编号

        # 若关卡序号为数字，补零为两位字符串
        if targetStageName.isdigit():
            targetStageName = f"{int(targetStageName):02d}"

        # 判断是否主线章节（数字），并确定大章节编号
        if mainChapter.isdigit():
            mainStoryChapter = 1 if int(mainChapter) <= 7 else 2 if int(mainChapter) <= 10 else 3
            # 主线关卡流程
            pipeline = {
                "EnterTheShowFlag": {"next": ["MainChapter_X"]},
                "MainChapter_XEnter": {"template": [f"Combat/MainChapter_{mainChapter}Enter.png"]},
                "TargetStageName_OCR": {"expected": [f"{targetStageName}"]},
                "StageDifficulty": {"next": [f"StageDifficulty_{level}", "TargetStageName"]},
                # 掉落识别相关节点
                "TargetCountVictory": {
                    "action": {"type": "DoNothing"},
                    "next": ["DropRecognition", "TargetCountVictoryClick"],
                },
                "DropRecognition": {
                    "recognition": {
                        "type": "OCR",
                        "param": {
                            "roi": [678, 10, 473, 240],
                            "expected": ["战斗", "胜利"],
                        },
                    },
                    "action": {
                        "type": "Custom",
                        "param": {"custom_action": "DropRecognition"},
                    },
                    "next": [
                        "TargetCountVictoryClick",
                    ],
                },
                "TargetCountVictoryClick": {
                    "recognition": {
                        "type": "OCR",
                        "param": {
                            "roi": [678, 10, 473, 240],
                            "expected": ["战斗", "胜利"],
                        },
                    },
                    "action": {"type": "Click"},
                    "next": [
                        "TargetCountWaitReplay",
                        "[JumpBack]CombatEntering",
                        "TargetCountVictoryClick",
                    ],
                },
            }
        else:
            mainStoryChapter = None
            # 资源关卡流程
            pipeline = {
                "EnterTheShowFlag": {"next": [f"ResourceChapter_{mainChapter}"]},
                "TargetStageName_OCR": {"expected": [f"{targetStageName}"]},
                "StageDifficulty": {"next": [f"StageDifficulty_{level}", "TargetStageName"]},
            }

        context.override_pipeline(pipeline)

        SelectCombatStage.stage = stage
        # SelectCombatStage.stageName = stageName
        SelectCombatStage.level = level
        SelectCombatStage.mainStoryChapter = mainStoryChapter

        return CustomAction.RunResult(success=True)


class _TargetCountState:
    target_count: int = 0
    already_count: int = 0
    current_times: int = 0
    candy_attempts: int = 0


def _tc_safe_int(text: str) -> int:
    try:
        return int(text)
    except Exception:
        return 0


def _tc_get_text_safe(context: Context, img: Any, rec_name: str) -> str:
    rec = context.run_recognition(rec_name, img)
    text = ocr_text(rec)
    if not text:
        logger.debug(f"{rec_name} 识别失败，返回None")
        return "0"
    return text


def _tc_get_available_count(context: Context) -> int:
    img = context.tasker.controller.post_screencap().wait().get()
    remaining_ap = _tc_safe_int(_tc_get_text_safe(context, img, "RecognizeRemainingAp"))
    stage_ap = _tc_safe_int(_tc_get_text_safe(context, img, "RecognizeStageAp"))
    combat_times = _tc_safe_int(_tc_get_text_safe(context, img, "RecognizeCombatTimes"))
    if stage_ap == 0:
        logger.debug("stage_ap 为0")
        return 999
    if combat_times == 0:
        logger.debug("识别失败，combat_times 为0")
        return -1
    stage_ap = stage_ap // combat_times
    logger.debug(f"剩余体力: {remaining_ap}, 关卡体力: {stage_ap}")
    return remaining_ap // stage_ap if stage_ap else 0


def _tc_pick_times(available_count: int, target_count: int, already_count: int) -> int:
    left_count = max(target_count - already_count, 0)
    return min(4, available_count, left_count)


@AgentServer.custom_action("TargetCountInit")
class TargetCountInit(CustomAction):
    """
    初始化刷图计数。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        param = parse_params(argv.custom_action_param)
        target_count = int(param.get("target_count", 114514))

        _TargetCountState.target_count = target_count
        _TargetCountState.already_count = 0
        _TargetCountState.current_times = 0
        _TargetCountState.candy_attempts = 0

        # 清空之前的掉落统计
        if _drop_recognition_available:
            DropRecognitionState.reset_total()

        logger.info(f"目标刷图次数：{target_count}")

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("TargetCountDetermine")
class TargetCountDetermine(CustomAction):
    """
    决定下一步动作：复现 / 吃糖 / 结束。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 已达到目标次数，结束任务
        if _TargetCountState.already_count >= _TargetCountState.target_count:
            context.override_next("TargetCountDetermine", ["TargetCountFinish"])
            return CustomAction.RunResult(success=True)

        available_count = _tc_get_available_count(context)
        if available_count == -1:
            context.override_next("TargetCountDetermine", ["TargetCountAbort"])
            return CustomAction.RunResult(success=True)

        times = _tc_pick_times(
            available_count,
            _TargetCountState.target_count,
            _TargetCountState.already_count,
        )
        if times > 0:
            _TargetCountState.current_times = times
            logger.info(f"准备复现 {times} 次，累计已刷 {_TargetCountState.already_count} 次")
            context.override_next("TargetCountDetermine", ["TargetCountOpenPanel"])
            return CustomAction.RunResult(success=True)

        if _TargetCountState.candy_attempts >= 2:
            logger.debug("尝试补体两次后仍不足，结束任务")
            context.override_next("TargetCountDetermine", ["TargetCountFinish"])
            return CustomAction.RunResult(success=True)

        _TargetCountState.candy_attempts += 1
        logger.debug(f"无可复现次数，尝试第 {_TargetCountState.candy_attempts} 次补体")
        context.override_next("TargetCountDetermine", ["TargetCountEatCandy"])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("TargetCountSelectTimes")
class TargetCountSelectTimes(CustomAction):
    """
    根据状态选择复现次数。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        times = _TargetCountState.current_times
        if times <= 0:
            logger.error("当前复现次数无效，终止任务")
            context.override_next("TargetCountSelectTimes", ["TargetCountAbort"])
            return CustomAction.RunResult(success=True)

        logger.info(f"选择复现 {times} 次")
        context.run_task(
            "SetReplaysTimes",
            {
                "SetReplaysTimes": {
                    "template": [
                        f"Combat/SetReplaysTimesX{times}.png",
                        f"Combat/SetReplaysTimesX{times}_selected.png",
                    ],
                    "next": ["SetReplaysTimes", "FlagInStartReplay"],
                }
            },
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("TargetCountEatCandy")
class TargetCountEatCandy(CustomAction):
    """
    通过 EatCandy 流水线补体力。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        context.run_task("EatCandy")
        context.override_next("TargetCountEatCandy", ["TargetCountDetermine"])
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("TargetCountProgress")
class TargetCountProgress(CustomAction):
    """
    统计复现次数并决定是否继续。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        _TargetCountState.already_count += _TargetCountState.current_times
        _TargetCountState.current_times = 0
        _TargetCountState.candy_attempts = 0

        logger.info(f"累计已刷 {_TargetCountState.already_count} 次")

        if _TargetCountState.already_count >= _TargetCountState.target_count:
            logger.info("达到目标次数，准备结束任务")
            context.override_next("TargetCountProgress", ["TargetCountFinish"])
        else:
            context.override_next("TargetCountProgress", ["TargetCountDetermine"])

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("TargetCountFinish")
class TargetCountFinish(CustomAction):
    """
    结束刷图，返回主界面。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        logger.info(f"任务结束，总共刷了 {_TargetCountState.already_count} 次")

        # 输出掉落总结
        if _drop_recognition_available:
            DropRecognitionState.print_total_summary(context)
            DropRecognitionState.reset_total()

        context.run_task("HomeButton")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("TargetCountAbort")
class TargetCountAbort(CustomAction):
    """
    识别失败等异常情况下终止刷图任务，返回主界面。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        logger.error(f"无法获取可复现次数，终止刷图任务，已刷 {_TargetCountState.already_count} 次")
        context.run_task("HomeButton")
        return CustomAction.RunResult(success=False)


@AgentServer.custom_action("SSReopenReplay")
class SSReopenReplay(CustomAction):
    """
    重开关卡复现。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 尝试切换到复现状态
        context.run_task("SSToReplayIfCan")

        # 看看要不要吃不吃糖
        available_count = _tc_get_available_count(context)
        if available_count == -1:
            logger.debug("识别战斗次数失败")
            available_count = 1
        elif available_count <= 0:
            logger.debug("没体力咯，吃个糖")
            for _ in range(2):  # 最多吃两次糖，防止吃mini糖体力不够
                context.run_task("EatCandy")

                available_count = _tc_get_available_count(context)
                if available_count == -1:
                    logger.debug("识别战斗次数失败")
                    available_count = 1
            if available_count <= 0:
                logger.debug("尝试吃糖后体力不够，任务结束。")
                context.run_task("HomeButton")
                context.tasker.post_stop()
                return CustomAction.RunResult(success=True)

        # 开始刷图
        img = context.tasker.controller.cached_image
        reco_detail = context.run_recognition("SSCannotReplay", img)
        if is_hit(reco_detail):
            # 无法复现，直接开始任务
            context.run_task("SSNoReplay")
        else:
            # 可复现
            context.override_pipeline(
                {
                    "SetReplaysTimes": {
                        "template": [
                            "Combat/SetReplaysTimesX1.png",
                            "Combat/SetReplaysTimesX1_selected.png",
                        ]
                    }
                }
            )
            context.run_task("OpenReplaysTimes")
            context.run_task("SSReopenBackToMain")

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("EatCandyStart")
class EatCandyStart(CustomAction):
    """
    开始吃糖。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        params: dict[str, Any] | None = context.get_node_data("EatCandyStart")
        if not params:
            logger.error("EatCandyStart 节点不存在")
            return CustomAction.RunResult(success=False)
        # 有效期：24h, 7d, 14d, infinite
        # 最大吃糖次数：0表示无限吃

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ResetEatCandyFlag")
class ResetEatCandyFlag(CustomAction):
    """
    重置吃糖标记，用于 QuitEatCandyPage 后清除非快速模式的限制。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        from custom.reco.combat import CandyPageRecord

        CandyPageRecord.reset_eaten_flag()
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DropRecognition")
class DropRecognition(CustomAction):
    """
    掉落物品识别。
    在战斗胜利后识别掉落的物品和数量。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        if not _drop_recognition_available:
            return CustomAction.RunResult(success=True)

        success = run_drop_recognition(
            context,
            SelectCombatStage.stage,
            SelectCombatStage.level,
            _TargetCountState.current_times,
        )
        return CustomAction.RunResult(success=success)
