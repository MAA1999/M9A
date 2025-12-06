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

        # 如处于章节展开状态，点击名字返回章节压缩状态
        context.run_task("ReturnMainStoryChapter")
        # 选择大章节并展开
        context.run_task(
            "SelectMainStoryChapter",
            {
                "SelectMainStoryChapter": {
                    "template": f"Combat/MainStoryChapter_{SelectCombatStage.mainStoryChapter}.png"
                }
            },
        )

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SelectCombatStage")
class SelectCombatStage(CustomAction):

    # 类静态变量，用于跨任务传递关卡信息
    stage = None
    level = None
    mainStoryChapter = None

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        param = json.loads(argv.custom_action_param)
        stage = param["stage"]
        level = param["level"]
        logger.info(f"当前关卡: {stage}, 难度: {level}")

        # 拆分关卡编号
        parts = stage.split("-")
        if len(parts) < 2:
            logger.error(f"关卡格式错误: {stage}")
            return CustomAction.RunResult(success=False)

        mainChapter = parts[0]  # 主章节编号
        targetStageName = parts[1]  # 关卡序号

        # 若关卡序号为数字，补零为两位字符串
        if targetStageName.isdigit():
            targetStageName = f"{int(targetStageName):02d}"

        # 判断是否主线章节（数字），并确定大章节编号
        if mainChapter.isdigit():
            mainStoryChapter = (
                1 if int(mainChapter) <= 7 else 2 if int(mainChapter) <= 10 else 3
            )
            # 主线关卡流程
            ppover = {
                "MainChapter_XEnter": {
                    "template": [f"Combat/MainChapter_{mainChapter}Enter.png"]
                },
                "TargetStageName": {"expected": [f"{targetStageName}"]},
                "StageDifficulty": {
                    "next": [f"StageDifficulty_{level}", "TargetStageName"]
                },
            }
        else:
            logger.error(f"错误的章节: {stage}")
            return CustomAction.RunResult(success=False)

        context.override_pipeline(ppover)

        SelectCombatStage.stage = stage
        SelectCombatStage.level = level
        SelectCombatStage.mainStoryChapter = mainStoryChapter

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("CombatTargetTimes")
class CombatTargetTimes(CustomAction):
    """

    参数格式:
    {
        "target_times": "目标次数"  # 可选，不填或为0则清空体力
    }
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

        def _get_available_count():
            img = context.tasker.controller.post_screencap().wait().get()
            remaining_ap = _safe_int(get_text_safe(img, "RecognizeRemainingAp"))
            stage_ap = _safe_int(get_text_safe(img, "RecognizeStageAp"))
            combat_times = _safe_int(get_text_safe(img, "RecognizeCombatTimes"))
            if combat_times == 0 or stage_ap == 0:
                logger.debug("识别失败，combat_times 或 stage_ap 为0")
                return 0
            stage_ap = stage_ap // combat_times
            logger.debug(f"剩余体力: {remaining_ap}, 关卡体力: {stage_ap}")
            return remaining_ap // stage_ap if stage_ap else 0

        target_times = int(json.loads(argv.custom_action_param)["target_times"])

        already_count = 0

        while True:
            available_count = _get_available_count()
            # 判断本轮最大可刷次数
            if target_times > 0:
                left_count = target_times - already_count
                times = min(4, available_count, left_count)
            else:
                times = min(4, available_count)
            if times <= 0:
                logger.debug("没体力咯，吃个糖")
                for _ in range(2):  # 最多吃两次糖，防止吃mini糖体力不够
                    context.run_task("EatCandy")

                    available_count = _get_available_count()
                    if target_times > 0:
                        left_count = target_times - already_count
                        times = min(4, available_count, left_count)
                    else:
                        times = min(4, available_count)
                    if times > 0:
                        break
                if times <= 0:
                    logger.debug(
                        f"吃糖后体力不够，任务结束。总共刷了 {already_count} 次"
                    )
                    break
            # 刷图流程
            logger.info(f"本次刷 {times} 次，累计已刷 {already_count} 次")
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

            already_count += times
            if target_times > 0 and already_count >= target_times:
                logger.debug(f"达到目标次数，任务结束。总共刷了 {already_count} 次")
                break

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
