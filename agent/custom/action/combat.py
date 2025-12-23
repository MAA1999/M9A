import re
import json
import time
import uuid
import hashlib
import warnings
import requests
import numpy as np
from PIL import Image
import os

# 禁用 SSL 警告
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


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

        times = json.loads(argv.custom_action_param)["times"]

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
                    "next": [],
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

        if reco_detail and reco_detail.hit:
            best = getattr(reco_detail, "best_result", None)
            text = getattr(best, "text", "") if best is not None else ""
            pattern = "(\\d)/4"
            m = re.search(pattern, text)
            if not m:
                logger.error("未能解析 Psychube 加成次数: %s", text)
                return CustomAction.RunResult(success=True)
            times = int(m.group(1))
            expected = self._int2Chinese(times)
            context.override_pipeline(
                {
                    "PsychubeVictoryOverrideTask": {
                        "custom_action_param": {
                            "PsychubeFlagInReplayTwoTimes": {"expected": f"{expected}"},
                            "SwitchCombatTimes": {
                                "custom_action_param": {"times": times}
                            },
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

        team = json.loads(argv.custom_action_param)["team"]

        img = context.tasker.controller.post_screencap().wait().get()

        reco_off_old = context.run_recognition(
            "TeamlistOff",
            img,
            {
                "TeamlistOff": {
                    "recognition": {
                        "param": {"template": "Combat/TeamList_Off_old.png"}
                    }
                }
            },
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

        if (reco_off_old and reco_off_old.hit) or (reco_open_old and reco_open_old.hit):
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
                if reco_open_old and reco_open_old.hit:
                    context.tasker.controller.post_click(target[0], target[1]).wait()
                    time.sleep(1)
                    flag = True
                else:
                    reco_off_old = context.run_recognition(
                        "TeamlistOff",
                        img,
                        {
                            "TeamlistOff": {
                                "recognition": {
                                    "param": {"template": "Combat/TeamList_Off_old.png"}
                                }
                            }
                        },
                    )
                    if reco_off_old and reco_off_old.hit:
                        context.tasker.controller.post_click(965, 650).wait()
                        time.sleep(1)
        else:
            # 新版
            reco_off_new = context.run_recognition(
                "TeamlistOff",
                img,
                {
                    "TeamlistOff": {
                        "recognition": {
                            "param": {"template": "Combat/TeamList_Off.png"}
                        }
                    }
                },
            )
            if not (reco_off_new and reco_off_new.hit):
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
                if reco_open_new and reco_open_new.hit:
                    # 识别到在队伍选择界面
                    time.sleep(2)  # 等待界面稳定
                    img = context.tasker.controller.post_screencap().wait().get()
                    reco_result = context.run_recognition("TeamListEditRoi", img)
                    if (
                        reco_result is None
                        or not reco_result.hit
                        or not reco_result.filtered_results
                    ):
                        logger.error("未识别到成员队列")
                        return CustomAction.RunResult(success=False)
                    else:
                        # 识别到每个队伍左上角标志，获取每个队伍的名称和按键位置
                        team_rois = reco_result.filtered_results
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
                            if (
                                reco_detail is None
                                or not reco_detail.hit
                                or not getattr(reco_detail, "best_result", None)
                            ):
                                team_name = ""
                            else:
                                best = getattr(reco_detail, "best_result", None)
                                team_name = (
                                    getattr(best, "text", "")
                                    if best is not None
                                    else ""
                                )
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
                            if (
                                reco_detail is None
                                or not reco_detail.hit
                                or not getattr(reco_detail, "best_result", None)
                            ):
                                team_use_text = ""
                                team_use_roi = None
                            else:
                                best = getattr(reco_detail, "best_result", None)
                                team_use_text = (
                                    getattr(best, "text", "")
                                    if best is not None
                                    else ""
                                )
                                team_use_roi = (
                                    getattr(best, "box", None)
                                    if best is not None
                                    else None
                                )
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
                            context.tasker.controller.post_swipe(
                                980, 630, 980, 190, 1000
                            ).wait()
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
                                    img = (
                                        context.tasker.controller.post_screencap()
                                        .wait()
                                        .get()
                                    )
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
                                    if reco_open_new is None or not reco_open_new.hit:
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
                                    context.tasker.controller.post_click(
                                        x + w // 2, y + h // 2
                                    ).wait()
                                    time.sleep(1)
                                    img = (
                                        context.tasker.controller.post_screencap()
                                        .wait()
                                        .get()
                                    )
                                    reco_detail = context.run_recognition(
                                        "ReadyForAction", img
                                    )

                                    if reco_detail and reco_detail.hit:
                                        break

                                flag = True
                                break
                else:
                    reco_off_new = context.run_recognition(
                        "TeamlistOff",
                        img,
                        {
                            "TeamlistOff": {
                                "recognition": {
                                    "param": {"template": "Combat/TeamList_Off.png"}
                                }
                            }
                        },
                    )
                    if reco_off_new and reco_off_new.hit:
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
        level = json.loads(argv.custom_action_param)["level"]

        if not level or level not in valid_levels:
            logger.error("目标难度不存在")
            return CustomAction.RunResult(success=False)

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("TargetLevelRec", img)

        best = (
            getattr(reco_detail, "best_result", None)
            if reco_detail and reco_detail.hit
            else None
        )
        reco_text = getattr(best, "text", "") if best is not None else ""
        if not reco_text or not any(
            difficulty in reco_text for difficulty in valid_levels
        ):
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
        level = json.loads(argv.custom_action_param)["level"]

        node = context.get_node_data("ActivityTargetLevelClick")
        click = None
        if isinstance(node, dict):
            click = (
                node.get("action", {})
                .get("param", {})
                .get("custom_action_param", {})
                .get("clicks")
            )
        if not click:
            click = [[945, 245], [1190, 245]]

        if not level or level not in valid_levels:
            logger.error("目标难度不存在")
            return CustomAction.RunResult(success=False)

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("ActivityTargetLevelRec", img)

        best = (
            getattr(reco_detail, "best_result", None)
            if reco_detail and reco_detail.hit
            else None
        )
        reco_text = getattr(best, "text", "") if best is not None else ""
        if not reco_text or not any(
            difficulty in reco_text for difficulty in valid_levels
        ):
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
                    context.tasker.controller.post_click(
                        click[0][0], click[0][1]
                    ).wait()
                    time.sleep(0.5)
                else:
                    context.tasker.controller.post_click(
                        click[1][0], click[1][1]
                    ).wait()
                    time.sleep(0.5)

            img = context.tasker.controller.post_screencap().wait().get()
            reco_detail = context.run_recognition("ActivityTargetLevelRec", img)

            if reco_detail and reco_detail.hit:
                best = getattr(reco_detail, "best_result", None)
                cur_level = getattr(best, "text", "") if best is not None else None
            else:
                cur_level = None

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
            if rec is None or not getattr(rec, "hit", False) or count >= 5:
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
        param = json.loads(argv.custom_action_param)
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
            mainStoryChapter = (
                1 if int(mainChapter) <= 7 else 2 if int(mainChapter) <= 10 else 3
            )
            # 主线关卡流程
            pipeline = {
                "EnterTheShowFlag": {"next": ["MainChapter_X"]},
                "MainChapter_XEnter": {
                    "template": [f"Combat/MainChapter_{mainChapter}Enter.png"]
                },
                "TargetStageName": {"expected": [f"{targetStageName}"]},
                "StageDifficulty": {
                    "next": [f"StageDifficulty_{level}", "TargetStageName"]
                },
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
                "TargetStageName": {"expected": [f"{targetStageName}"]},
                "StageDifficulty": {
                    "next": [f"StageDifficulty_{level}", "TargetStageName"]
                },
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


def _tc_get_text_safe(context: Context, img, rec_name: str) -> str:
    rec = context.run_recognition(rec_name, img)
    if rec is None or getattr(rec, "best_result", None) is None:
        logger.debug(f"{rec_name} 识别失败，返回None")
        return "0"
    return getattr(rec.best_result, "text", "0") or "0"


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

        param = json.loads(argv.custom_action_param or "{}")
        target_count = int(param.get("target_count", 114514))

        _TargetCountState.target_count = target_count
        _TargetCountState.already_count = 0
        _TargetCountState.current_times = 0
        _TargetCountState.candy_attempts = 0

        # 清空之前的掉落统计
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
            logger.info(
                f"准备复现 {times} 次，累计已刷 {_TargetCountState.already_count} 次"
            )
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
                    "next": [],
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
        DropRecognitionState.print_total_summary()
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

        logger.error(
            f"无法获取可复现次数，终止刷图任务，已刷 {_TargetCountState.already_count} 次"
        )
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
                logger.debug(f"尝试吃糖后体力不够，任务结束。")
                context.run_task("HomeButton")
                context.tasker.post_stop()
                return CustomAction.RunResult(success=True)

        # 开始刷图
        img = context.tasker.controller.cached_image
        reco_detail = context.run_recognition("SSCannotReplay", img)
        if reco_detail and reco_detail.hit:
            # 无法复现，直接开始任务
            context.run_task("SSNoReplay")
        else:
            # 可复现
            context.override_pipeline(
                {
                    "SetReplaysTimes": {
                        "template": [
                            f"Combat/SetReplaysTimesX1.png",
                            f"Combat/SetReplaysTimesX1_selected.png",
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

        params: dict | None = context.get_node_data("EatCandyStart")
        if not params:
            logger.error("EatCandyStart 节点不存在")
            return CustomAction.RunResult(success=False)
        # 有效期：24h, 7d, 14d, infinite
        valid_period = params.get("valid_period", "24h")
        # 最大吃糖次数：0表示无限吃
        max_times = params.get("max_times", 0)

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


class DropRecognitionState:
    """掉落识别状态"""

    drop_index: dict = {}  # 关卡掉落索引
    items_data: dict = {}  # 物品数据
    id_to_name: dict = {}  # id -> name 映射
    id_to_rarity: dict = {}  # id -> rarity 映射
    current_drops: dict = {}  # 当前战斗掉落 {item_id: count}
    total_drops: dict = {}  # 累计掉落 {item_id: count}
    _loaded: bool = False  # 是否已加载
    _user_id: str = ""  # 设备唯一标识
    _recognition_enabled: bool = False  # 是否已启用掉落识别

    API_URL = "https://mojing.org/api/insertItem"
    _version: str = ""  # M9A 版本号

    # 辅助识别物品列表（仅用于识别，不上报）
    HELPER_ITEMS: set = {203, 205, 1002}  # 经验、金币等

    # 辅助物品ID -> 名称映射（这些物品不在items.json中）
    HELPER_ITEM_NAMES: dict = {203: "利齿子儿", 205: "微尘", 1002: "启寤Ⅰ"}

    # 稀有度 -> 颜色匹配节点名映射
    RARITY_TO_COLOR_NODE = {
        "gold": "DropRarityGold",
        "yellow": "DropRarityYellow",
        "purple": "DropRarityPurple",
        "blue": "DropRarityBlue",
        "green": "DropRarityGreen",
    }

    # 稀有度 -> ANSI 颜色码 (用于终端彩色输出)
    RARITY_ANSI_COLORS = {
        "gold": "\033[93m",  # 亮黄色
        "yellow": "\033[33m",  # 黄色
        "purple": "\033[95m",  # 亮紫色
        "blue": "\033[94m",  # 亮蓝色
        "green": "\033[92m",  # 亮绿色
    }
    ANSI_RESET = "\033[0m"

    @classmethod
    def load_data(cls):
        """加载掉落数据"""
        if cls._loaded:
            return

        try:
            with open("resource/data/combat/drop_index.json", encoding="utf-8") as f:
                cls.drop_index = json.load(f)
            logger.debug(f"已加载掉落索引，共 {len(cls.drop_index)} 个关卡")
        except Exception as e:
            logger.error(f"加载 drop_index.json 失败: {e}")
            cls.drop_index = {}

        try:
            with open("resource/data/combat/items.json", encoding="utf-8") as f:
                cls.items_data = json.load(f)
            # 构建 id -> name 和 id -> rarity 映射
            cls.id_to_name = {}
            cls.id_to_rarity = {}
            for rarity, rarity_items in cls.items_data.items():
                for item_id, item_info in rarity_items.items():
                    cls.id_to_name[int(item_id)] = item_info["name"]
                    cls.id_to_rarity[int(item_id)] = rarity
            logger.debug(f"已加载物品数据，共 {len(cls.id_to_name)} 个物品")
        except Exception as e:
            logger.error(f"加载 items.json 失败: {e}")
            cls.items_data = {}
            cls.id_to_name = {}
            cls.id_to_rarity = {}

        cls._loaded = True

    @classmethod
    def get_version(cls) -> str:
        """获取 M9A 版本号"""
        if cls._version:
            return cls._version

        try:
            with open("./interface.json", "r", encoding="utf-8") as f:
                interface_data = json.load(f)
                cls._version = interface_data.get("version", "debug")
        except Exception:
            cls._version = "debug"

        return cls._version

    @classmethod
    def get_user_id(cls) -> str:
        """获取或生成设备唯一标识"""
        if cls._user_id:
            return cls._user_id

        # 尝试读取已保存的 user_id
        try:
            with open("config/user_id.txt", "r", encoding="utf-8") as f:
                cls._user_id = f.read().strip()
                if cls._user_id:
                    return cls._user_id
        except FileNotFoundError:
            pass

        # 基于 MAC 地址生成唯一 ID
        mac = uuid.getnode()
        cls._user_id = hashlib.md5(str(mac).encode()).hexdigest()[:16]

        # 保存到文件
        try:
            with open("config/user_id.txt", "w", encoding="utf-8") as f:
                f.write(cls._user_id)
        except Exception as e:
            logger.warning(f"保存 user_id 失败: {e}")

        return cls._user_id

    @classmethod
    def reset_current(cls):
        """重置当前战斗掉落"""
        cls.current_drops = {}
        cls._recognition_enabled = True  # 标记掉落识别已启用

    @classmethod
    def add_drop(cls, item_id: int, count: int = 1, is_helper: bool = False):
        """记录掉落

        Args:
            item_id: 物品ID
            count: 数量
            is_helper: 是否为辅助识别物品（辅助物品不会被记录）
        """
        if not is_helper:
            cls.current_drops[item_id] = cls.current_drops.get(item_id, 0) + count
            cls.total_drops[item_id] = cls.total_drops.get(item_id, 0) + count

    @classmethod
    def get_level_key(cls) -> str:
        """获取当前关卡的 drop_index key"""
        stage = SelectCombatStage.stage  # 如 "5-19"
        level = SelectCombatStage.level  # "Hard" 或 "Story"
        suffix = "E" if level == "Hard" else "G"
        return f"{stage}{suffix}"

    @classmethod
    def get_level_id(cls) -> str:
        """获取用于上报的 levelId，格式如 '6-4厄险'"""
        stage = SelectCombatStage.stage  # 如 "5-19"
        level = SelectCombatStage.level  # "Hard" 或 "Story"
        difficulty = "厄险" if level == "Hard" else "故事"
        return f"{stage}{difficulty}"

    @classmethod
    def get_item_name(cls, item_id: int) -> str:
        """获取物品名称，优先从items.json查找，如果找不到再从辅助物品映射查找

        Args:
            item_id: 物品ID

        Returns:
            物品名称，如果都找不到则返回ID字符串
        """
        # 先从 items.json 加载的数据中查找
        name = cls.id_to_name.get(item_id)
        if name:
            return name

        # 再从辅助物品映射中查找
        name = cls.HELPER_ITEM_NAMES.get(item_id)
        if name:
            return name

        # 都找不到，返回ID字符串
        return str(item_id)

    @classmethod
    def verify_rarity_color(cls, context, img, box, item_id: int) -> bool:
        """验证物品边框颜色是否与稀有度匹配

        Args:
            context: MaaFramework Context
            img: numpy 图像数组
            box: 物品的识别框 Rect(x, y, w, h)
            item_id: 物品 ID

        Returns:
            bool: 颜色是否匹配
        """
        rarity = cls.id_to_rarity.get(item_id)
        if not rarity or rarity not in cls.RARITY_TO_COLOR_NODE:
            return True  # 未知稀有度，跳过验证

        color_node = cls.RARITY_TO_COLOR_NODE[rarity]

        # 使用 run_recognition 进行颜色匹配
        # ROI 在物品正下方边框区域
        color_roi = [box[0] - 5, box[1] + 76, box[2] + 14, box[3] - 39]
        rec = context.run_recognition(
            color_node,
            img,
            {color_node: {"roi": color_roi}},
        )

        return rec is not None and rec.hit

    @staticmethod
    def boxes_overlap(box1, box2, threshold: float = 0.5) -> bool:
        """检测两个 box 是否重叠

        Args:
            box1, box2: Rect(x, y, w, h) 格式
            threshold: 重叠面积占较小 box 面积的比例阈值

        Returns:
            bool: 是否重叠
        """
        x1, y1, w1, h1 = box1[0], box1[1], box1[2], box1[3]
        x2, y2, w2, h2 = box2[0], box2[1], box2[2], box2[3]

        # 计算交集
        inter_x1 = max(x1, x2)
        inter_y1 = max(y1, y2)
        inter_x2 = min(x1 + w1, x2 + w2)
        inter_y2 = min(y1 + h1, y2 + h2)

        if inter_x1 >= inter_x2 or inter_y1 >= inter_y2:
            return False  # 无交集

        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        min_area = min(w1 * h1, w2 * h2)

        return inter_area / min_area >= threshold

    @staticmethod
    def filter_overlapping_matches(matches: list) -> list:
        """过滤重叠的匹配结果，保留分数最高的

        Args:
            matches: [(item_id, box, score), ...]

        Returns:
            过滤后的列表，按 x 坐标从左到右排序
        """
        if not matches:
            return []

        # 按分数降序排序（用于处理重叠时保留分数最高的）
        sorted_matches = sorted(matches, key=lambda x: x[2], reverse=True)
        result = []

        for item_id, box, score in sorted_matches:
            # 检查是否与已保留的 box 重叠
            is_overlapping = False
            for _, kept_box, _ in result:
                if DropRecognitionState.boxes_overlap(box, kept_box):
                    is_overlapping = True
                    break

            if not is_overlapping:
                result.append((item_id, box, score))

        # 按 x 坐标排序（从左到右，符合屏幕顺序）
        result.sort(key=lambda x: x[1][0])
        return result

    @staticmethod
    def filter_digit_colors(img: np.ndarray) -> np.ndarray:
        """过滤图像，只保留数字颜色（灰白色调）

        目标颜色: #D1CBCB, #CBC7C7, #938F8F, #ABA7A7 及相近颜色
        这些都是 R≈G≈B 的灰色，范围大约在 130-220
        """
        # 计算每个像素 R, G, B 的最大差值
        max_channel = np.max(img, axis=2)
        min_channel = np.min(img, axis=2)
        channel_diff = max_channel - min_channel

        # 灰色条件: R, G, B 差值小（接近灰色）
        gray_mask = channel_diff < 50

        # 亮度条件: 在目标范围内 (100-240)
        brightness = np.mean(img, axis=2)
        brightness_mask = (brightness >= 100) & (brightness <= 240)

        # 组合条件
        mask = gray_mask & brightness_mask

        # 创建过滤后的图像（匹配的变黑，不匹配的变白）
        result = np.ones_like(img) * 255  # 默认白色
        result[mask] = 0  # 匹配的像素变黑

        return result

    @classmethod
    def print_total_summary(cls):
        """输出累计掉落总结"""
        if not cls._recognition_enabled:
            # 未启用掉落识别，不显示任何提示
            return

        if not cls.total_drops:
            logger.info("本次任务无材料掉落")
            return

        logger.info("材料掉落总结:")

        # 按稀有度分组统计
        rarity_groups = {"gold": [], "purple": [], "blue": [], "green": [], "other": []}

        for item_id, count in cls.total_drops.items():
            rarity = cls.id_to_rarity.get(item_id, "other")
            if rarity not in rarity_groups:
                rarity = "other"
            rarity_groups[rarity].append((item_id, count))

        # 按稀有度顺序输出
        rarity_order = ["gold", "purple", "blue", "green", "other"]
        rarity_names = {
            "gold": "金色",
            "purple": "紫色",
            "blue": "蓝色",
            "green": "绿色",
            "other": "其他",
        }

        for rarity in rarity_order:
            items = rarity_groups[rarity]
            if not items:
                continue

            # 按数量降序排列
            items.sort(key=lambda x: x[1], reverse=True)

            logger.info(f"[{rarity_names[rarity]}]")
            for item_id, count in items:
                item_name = cls.get_item_name(item_id)
                color = cls.RARITY_ANSI_COLORS.get(rarity, "")
                reset = cls.ANSI_RESET if color else ""
                logger.info(f"  {color}{item_name}{reset} x{count}")

    @classmethod
    def reset_total(cls):
        """清空累计掉落数据"""
        cls.total_drops = {}
        cls._recognition_enabled = False  # 重置识别标记

    @classmethod
    def report_drops(cls) -> bool:
        """上报当前战斗掉落数据"""
        if not cls.current_drops:
            logger.info("本次战斗无掉落，跳过上报")
            return True

        # 构造 item 列表，过滤掉落数为 0 的物品
        items = []
        for item_id, count in cls.current_drops.items():
            if count <= 0:
                continue
            item_name = cls.get_item_name(item_id)
            items.append({"name": item_name, "num": count, "id": item_id})

        # 获取刷取次数（复现次数）
        total = (
            _TargetCountState.current_times
            if _TargetCountState.current_times > 0
            else 1
        )

        # 构造请求体
        payload = {
            "userId": cls.get_user_id(),
            "levelId": cls.get_level_id(),
            "total": total,
            "item": items,
        }

        try:
            response = requests.post(
                cls.API_URL,
                data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": f"M9A/{cls.get_version()}",
                },
                timeout=15,
                verify=False,  # 禁用 SSL 证书验证
            )
            if response.status_code in (200, 201):
                logger.debug(f"掉落上报成功: {cls.get_level_id()}, {total} 个物品")
                return True
            else:
                logger.error(
                    f"掉落上报失败: HTTP {response.status_code}, {response.text}"
                )
                return False
        except requests.RequestException as e:
            logger.error(f"掉落上报请求异常: {e}")
            return False


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

        # 加载数据
        DropRecognitionState.load_data()
        DropRecognitionState.reset_current()

        # 获取当前关卡的候选物品
        level_key = DropRecognitionState.get_level_key()
        reportable_items = DropRecognitionState.drop_index.get(level_key, [])

        if not reportable_items:
            logger.warning(f"关卡 {level_key} 没有掉落验证数据，跳过掉落识别")
            return CustomAction.RunResult(success=True)

        # 合并待上报物品和辅助识别物品
        possible_items = list(set(reportable_items) | DropRecognitionState.HELPER_ITEMS)
        helper_items = DropRecognitionState.HELPER_ITEMS

        # 识别掉落物品
        recognized_ids = set()  # 已识别的物品ID，避免重复
        recognized_reportable = False  # 是否识别到待上报物品
        max_swipe = 5  # 最大滑动次数
        rare_drop_counts = {"gold": 0, "purple": 0}  # 高价值物品计数
        screenshot_saved = False  # 是否已保存截图

        for swipe_count in range(max_swipe + 1):
            # 1. 截图
            img = context.tasker.controller.post_screencap().wait().get()

            # 2. 对每个候选物品进行模板匹配
            raw_matches = []  # [(item_id, box, score), ...]
            for item_id in possible_items:
                if item_id in recognized_ids:
                    continue  # 跳过已识别的物品

                rec = context.run_recognition(
                    "DropRegionRec",
                    img,
                    {
                        "DropRegionRec": {
                            "template": [f"Items_processed/Item-{item_id}.png"]
                        }
                    },
                )
                if rec is not None and rec.hit and getattr(rec, "box", None):
                    box = rec.box
                    # 获取匹配分数
                    score = 1.0
                    if rec.best_result:
                        score = getattr(rec.best_result, "score", 1.0)

                    # 验证稀有度颜色
                    if not DropRecognitionState.verify_rarity_color(
                        context, img, box, item_id
                    ):
                        item_name = DropRecognitionState.get_item_name(item_id)
                        rarity = DropRecognitionState.id_to_rarity.get(item_id, "?")
                        logger.debug(
                            f"颜色验证失败: {item_name} ({item_id}, {rarity}) at {box}"
                        )
                        continue

                    item_name = DropRecognitionState.get_item_name(item_id)
                    logger.debug(
                        f"模板匹配: {item_name} ({item_id}) at {box}, score={score:.3f}"
                    )
                    raw_matches.append((item_id, box, score))

            # 3. 过滤重叠匹配，保留分数最高的
            matched_items = DropRecognitionState.filter_overlapping_matches(raw_matches)

            # 4. 识别数量
            # 过滤图像颜色，只保留数字颜色（灰白色调）
            filtered_img = DropRecognitionState.filter_digit_colors(img)

            for item_id, box, _ in matched_items:
                # 判断是否为辅助识别物品
                is_helper = item_id in helper_items
                item_name = DropRecognitionState.get_item_name(item_id)

                if is_helper:
                    # 辅助物品不需要识别数量，直接记录
                    logger.debug(f"掉落(辅助): {item_name}")
                    DropRecognitionState.add_drop(item_id, 1, is_helper=True)
                    recognized_ids.add(item_id)
                    continue

                # 数量在物品右下角，调整 ROI
                count_roi = [box[0] + 12, 613, box[2] - 24, 17]
                rec = context.run_recognition(
                    "DropCountRec",
                    filtered_img,
                    {"DropCountRec": {"roi": count_roi}},
                )

                if (
                    rec is None
                    or not rec.hit
                    or getattr(rec, "best_result", None) is None
                ):
                    logger.warning(f"掉落识别中止: {item_name} 数量识别失败")
                    return CustomAction.RunResult(success=True)

                try:
                    text = getattr(rec.best_result, "text", None)
                    if not text:
                        raise ValueError("OCR 结果为空")
                    # 清理非数字字符（如 ￥5 -> 5）
                    digits = re.sub(r"\D", "", text)
                    if not digits:
                        raise ValueError(f"OCR 结果无数字: {text}")
                    count = int(digits)
                except (ValueError, AttributeError) as e:
                    logger.warning(f"掉落识别中止: {item_name} 数量解析失败 ({e})")
                    return CustomAction.RunResult(success=True)

                logger.debug(f"掉落: {item_name} x{count}")
                recognized_reportable = True

                # 累积高价值物品数量并检查是否需要保存截图（仅针对非辅助物品）
                if not is_helper:
                    rarity = DropRecognitionState.id_to_rarity.get(item_id, "")
                    if rarity in ("gold", "purple"):
                        rare_drop_counts[rarity] += count

                        # 检查是否满足保存截图的条件（金≥2 或 紫≥5）
                        should_save = (
                            rare_drop_counts["gold"] >= 2
                            or rare_drop_counts["purple"] >= 5
                        )

                        if should_save and not screenshot_saved:
                            try:
                                # 保存当前截图
                                user_id = DropRecognitionState.get_user_id()
                                timestamp = time.strftime(
                                    "%Y%m%d_%H%M%S", time.localtime()
                                )
                                dir_path = "debug/rare_drops"
                                filename = f"{dir_path}/{user_id}_{timestamp}.png"

                                # 确保目录存在
                                os.makedirs(dir_path, exist_ok=True)

                                # 将numpy数组转换为PIL Image
                                pil_image = Image.fromarray(img)
                                pil_image.save(filename, "PNG")
                                screenshot_saved = True
                                logger.info(
                                    f"检测到高价值掉落 (金{rare_drop_counts['gold']} 紫{rare_drop_counts['purple']})，已保存截图: {filename}"
                                )
                            except Exception as e:
                                logger.error(f"保存高价值掉落截图失败: {e}")

                DropRecognitionState.add_drop(item_id, count, is_helper=is_helper)
                recognized_ids.add(item_id)

            # 4. 检查是否需要滑动
            if not matched_items or swipe_count >= max_swipe:
                break  # 没有新物品或达到最大滑动次数

            # 滑动查看更多
            context.tasker.controller.post_swipe(1155, 572, 921, 571, 500).wait()
            time.sleep(0.3)  # 等待滑动动画

        # 5. 验证掉落数据合理性
        if DropRecognitionState.current_drops:
            # 统计各稀有度的掉落数量
            rarity_counts = {"gold": 0, "purple": 0, "blue": 0, "green": 0}
            for item_id, count in DropRecognitionState.current_drops.items():
                rarity = DropRecognitionState.id_to_rarity.get(item_id, "")
                if rarity in rarity_counts:
                    rarity_counts[rarity] += count

            # 验证合理范围
            valid_ranges = {
                "gold": (0, 4),  # 金材料 0-4 个
                "purple": (0, 8),  # 紫材料 0-8 个
                "blue": (0, 16),  # 蓝材料 0-16 个
                "green": (0, 28),  # 绿材料 0-28 个
            }

            is_valid = True
            for rarity, (min_count, max_count) in valid_ranges.items():
                if not (min_count <= rarity_counts[rarity] <= max_count):
                    logger.warning(
                        f"掉落数据异常: {rarity} 材料数量 {rarity_counts[rarity]} 超出合理范围 [{min_count}, {max_count}]"
                    )
                    is_valid = False

            if not is_valid:
                logger.warning("掉落数据超出合理范围，已丢弃本次数据")
                DropRecognitionState.reset_current()
                return CustomAction.RunResult(success=True)

        # 6. 输出结果并上报
        # 只要识别到任何物品（包括仅辅助物品），就算正常并上报
        if recognized_ids:
            if DropRecognitionState.current_drops:
                logger.info("掉落统计:")
                for item_id, count in DropRecognitionState.current_drops.items():
                    item_name = DropRecognitionState.get_item_name(item_id)
                    rarity = DropRecognitionState.id_to_rarity.get(item_id, "")
                    color = DropRecognitionState.RARITY_ANSI_COLORS.get(rarity, "")
                    reset = DropRecognitionState.ANSI_RESET if color else ""
                    logger.info(f"  {color}{item_name}{reset} x{count}")
            else:
                logger.info("本次掉落上报空材料列表")

            # 上报掉落数据（无论item列表是否为空）
            DropRecognitionState.report_drops()
        else:
            logger.info("未识别到任何掉落物品")

        return CustomAction.RunResult(success=True)
