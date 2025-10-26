import re
import json
import time

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

        if reco_detail is not None:
            text = reco_detail.best_result.text
            pattern = "(\\d)/4"
            times = int(re.search(pattern, text).group(1))
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
                                "next": ["HomeFlag", "PsychubeVictory"],
                                "interrupt": [
                                    "HomeButton",
                                    "CombatEntering",
                                    "HomeLoading",
                                ],
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

        if (
            context.run_recognition(
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
            is not None
            or context.run_recognition(
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
            is not None
        ):
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

                if (
                    context.run_recognition(
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
                    is not None
                ):
                    context.tasker.controller.post_click(target[0], target[1]).wait()
                    time.sleep(1)
                    flag = True
                elif (
                    context.run_recognition(
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
                    is not None
                ):
                    context.tasker.controller.post_click(965, 650).wait()
                    time.sleep(1)
        elif (
            context.run_recognition(
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
            is not None
        ):
            # 新版
            flag = False
            team_names, team_uses = [], {}
            while not flag:

                img = context.tasker.controller.post_screencap().wait().get()

                if (
                    context.run_recognition(
                        "TeamlistOpen",
                        img,
                        {
                            "TeamlistOpen": {
                                "recognition": {
                                    "param": {
                                        "roi": [36, 63, 137, 141],
                                        "template": "Combat/TeamList_Open.png",
                                    },
                                }
                            }
                        },
                    )
                    is not None
                ):
                    # 识别到在队伍选择界面
                    time.sleep(2)  # 等待界面稳定
                    img = context.tasker.controller.post_screencap().wait().get()
                    reco_result = context.run_recognition("TeamListEditRoi", img)
                    if reco_result is None or not reco_result.filterd_results:
                        logger.error("未识别到成员队列")
                        return CustomAction.RunResult(success=False)
                    else:
                        # 识别到每个队伍左上角标志，获取每个队伍的名称和按键位置
                        team_rois = reco_result.filterd_results
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
                            team_name = reco_detail.best_result.text
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
                            team_use_text, team_use_roi = (
                                reco_detail.best_result.text,
                                reco_detail.best_result.box,
                            )
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
                                flag = True
                                context.run_task("BackButton")
                                time.sleep(1)
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

                                    if reco_detail and reco_detail.box:
                                        break

                                flag = True
                                break
                elif (
                    context.run_recognition(
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
                    is not None
                ):
                    # 识别到不在队伍选择界面，点击打开
                    context.tasker.controller.post_click(965, 650).wait()
                    time.sleep(1)
        else:
            logger.debug("未识别到队伍选择界面")
            return CustomAction.RunResult(success=False)

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

        if reco_detail is None or not any(
            difficulty in reco_detail.best_result.text for difficulty in valid_levels
        ):
            logger.warning("未识别到当前难度")
            return CustomAction.RunResult(success=False)

        text = reco_detail.best_result.text

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

        if not level or level not in valid_levels:
            logger.error("目标难度不存在")
            return CustomAction.RunResult(success=False)

        img = context.tasker.controller.post_screencap().wait().get()
        reco_detail = context.run_recognition("ActivityTargetLevelRec", img)

        if reco_detail is None or not any(
            difficulty in reco_detail.best_result.text for difficulty in valid_levels
        ):
            logger.warning("未识别到当前难度")
            return CustomAction.RunResult(success=False)

        cur_level = reco_detail.best_result.text

        retry = 0

        while cur_level != level:
            retry += 1
            if retry > 10:
                logger.error("切换难度失败，超过最大重试次数，请检查选择难度是否正确")
                return CustomAction.RunResult(success=False)
            if cur_level == "故事":
                context.tasker.controller.post_click(1190, 245).wait()
                time.sleep(0.5)
            elif cur_level == "艰难":
                context.tasker.controller.post_click(945, 245).wait()
                time.sleep(0.5)
            else:
                if level == "故事":
                    context.tasker.controller.post_click(945, 245).wait()
                    time.sleep(0.5)
                else:
                    context.tasker.controller.post_click(1190, 245).wait()
                    time.sleep(0.5)

            img = context.tasker.controller.post_screencap().wait().get()
            reco_detail = context.run_recognition("ActivityTargetLevelRec", img)

            if reco_detail:
                cur_level = reco_detail.best_result.text
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
            if (
                context.run_recognition(
                    "SelectMainStoryChapter",
                    img,
                    {
                        "SelectMainStoryChapter": {
                            "template": f"Combat/MainStoryChapter_{SelectCombatStage.mainStoryChapter}.png"
                        }
                    },
                )
                is None
                or count >= 5
            ):
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
        # stageName = param["stageName"]
        level = param["level"]
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


@AgentServer.custom_action("TargetCount")
class TargetCount(CustomAction):
    """
    清空体力或按次数刷图。

    参数格式:
    {
        "target_count": "目标次数"  # 可选，不填或为0则清空体力
    }
    """

    @classmethod
    def _safe_int(cls, text):
        try:
            return int(text)
        except Exception:
            return 0

    @classmethod
    def get_text_safe(cls, context, img, rec_name):
        rec = context.run_recognition(rec_name, img)
        if rec is None or getattr(rec, "best_result", None) is None:
            logger.debug(f"{rec_name} 识别失败，返回None")
            return "0"
        return getattr(rec.best_result, "text", "0") or "0"

    @classmethod
    def _get_available_count(cls, context):
        img = context.tasker.controller.post_screencap().wait().get()
        remaining_ap = cls._safe_int(
            cls.get_text_safe(context, img, "RecognizeRemainingAp")
        )
        stage_ap = cls._safe_int(cls.get_text_safe(context, img, "RecognizeStageAp"))
        combat_times = cls._safe_int(
            cls.get_text_safe(context, img, "RecognizeCombatTimes")
        )
        if combat_times == 0 or stage_ap == 0:
            logger.debug("识别失败，combat_times 或 stage_ap 为0")
            return 999
        stage_ap = stage_ap // combat_times
        logger.debug(f"剩余体力: {remaining_ap}, 关卡体力: {stage_ap}")
        return remaining_ap // stage_ap if stage_ap else 0

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        target_count = int(json.loads(argv.custom_action_param)["target_count"])

        already_count = 0

        while True:
            available_count = TargetCount._get_available_count(context)
            if available_count == 999:
                logger.debug("识别失败，任务结束")
                return CustomAction.RunResult(success=False)
            # 判断本轮最大可刷次数
            if target_count > 0:
                left_count = target_count - already_count
                times = min(4, available_count, left_count)
            else:
                times = min(4, available_count)
            if times <= 0:
                logger.debug("没体力咯，吃个糖")
                for _ in range(2):  # 最多吃两次糖，防止吃mini糖体力不够
                    context.run_task("EatCandy")

                    available_count = TargetCount._get_available_count(context)
                    if available_count == 999:
                        logger.debug("识别失败，任务结束")
                        return CustomAction.RunResult(success=False)
                    if target_count:
                        left_count = target_count - already_count
                        times = min(4, available_count, left_count)
                    else:
                        times = min(4, available_count)
                    if times > 0:
                        break
                if times <= 0:
                    logger.debug(
                        f"尝试吃糖后体力不够，任务结束。总共刷了 {already_count} 次"
                    )
                    break
            # 刷图流程
            logger.info(f"本次刷 {times} 次，累计已刷 {already_count} 次")
            context.override_pipeline(
                {
                    "StartReplay": {"action": "Click", "next": ["Replaying"]},
                    "SetReplaysTimes": {
                        "template": [
                            f"Combat/SetReplaysTimesX{times}.png",
                            f"Combat/SetReplaysTimesX{times}_selected.png",
                        ]
                    },
                }
            )
            context.run_task("OpenReplaysTimes")

            already_count += times
            if target_count > 0 and already_count >= target_count:
                logger.debug(f"达到目标次数，任务结束。总共刷了 {already_count} 次")
                break

        logger.info(f"任务结束，总共刷了 {already_count} 次")
        context.run_task("HomeButton")
        return CustomAction.RunResult(success=True)


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

        # 判断当前页面类型（有/无复现）
        img = context.tasker.controller.cached_image
        reco_detail = context.run_recognition("Has_Replay", img)

        if reco_detail is not None:
            context.run_task("SSToReplayIfCan")
            # 看看吃不吃糖
            available_count = TargetCount._get_available_count(context)
            if available_count == 999:
                logger.debug("识别失败，任务结束")
            elif available_count <= 0:
                logger.debug("没体力咯，吃个糖")
                for _ in range(2):  # 最多吃两次糖，防止吃mini糖体力不够
                    context.run_task("EatCandy")

                    available_count = TargetCount._get_available_count(context)
                    if available_count == 999:
                        logger.debug("识别失败，任务结束")
                        return CustomAction.RunResult(success=False)
                    elif available_count > 0:
                        break
                if available_count <= 0:
                    logger.debug(f"尝试吃糖后体力不够，任务结束。")
                    context.run_task("HomeButton")
                    return CustomAction.RunResult(success=False)

            # 开始刷图
            reco_detail = context.run_recognition("SSCannotReplay", img)
            if reco_detail is not None:
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
        else:
            context.run_task("SSNoReplay")

        return CustomAction.RunResult(success=True)
