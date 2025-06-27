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

            if context.run_recognition("TeamlistOpen", img) is not None:
                context.tasker.controller.post_click(target[0], target[1]).wait()
                time.sleep(1)
                flag = True
            elif context.run_recognition("TeamlistOff", img) is not None:
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

            cur_level = reco_detail.best_result.text

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SelectChapter")
class SelectChapter(CustomAction):
    """
    章节选择 。

    参数格式:
    {
        "mainStoryChapter": "第X大章",
        "mainChapter": "第X小章（原章节）"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 返回大章节
        context.run_task("ReturnMainStoryChapter", {"ReturnMainStoryChapter": {}})
        context.run_task(
            "SelectMainStoryChapter",
            {
                "SelectMainStoryChapter": {
                    "template": f"Combat/MainStoryChapter_{SelectCombatStage.mainStoryChapter}.png",
                    "next": [],
                }
            },
        )

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SelectCombatStage")
class SelectCombatStage(CustomAction):

    # 类静态变量，用于跨任务传递关卡信息
    stage = None
    stageName = None
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
        stageName = param["stageName"]
        level = param["level"]
        logger.info(f"当前关卡: {stage}, 名称: {stageName}, 难度: {level}")

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
                "EnterTheShow": {"next": ["MainChapter_X"]},
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
                "EnterTheShow": {"next": [f"ResourceChapter_{mainChapter}"]},
                "TargetStageName": {"expected": [f"{targetStageName}"]},
                "StageDifficulty": {
                    "next": [f"StageDifficulty_{level}", "TargetStageName"]
                },
            }

        context.override_pipeline(pipeline)

        SelectCombatStage.stage = stage
        SelectCombatStage.stageName = stageName
        SelectCombatStage.level = level
        SelectCombatStage.mainStoryChapter = mainStoryChapter

        return CustomAction.RunResult(success=True)
