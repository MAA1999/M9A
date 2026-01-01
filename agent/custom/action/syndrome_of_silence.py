import re
import time
import json
import copy
import os
import ast
from typing import cast
from PIL import Image
import numpy as np

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from maa.define import NeuralNetworkDetectResult, OCRResult

from utils import logger


__all__ = [
    "SOSSelectNode",
    "SOSNodeProcess",
    "SOSSelectEncounterOption_OCR",
    "SOSSelectEncounterOption_HSV",
    "SOSShoppingList",
    "SOSBuyItems",
    "SOSSelectNoise",
    "SOSSelectInstrument",
    "SOSSwitchStat",
]


@AgentServer.custom_action("SOSSelectNode")
class SOSSelectNode(CustomAction):
    """
    节点选择
    """

    node_type, event_name = "", ""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        reco_detail = argv.reco_detail.raw_detail["best"]["detail"]

        with open("resource/data/sos/nodes.json", encoding="utf-8") as f:
            nodes = json.load(f)

        # 检查识别结果中在期望列表中的结果，保存截图用于调试
        expected_indices = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12]
        score_threshold = 0.6
        if argv.reco_detail.filtered_results:
            expected_results = [
                r
                for r in argv.reco_detail.filtered_results
                if isinstance(r, NeuralNetworkDetectResult)
                and r.cls_index in expected_indices
                and r.score < score_threshold
            ]
            if expected_results:
                img = context.tasker.controller.cached_image

                # BGR2RGB
                if len(img.shape) == 3 and img.shape[2] == 3:
                    rgb_img = img[:, :, ::-1]
                else:
                    rgb_img = img
                    logger.warning("当前截图并非三通道")

                timestamp = time.strftime("%Y%m%d_%H%M%S")
                save_dir = "debug/custom/SOSSelectNode"
                os.makedirs(save_dir, exist_ok=True)
                save_path = f"{save_dir}/{timestamp}.png"
                Image.fromarray(rgb_img).save(save_path)
                logger.debug(f"检测到低分数节点，截图已保存: {save_path}")
                for i, r in enumerate(expected_results):
                    logger.debug(
                        f"  结果{i}: 类型={nodes['types'][r.cls_index]} (cls_index={r.cls_index}), 分数={r.score:.3f}"
                    )

        # 如果 reco_detail 是字符串，解析为 dict
        if isinstance(reco_detail, str):
            try:
                reco_detail = ast.literal_eval(reco_detail)
            except (ValueError, SyntaxError):
                logger.error(f"无法解析 reco_detail: {reco_detail}")
                return CustomAction.RunResult(success=False)

        # 获取 cls_index
        if isinstance(reco_detail, dict):
            cls_index = reco_detail.get("best", {}).get("cls_index")
        elif hasattr(reco_detail, "cls_index"):
            cls_index = reco_detail.cls_index
        else:
            logger.error(
                f"无法获取 cls_index from reco_detail: {type(reco_detail)} {reco_detail}"
            )
            return CustomAction.RunResult(success=False)

        if cls_index is None:
            logger.error("cls_index 为 None")
            return CustomAction.RunResult(success=False)

        # 获取 box
        if isinstance(reco_detail, dict):
            box = reco_detail.get("best", {}).get("box")
        elif hasattr(reco_detail, "box"):
            box = reco_detail.box
        else:
            logger.error(
                f"无法获取 box from reco_detail: {type(reco_detail)} {reco_detail}"
            )
            return CustomAction.RunResult(success=False)

        if box is None:
            logger.error("box 为 None")
            return CustomAction.RunResult(success=False)

        node_type = nodes["types"][cls_index]
        if not node_type:
            logger.error(f"空的 node_type for cls_index: {cls_index}")
            return CustomAction.RunResult(success=False)
        SOSSelectNode.node_type = node_type
        logger.info(f"当前进入节点类型: {node_type}")

        times = 0
        while times < 3:
            context.run_task(
                "Click",
                {
                    "Click": {
                        "action": "Click",
                        "target": box,
                        "post_wait_freezes": {
                            "time": 500,
                            "target": [846, 555, 406, 68],
                            "timeout": 3000,
                        },
                    }
                },
            )
            img = context.tasker.controller.post_screencap().wait().get()
            rec = context.run_recognition("SOSGOTO", img)
            if rec and rec.hit:
                context.run_task("SOSGOTO")
                break
            times += 1

        event_name_roi = nodes[node_type]["event_name_roi"]

        if event_name_roi:
            # 看下当前事件名
            retry_times = 0

            while retry_times < 3:
                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition(
                    "SOSEventRec", img, {"SOSEventRec": {"roi": event_name_roi}}
                )

                if reco_detail and reco_detail.hit:
                    ocr_result = cast(OCRResult, reco_detail.best_result)
                    event = ocr_result.text
                    SOSSelectNode.event_name = event
                    logger.info(f"当前事件: {event}")
                    break
                else:
                    # 检查并处理可能的弹窗节点
                    interrupts = [
                        "SOSWarning",
                        "SOSStatsUpButton",
                        "SOSStatsUp",
                        "SOSArtefactsObtained",
                        "SOSSelectArtefact",
                        "SOSLoseArtefact",
                        "SOSStrengthenArtefact",
                        "SOSHarmonicObtained",
                        "SOSSelectHarmonic",
                        "SOSResonatorObtained",
                        "SOSSelectResonator",
                        "CloseTip",
                    ]
                    popup_handled = False

                    for interrupt in interrupts:
                        rec = context.run_recognition(interrupt, img)
                        if rec and rec.hit:
                            logger.debug(f"检测到弹窗，执行节点: {interrupt}")
                            context.run_task(interrupt)
                            retry_times = 0
                            popup_handled = True
                            break

                    if not popup_handled:
                        # 没有检测到已知弹窗，等待一下再重试
                        time.sleep(1)
                        retry_times += 1
            else:
                # 事件名识别失败，检查是否是购物契机被误识别为其他节点
                img = context.tasker.controller.post_screencap().wait().get()
                shopping_rec = context.run_recognition("SOSShopping", img)
                if shopping_rec and shopping_rec.hit:
                    logger.warning(
                        f"节点类型 {node_type} 事件名识别失败，"
                        f"但检测到购物契机界面，修正节点类型"
                    )
                    node_type = "购物契机"
                    SOSSelectNode.node_type = node_type
                    SOSSelectNode.event_name = ""
                else:
                    SOSSelectNode.event_name = ""
                    return CustomAction.RunResult(success=False)
        else:
            # 没有事件名
            SOSSelectNode.event_name = ""
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SOSNodeProcess")
class SOSNodeProcess(CustomAction):
    """
    节点处理
    """

    # 跟踪 SOSTeamSelect 的运行次数
    _sos_team_select_count = 0

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        with open("resource/data/sos/nodes.json", encoding="utf-8") as f:
            nodes = json.load(f)

        node_type, event_name = (
            SOSSelectNode.node_type,
            SOSSelectNode.event_name,
        )

        if not node_type:
            logger.error("node_type 为空")
            return CustomAction.RunResult(success=False)

        # 无 event 的处理
        if node_type in ["购物契机", "遭遇", "途中余兴", "冲突", "恶战", "巧匠之手"]:
            actions = nodes[node_type]["actions"] + [
                {"type": "RunNode", "name": "FlagInSOSMain"}
            ]
            interrupts = self._resolve_interrupts(
                nodes[node_type].get("interrupts", []), nodes
            )
        else:
            # 有 event 的处理
            if event_name not in nodes[node_type]["events"]:
                logger.error(f"未适配该事件: {event_name}")
                context.tasker.post_stop()
                return CustomAction.RunResult(success=False)

            info: dict = nodes[node_type]["events"][event_name]
            # 如果是最终难题，不添加 FlagInSOSMain
            if event_name == "最终难题":
                actions = info["actions"]
            else:
                actions = info["actions"] + [
                    {"type": "RunNode", "name": "FlagInSOSMain"}
                ]
            interrupts: list = self._resolve_interrupts(
                info.get("interrupts", []), nodes
            )

        if context.tasker.stopping:
            logger.debug("任务即将停止，跳过节点处理")
            return CustomAction.RunResult(success=True)
        for action in actions:
            if context.tasker.stopping:
                logger.debug("任务即将停止，跳过节点处理")
                return CustomAction.RunResult(success=True)
            if not self.exec_main(context, action, interrupts):
                return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=True)

    def _resolve_interrupts(self, interrupts: str | list, nodes: dict) -> list:
        """
        解析 interrupts 配置，支持 @ 引用和 + 组合
        @common_name: 引用 common_interrupts 中的配置
        @name1+@name2: 组合多个引用
        """
        if isinstance(interrupts, list):
            return interrupts

        if not isinstance(interrupts, str):
            return []

        result = []
        common = nodes.get("common_interrupts", {})

        # 支持 + 分割多个引用
        parts = interrupts.split("+")
        for part in parts:
            part = part.strip()
            if part.startswith("@"):
                ref_name = part[1:]  # 去掉 @
                if ref_name in common:
                    ref_value = common[ref_name]
                    # 如果引用的值是字符串，递归解析
                    if isinstance(ref_value, str):
                        result.extend(self._resolve_interrupts(ref_value, nodes))
                    elif isinstance(ref_value, list):
                        result.extend(ref_value)
            else:
                if part:  # 避免添加空字符串
                    result.append(part)

        return result

    def exec_main(self, context: Context, action: dict | list, interrupts: list):
        retry_times = 0
        while retry_times < 20:
            if context.tasker.stopping:
                logger.debug("任务即将停止，跳过节点处理")
                return False
            # 先尝试执行主动作
            if self.exec_action(context.clone(), action):
                return True

            # 尝试所有 interrupts
            for interrupt in interrupts:
                if context.tasker.stopping:
                    logger.debug("任务即将停止，跳过节点处理")
                    return False
                img = context.tasker.controller.post_screencap().wait().get()
                if self.exec_action(context.clone(), interrupt, img):
                    retry_times = 0
                    break

            time.sleep(1)
            retry_times += 1
        return False

    def exec_action(
        self, context: Context, action: dict | list | str, img=None
    ) -> bool:
        # 如果是字符串,说明是 interrupt 节点，识别后执行
        if isinstance(action, str):
            # 如果没有传入 img，使用 cached_image
            check_img = (
                img if img is not None else context.tasker.controller.cached_image
            )
            rec = context.run_recognition(action, check_img)
            if rec and rec.hit:
                logger.debug(f"执行中断节点: {action}")
                context.run_task(action)
                return True
        elif isinstance(action, list):
            # 对于列表，依次执行，任意一个成功即返回成功
            for act in action:
                if context.tasker.stopping:
                    logger.debug("任务即将停止，跳过节点处理")
                    return False
                if self.exec_action(context, act):
                    return True
        elif isinstance(action, dict):
            # 对于单个动作，执行并检查结果
            action_type = action.get("type")
            if action_type == "RunNode":
                name = action.get("name", "")
                if context.tasker.stopping:
                    logger.debug("任务即将停止，跳过节点处理")
                    return False
                # 如果是 SOSTeamSelect 且已经运行过，直接跳过
                if (
                    name == "SOSTeamSelect"
                    and SOSNodeProcess._sos_team_select_count > 0
                ):
                    logger.debug(f"跳过执行节点: {name}")
                    return True

                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition(name, img)
                if (
                    reco_detail
                    and reco_detail.hit
                    or reco_detail
                    and reco_detail.algorithm == "DirectHit"
                ):
                    logger.debug(f"执行节点: {name}")
                    context.run_task(entry=name)
                    # 如果是 SOSTeamSelect，增加运行计数
                    if name == "SOSTeamSelect":
                        SOSNodeProcess._sos_team_select_count += 1
                    return True
            elif action_type == "SelectOption":
                method = action.get("method")
                if method == "OCR":
                    expected_all: list[str] | str = action.get("expected", "")
                    order_by: str = action.get("order_by", "Vertical")
                    index: int = action.get("index", 0)
                    origin_node = context.get_node_data("SOSSelectOption_OCR")

                    if not origin_node:
                        logger.error("未找到原始节点 SOSSelectOption_OCR")
                        return False

                    # 将 expected 统一转为列表
                    expected_list = (
                        expected_all
                        if isinstance(expected_all, list)
                        else [expected_all]
                    )

                    # 先识别一下是否有选项界面
                    img = context.tasker.controller.post_screencap().wait().get()
                    check_reco = context.run_recognition("SOSSelectOption", img)
                    if not check_reco or not check_reco.hit:
                        return False

                    origin_node1 = context.get_node_data("SOSSelectOption")

                    pp_override = {
                        "SOSSelectOption": {
                            "next": origin_node1.get("next", []) if origin_node1 else []
                        }
                    }

                    # 为每个 expected 创建独立节点
                    for i, expected in enumerate(expected_list):
                        node_name = f"SOSSelectOption_OCR_{i}"
                        # 基于 origin_node 创建新节点（使用深拷贝）
                        new_node = copy.deepcopy(origin_node)
                        if "recognition" not in new_node:
                            new_node["recognition"] = {}
                        if "param" not in new_node["recognition"]:
                            new_node["recognition"]["param"] = {}

                        # 更新参数
                        new_node["recognition"]["param"]["expected"] = expected
                        new_node["recognition"]["param"]["order_by"] = order_by
                        new_node["recognition"]["param"]["index"] = index

                        # 添加到 pipeline_override
                        pp_override[node_name] = new_node
                        pp_override["SOSSelectOption"]["next"].append(
                            "[JumpBack]" + node_name
                        )

                    logger.debug(
                        f"执行选项选择: SelectOption (OCR), expected={expected_list}"
                    )
                    if context.tasker.stopping:
                        logger.debug("任务即将停止，跳过节点处理")
                        return False
                    context.run_task("SOSSelectOption", pipeline_override=pp_override)
                elif method == "HSV":
                    order_by = action.get("order_by", "Vertical")
                    index = action.get("index", 0)

                    # 先识别一下是否有选项界面
                    if context.tasker.stopping:
                        logger.debug("任务即将停止，跳过节点处理")
                        return False
                    img = context.tasker.controller.post_screencap().wait().get()
                    check_reco = context.run_recognition("SOSSelectOption", img)
                    if not check_reco or not check_reco.hit:
                        return False

                    origin_node = context.get_node_data("SOSSelectOption")

                    override_next = (
                        origin_node.get("next", []) if origin_node else []
                    ).copy()
                    override_next.append("[JumpBack]SOSSelectOption_HSV")

                    pp_override = {
                        "SOSSelectOption": {"next": override_next},
                        "SOSSelectOption_HSV": {
                            "recognition": {
                                "param": {
                                    "order_by": order_by,
                                    "index": index,
                                }
                            }
                        },
                    }
                    logger.debug(
                        f"执行选项选择: SelectOption (HSV), order_by={order_by}, index={index}"
                    )
                    if context.tasker.stopping:
                        logger.debug("任务即将停止，跳过节点处理")
                        return False
                    context.run_task("SOSSelectOption", pipeline_override=pp_override)
                else:
                    logger.error(f"未知的选项选择方法: {method}")
                    return False
                return True
            elif action_type == "SelectEncounterOption":
                method = action.get("method")
                if method == "OCR":
                    expected: str = action.get("expected", "")
                    order_by = action.get("order_by", "Vertical")

                    # 先识别一下是否有途中偶遇选项界面
                    time.sleep(1)
                    img = context.tasker.controller.post_screencap().wait().get()
                    check_reco = context.run_recognition(
                        "SOSSelectEncounterOptionRec_Template", img
                    )
                    if not check_reco or not check_reco.hit:
                        logger.debug("未识别到途中偶遇选项界面，跳过")
                        return False

                    logger.debug(
                        f"执行途中偶遇选项选择: SelectEncounterOption (OCR), expected={expected}"
                    )
                    if context.tasker.stopping:
                        logger.debug("任务即将停止，跳过节点处理")
                        return False
                    context.run_task(
                        "SOSSelectEncounterOption_OCR",
                        pipeline_override={
                            "SOSSelectEncounterOption_OCR": {
                                "custom_action_param": {"expected": expected}
                            },
                            "SOSSelectEncounterOptionRec_Template": {
                                "order_by": order_by
                            },
                        },
                    )
                elif method == "HSV":
                    order_by = action.get("order_by", "Vertical")
                    index = action.get("index", 0)

                    # 先识别一下是否有途中偶遇选项界面
                    if context.tasker.stopping:
                        logger.debug("任务即将停止，跳过节点处理")
                        return False
                    time.sleep(1)
                    img = context.tasker.controller.post_screencap().wait().get()
                    check_reco = context.run_recognition(
                        "SOSSelectEncounterOptionRec_Template", img
                    )
                    if not check_reco or not check_reco.hit:
                        logger.debug("未识别到途中偶遇选项界面，跳过")
                        return False

                    logger.debug(
                        f"执行途中偶遇选项选择: SelectEncounterOption (HSV), order_by={order_by}, index={index}"
                    )
                    if context.tasker.stopping:
                        logger.debug("任务即将停止，跳过节点处理")
                        return False
                    context.run_task(
                        "SOSSelectEncounterOption_HSV",
                        pipeline_override={
                            "SOSSelectEncounterOption_HSV": {
                                "custom_action_param": {"index": index}
                            },
                            "SOSSelectEncounterOptionRec_Template": {
                                "recognition": {
                                    "param": {
                                        "order_by": order_by,
                                        "index": index,
                                    }
                                }
                            },
                        },
                    )
                else:
                    logger.error(f"未知的途中偶遇选项选择方法: {method}")
                    return False
                return True
        return False


@AgentServer.custom_action("SOSSelectEncounterOption_OCR")
class SOSSelectEncounterOption_OCR(CustomAction):
    """
    局外演绎：无声综合征-途中偶遇选项内容识别-OCR版
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        expected: str = json.loads(argv.custom_action_param).get("expected")
        options: list[dict] = argv.reco_detail.raw_detail["best"]["detail"]["options"]

        for option in options:
            if expected in option["content"]:
                x, y, w, h = option["roi"]
                context.run_task(
                    "Click",
                    {
                        "Click": {
                            "action": "Click",
                            "target": [x + 20, y + 10, w - 40, h - 20],
                            "pre_delay": 0,
                            "post_delay": 1500,
                        }
                    },
                )
                return CustomAction.RunResult(success=True)
        return CustomAction.RunResult(success=False)


@AgentServer.custom_action("SOSSelectEncounterOption_HSV")
class SOSSelectEncounterOption_HSV(CustomAction):
    """
    局外演绎：无声综合征-途中偶遇选项内容识别-HSV版
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        index: int = json.loads(argv.custom_action_param).get("index", 0)
        options: list[dict] = argv.reco_detail.raw_detail["best"]["detail"]["options"]

        context.run_task(
            "Click",
            {
                "Click": {
                    "action": "Click",
                    "target": options[index]["roi"],
                    "pre_delay": 0,
                    "post_delay": 1500,
                }
            },
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SOSShoppingList")
class SOSShoppingList(CustomAction):
    """
    局外演绎：无声综合征-购物列表处理
    """

    shopping_items: dict[str, int] = {}  # 存储识别到的物品 {name: price}

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        SOSShoppingList.shopping_items = {}

        # 加载物品数据用于纠错
        with open("resource/data/sos/items.json", encoding="utf-8") as f:
            items_data = json.load(f)

        # 构建所有有效物品名的集合（造物+谐波）
        valid_names = set()
        for type_items in items_data["artefacts"].values():
            valid_names.update(type_items)
        valid_names.update(items_data["harmonics"])

        all_items = {}  # 存储所有识别到的物品 {name: price}
        skipped_items = set()  # 存储所有跳过的物品名（已售出）
        last_results = []
        retry_times = 0

        while retry_times < 5:
            # 截图
            img = context.tasker.controller.post_screencap().wait().get()
            # 只保留接近黑色的像素，其他颜色都变成白色
            # 允许 RGB 每个通道在 0-95 范围内都认为是黑色
            mask = np.all(img <= 95, axis=-1)
            # 创建一个全白图像
            processed_img = np.full_like(img, 255, dtype=np.uint8)
            # 保留暗色像素
            processed_img[mask] = img[mask]

            reco_detail = context.run_recognition("SOSShoppingListOCR", processed_img)
            if not reco_detail or not reco_detail.hit:
                retry_times += 1
                continue

            # 获取识别结果列表（已按垂直顺序排列）
            raw_detail = reco_detail.raw_detail
            current_results = raw_detail.get("filtered", []) if raw_detail else []

            # 配对物品名和价格（传入原始图像和context用于检测已售出标记）
            items, skipped = self._pair_items_and_prices(current_results, img, context)

            # 记录所有跳过的物品
            skipped_items.update(skipped)

            # 纠错并合并到总结果中
            for name, price in items.items():
                corrected_name = self._correct_item_name(name, valid_names)
                if corrected_name:
                    # 检查纠正后的名称是否在跳过列表中
                    if corrected_name in skipped_items:
                        logger.debug(
                            f"跳过已售出物品（纠错后匹配）: {name} -> {corrected_name}"
                        )
                        continue

                    # 如果纠正后的物品名已经在结果中，说明之前已经识别过
                    # 只保留价格更合理的那个（更小的价格，避免拼接价格）
                    if corrected_name in all_items:
                        # 保留价格更小的
                        if price < all_items[corrected_name]:
                            all_items[corrected_name] = price
                            logger.debug(
                                f"更新物品价格: {corrected_name} {all_items[corrected_name]} -> {price}"
                            )
                    else:
                        all_items[corrected_name] = price

            # 向下滑动
            context.run_task(
                "Swipe",
                {
                    "Swipe": {
                        "action": "Swipe",
                        "begin": [380, 459, 24, 21],
                        "end": [368, 120, 30, 27],
                        "duration": 500,
                        "post_delay": 800,
                    }
                },
            )

            # 判断是否划到底（本次识别结果和上次相同）
            if self._is_same_results(current_results, last_results):
                break

            last_results = current_results

            retry_times += 1

        logger.info(f"共识别到 {len(all_items)} 个可购买物品")
        for name, price in all_items.items():
            logger.info(f"{name}: {price}")

        # 存储到类静态变量
        SOSShoppingList.shopping_items = all_items

        return CustomAction.RunResult(success=True)

    def _pair_items_and_prices(
        self, results: list, img: np.ndarray, context: Context
    ) -> tuple[dict[str, int], set[str]]:
        """
        配对物品名和价格
        结果已按垂直顺序排列，价格在物品名下方约35-45像素处
        过滤掉已售出的物品（检测左上角"已售出"标记）

        返回: (物品字典, 跳过的物品名集合)
        """
        items = {}
        skipped = set()
        i = 0
        while i < len(results):
            current = results[i]
            current_text = current.get("text", "")
            current_box = current.get("box", [0, 0, 0, 0])
            current_y = current_box[1]

            # 判断是否为纯数字（价格）
            if current_text.isdigit():
                i += 1
                continue

            # 检查左上角是否有"已售出"标记
            # 使用 pipeline 识别"已售出"
            sold_out_reco = context.run_recognition(
                "SOSShoppingItemSoldOut",
                img,
                {
                    "SOSShoppingItemSoldOut": {
                        "roi": [
                            current_box[0] - 145,  # x: 物品名左上角往左扩展
                            current_box[1] - 17,  # y: 物品名左上角往上扩展
                            62,  # width
                            24,  # height
                        ]
                    }
                },
            )

            if sold_out_reco and sold_out_reco.hit:
                logger.debug(f"跳过已售出物品: {current_text}")
                skipped.add(current_text)
                i += 1
                continue

            # 这是物品名，查找其对应的价格
            price = None
            if i + 1 < len(results):
                next_item = results[i + 1]
                next_text = next_item.get("text", "")
                next_y = next_item.get("box", [0, 0, 0, 0])[1]

                # 检查下一个是否为价格（纯数字且y坐标差在合理范围内）
                y_diff = next_y - current_y
                if next_text.isdigit() and 30 <= y_diff <= 50:
                    price_value = int(next_text)
                    # 过滤异常价格（防止拼接价格）
                    # 游戏中单个物品价格通常不超过1000
                    if price_value <= 1000:
                        price = price_value

            if price:
                items[current_text] = price

            i += 1

        return items, skipped

    def _correct_item_name(self, name: str, valid_names: set) -> str:
        """
        纠正识别错误的物品名
        使用编辑距离找到最相似的有效名称
        """
        if name in valid_names:
            return name

        # 计算与所有有效名称的相似度
        def edit_distance(s1: str, s2: str) -> int:
            """计算编辑距离"""
            if len(s1) < len(s2):
                return edit_distance(s2, s1)
            if len(s2) == 0:
                return len(s1)

            previous_row = range(len(s2) + 1)
            for i, c1 in enumerate(s1):
                current_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = previous_row[j + 1] + 1
                    deletions = current_row[j] + 1
                    substitutions = previous_row[j] + (c1 != c2)
                    current_row.append(min(insertions, deletions, substitutions))
                previous_row = current_row

            return previous_row[-1]

        # 找最相似的名称
        min_distance = float("inf")
        best_match = None

        for valid_name in valid_names:
            distance = edit_distance(name, valid_name)
            # 只接受距离小于名称长度一半的匹配
            if distance < min_distance and distance <= len(name) // 2:
                min_distance = distance
                best_match = valid_name

        if best_match:
            if best_match != name:
                logger.debug(f"纠正物品名: {name} -> {best_match}")
            return best_match

        logger.warning(f"未找到匹配的物品名: {name}")
        return name  # 返回原名称

    def _is_same_results(self, current: list, last: list) -> bool:
        """
        判断两次识别结果是否相同（通过文本内容比较）
        """
        if not last:
            return False

        current_texts = {item.get("text", "") for item in current}
        last_texts = {item.get("text", "") for item in last}

        # 如果有80%以上的内容相同，认为到底了
        if not current_texts or not last_texts:
            return False

        intersection = current_texts & last_texts
        return len(intersection) / len(current_texts) >= 0.8


@AgentServer.custom_action("SOSBuyItems")
class SOSBuyItems(CustomAction):
    """
    局外演绎：无声综合征-购买物品
    根据当前金雀子儿和商品列表，尽可能多地购买物品
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        # 获取 interrupts 配置（购买后可能出现的弹窗）
        interrupts = [
            "SOSLoseArtefact",
            "SOSStrengthenArtefact",
            "SOSWarning",
            "SOSStatsUpButton",
            "SOSStatsUp",
            "CloseTip",
        ]

        # 识别右上角当前金雀子儿
        img = context.tasker.controller.post_screencap().wait().get()
        money_roi = [1125, 18, 88, 28]  # 右上角金雀子儿的ROI，需要根据实际调整

        reco_detail = context.run_recognition(
            "OCR",
            img,
            {"OCR": {"recognition": "OCR", "roi": money_roi, "expected": r"\d{1,5}"}},
        )

        if not reco_detail or not reco_detail.hit:
            logger.error("无法识别当前金雀子儿")
            return CustomAction.RunResult(success=False)

        ocr_result = cast(OCRResult, reco_detail.best_result)
        money_text = ocr_result.text

        # 提取数字
        money_match = re.search(r"\d+", money_text)
        if not money_match:
            logger.error(f"无法从文本中提取金雀子儿数量: {money_text}")
            return CustomAction.RunResult(success=False)

        current_money = int(money_match.group())
        logger.info(f"当前金雀子儿: {current_money}")

        # 获取购物清单
        shopping_items = SOSShoppingList.shopping_items
        if not shopping_items:
            logger.warning("购物清单为空")
            return CustomAction.RunResult(success=True)

        # 加载物品优先级配置（可选）
        try:
            with open("resource/data/sos/items.json", encoding="utf-8") as f:
                items_data = json.load(f)
            # 可以在这里定义优先级逻辑，暂时按价格升序排列（买便宜的，数量更多）
        except:
            pass

        # 第一阶段：遍历所有页面，收集所有可购买物品及其位置信息

        # 先滑动到顶部
        for _ in range(3):
            context.run_task(
                "Swipe",
                {
                    "Swipe": {
                        "action": "Swipe",
                        "begin": [368, 120, 30, 27],
                        "end": [380, 459, 24, 21],
                        "duration": 500,
                        "post_delay": 500,
                    }
                },
            )

        all_buyable_items = (
            []
        )  # 存储所有可购买的物品: [(item_name, item_price, page_index, result), ...]
        last_screen_texts = set()
        page_index = 0
        max_scroll_times = 3

        while page_index < max_scroll_times:
            # 截图并识别当前屏幕的物品
            img = context.tasker.controller.post_screencap().wait().get()
            reco_detail = context.run_recognition("SOSShoppingListOCR", img)

            if not reco_detail or not reco_detail.hit:
                page_index += 1
                context.run_task(
                    "Swipe",
                    {
                        "Swipe": {
                            "action": "Swipe",
                            "begin": [380, 459, 24, 21],
                            "end": [368, 120, 30, 27],
                            "duration": 500,
                            "post_delay": 500,
                        }
                    },
                )
                continue

            raw_detail = reco_detail.raw_detail
            current_results = raw_detail.get("filtered", []) if raw_detail else []

            # 获取当前屏幕的物品文本集合
            current_screen_texts = {
                item.get("text", "")
                for item in current_results
                if not item.get("text", "").isdigit()
            }

            # 判断是否到达底部（与上一屏内容80%相同）
            if last_screen_texts:
                intersection = current_screen_texts & last_screen_texts
                if (
                    current_screen_texts
                    and len(intersection) / len(current_screen_texts) >= 0.8
                ):
                    break

            last_screen_texts = current_screen_texts

            # 使用黑色过滤后的图像再次识别，以检查价格是否可见（红色价格会被过滤）
            mask = np.all(img <= 95, axis=-1)
            # 创建一个全白图像
            processed_img = np.full_like(img, 255, dtype=np.uint8)
            # 保留暗色像素
            processed_img[mask] = img[mask]
            price_reco_detail = context.run_recognition(
                "SOSShoppingListOCR", processed_img
            )

            # 获取可见价格的物品名集合（金雀子儿足够的物品）
            affordable_items = set()
            if price_reco_detail and price_reco_detail.hit:
                price_raw_detail = price_reco_detail.raw_detail
                price_results = (
                    price_raw_detail.get("filtered", []) if price_raw_detail else []
                )

                # 配对物品名和价格，只有能配对成功的说明价格可见
                i = 0
                while i < len(price_results):
                    current = price_results[i]
                    current_text = current.get("text", "")

                    if current_text.isdigit():
                        i += 1
                        continue

                    if i + 1 < len(price_results):
                        next_item = price_results[i + 1]
                        next_text = next_item.get("text", "")

                        if next_text.isdigit():
                            affordable_items.add(current_text)

                    i += 1

            # 收集当前屏幕的可购买物品
            for result in current_results:
                text = result.get("text", "")
                # 检查是否是购物清单中的物品，且价格可见（买得起）
                for item_name, item_price in shopping_items.items():
                    if (
                        (item_name in text or text in item_name)
                        and item_price <= current_money
                        and text in affordable_items
                    ):
                        all_buyable_items.append(
                            (item_name, item_price, page_index, result)
                        )
                        break

            # 向下滑动到下一页
            page_index += 1
            context.run_task(
                "Swipe",
                {
                    "Swipe": {
                        "action": "Swipe",
                        "begin": [380, 459, 24, 21],
                        "end": [368, 120, 30, 27],
                        "duration": 500,
                        "post_delay": 500,
                    }
                },
            )

        # 第二阶段：按价格排序，使用贪心算法决定购买哪些物品

        # 去重：同一物品可能在多个页面出现，只保留第一次出现的
        seen_items = {}
        for item_name, item_price, page_idx, result in all_buyable_items:
            if item_name not in seen_items:
                seen_items[item_name] = (item_price, page_idx, result)

        # 按价格从低到高排序（贪心策略：买便宜的，数量更多）
        sorted_buyable = sorted(seen_items.items(), key=lambda x: x[1][0])

        # 计算购买方案
        purchase_plan = []
        remaining_money = current_money
        for item_name, (item_price, page_idx, result) in sorted_buyable:
            if item_price <= remaining_money:
                purchase_plan.append((item_name, item_price, page_idx, result))
                remaining_money -= item_price

        # 第三阶段：按页面顺序执行购买

        # 先回到顶部
        for _ in range(3):
            context.run_task(
                "Swipe",
                {
                    "Swipe": {
                        "action": "Swipe",
                        "begin": [368, 120, 30, 27],
                        "end": [380, 459, 24, 21],
                        "duration": 500,
                        "post_delay": 500,
                    }
                },
            )

        # 按页面索引分组
        purchase_by_page = {}
        for item_name, item_price, page_idx, result in purchase_plan:
            if page_idx not in purchase_by_page:
                purchase_by_page[page_idx] = []
            purchase_by_page[page_idx].append((item_name, item_price, result))

        purchased_items = []
        current_page = 0

        for page_idx in sorted(purchase_by_page.keys()):
            # 滑动到目标页面
            while current_page < page_idx:
                context.run_task(
                    "Swipe",
                    {
                        "Swipe": {
                            "action": "Swipe",
                            "begin": [380, 459, 24, 21],
                            "end": [368, 120, 30, 27],
                            "duration": 500,
                            "post_delay": 500,
                        }
                    },
                )
                current_page += 1

            # 购买该页面的所有物品
            for item_name, item_price, result in purchase_by_page[page_idx]:
                if self._buy_item_on_screen(context, item_name, result, interrupts):
                    purchased_items.append((item_name, item_price))
                    logger.info(f"购买成功: {item_name} ({item_price})")
                else:
                    logger.warning(f"购买失败: {item_name}")

        total_spent = sum(price for _, price in purchased_items)
        logger.info(f"购买完成，共购买 {len(purchased_items)} 件物品")
        logger.info(f"花费: {total_spent}, 剩余: {current_money - total_spent}")

        return CustomAction.RunResult(success=True)

    def _buy_item_on_screen(
        self, context: Context, item_name: str, result: dict, interrupts: list
    ) -> bool:
        """
        购买当前屏幕上的指定物品
        interrupts: 购买后可能出现的弹窗节点列表
        """
        box = result.get("box", [0, 0, 0, 0])

        # 点击物品名称区域
        context.run_task(
            "Click",
            {
                "Click": {
                    "action": "Click",
                    "target": box,
                    "post_delay": 500,
                }
            },
        )

        # 确认左侧已选中该物品
        time.sleep(0.3)
        img = context.tasker.controller.post_screencap().wait().get()

        selected_reco = context.run_recognition(
            "SOSShoppingItemSelected",
            img,
            {"SOSShoppingItemSelected": {"roi": [box[0] - 150, box[1] - 6, 35, 100]}},
        )

        if not selected_reco or not selected_reco.hit:
            logger.warning(f"左侧未确认选中物品: {item_name}")
            return False

        # 点击右下角的购买按钮
        time.sleep(0.2)
        img = context.tasker.controller.post_screencap().wait().get()

        # 先检查是否已购买
        bought_roi = [1114, 647, 76, 35]
        bought_reco = context.run_recognition(
            "OCR",
            img,
            {"OCR": {"recognition": "OCR", "roi": bought_roi}},
        )

        if bought_reco and bought_reco.hit:
            ocr_result = cast(OCRResult, bought_reco.best_result)
            button_text = ocr_result.text

            if "已购买" in button_text or "已购" in button_text:
                logger.info(f"物品已购买: {item_name}")
                return True

        # 检查购买按钮并点击
        buy_button_reco = context.run_recognition("SOSBuyButton", img)
        if buy_button_reco and buy_button_reco.hit:
            # 最多重试5次购买
            buy_retry = 0
            while buy_retry < 3:
                context.run_task("SOSBuyButton")

                # 先处理可能出现的弹窗
                time.sleep(0.5)
                self._handle_interrupts(context, interrupts)

                # 弹窗处理完后，检查是否购买成功
                time.sleep(0.3)
                img = context.tasker.controller.post_screencap().wait().get()
                confirm_reco = context.run_recognition(
                    "OCR",
                    img,
                    {"OCR": {"recognition": "OCR", "roi": bought_roi}},
                )

                if confirm_reco and confirm_reco.hit:
                    ocr_result = cast(OCRResult, confirm_reco.best_result)
                    confirm_text = ocr_result.text

                    if "已购买" in confirm_text or "已购" in confirm_text:
                        return True
                    else:
                        buy_retry += 1
                else:
                    buy_retry += 1

            logger.error(f"购买失败，已重试3次: {item_name}")
            return False
        else:
            logger.warning(f"未找到购买按钮")
            return False

    def _handle_interrupts(self, context: Context, interrupts: list) -> None:
        """
        处理购买后可能出现的弹窗
        interrupts: 弹窗节点名称列表
        """
        if not interrupts:
            return

        max_attempts = 3
        for _ in range(max_attempts):
            time.sleep(1.5)
            img = context.tasker.controller.post_screencap().wait().get()

            # 检查每个可能的弹窗
            for interrupt in interrupts:
                rec = context.run_recognition(interrupt, img)
                if rec and rec.hit:
                    logger.debug(f"检测到弹窗，执行节点: {interrupt}")
                    context.run_task(interrupt)
                    # 执行后重新开始检测，可能有连续弹窗
                    break
            else:
                # 没有检测到任何弹窗，退出
                break


@AgentServer.custom_action("SOSSelectNoise")
class SOSSelectNoise(CustomAction):
    """
    局外演绎：无声综合征-选择噪音类型
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        level: int = json.loads(argv.custom_action_param)["level"]

        levels = ["当前", "颤动 Ⅰ", "颤动 Ⅱ", "嗡鸣 Ⅰ", "嗡鸣 Ⅱ"]

        logger.info(f"选择噪音类型: {levels[level]}")
        if level == 0:
            return CustomAction.RunResult(success=True)

        # 判断当前页面
        img = context.tasker.controller.cached_image
        reco_detail = context.run_recognition(
            "OCR",
            img,
            {
                "OCR": {
                    "recognition": "OCR",
                    "roi": [343, 427, 84, 46],
                    "expected": ".*",
                }
            },
        )
        if reco_detail and reco_detail.hit:
            ocr_result = cast(OCRResult, reco_detail.best_result)
            current_level_text = ocr_result.text
            page = 1 if "颤动" in current_level_text else 2
        else:
            logger.error("无法识别当前噪音类型页面")
            return CustomAction.RunResult(success=False)

        # 到目标页面
        while True:
            if page == 1 and level >= 3:
                context.run_task(
                    "Click",
                    {
                        "Click": {
                            "action": "Click",
                            "target": [1070, 297, 38, 67],
                            "post_delay": 500,
                        }
                    },
                )
                # 更新页面状态
                time.sleep(0.5)
                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition(
                    "OCR",
                    img,
                    {
                        "OCR": {
                            "recognition": "OCR",
                            "roi": [343, 427, 84, 46],
                            "expected": ".*",
                        }
                    },
                )
                if reco_detail and reco_detail.hit:
                    ocr_result = cast(OCRResult, reco_detail.best_result)
                    current_level_text = ocr_result.text
                    page = 1 if "颤动" in current_level_text else 2
                continue
            elif page == 2 and level < 3:
                context.run_task(
                    "Click",
                    {
                        "Click": {
                            "action": "Click",
                            "target": [121, 295, 37, 63],
                            "post_delay": 500,
                        }
                    },
                )
                # 更新页面状态
                time.sleep(0.5)
                img = context.tasker.controller.post_screencap().wait().get()
                reco_detail = context.run_recognition(
                    "OCR",
                    img,
                    {
                        "OCR": {
                            "recognition": "OCR",
                            "roi": [343, 427, 84, 46],
                            "expected": ".*",
                        }
                    },
                )
                if reco_detail and reco_detail.hit:
                    ocr_result = cast(OCRResult, reco_detail.best_result)
                    current_level_text = ocr_result.text
                    page = 1 if "颤动" in current_level_text else 2
                continue
            break

        # 选择目标噪音
        roi = [[735, 194, 221, 221], [288, 187, 221, 221]][level % 2]

        context.run_task(
            "SOSNoiseSelect",
            {"SOSNoiseSelected": {"roi": roi}, "SOSNoiseUnselected": {"roi": roi}},
        )

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SOSSelectInstrument")
class SOSSelectInstrument(CustomAction):
    """
    局外演绎：无声综合征-选择配器类型
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        instrument: str = json.loads(argv.custom_action_param)["instrument"]

        logger.info(f"选择配器类型: {instrument}")

        instrument_map = {"管钟": "TubularBell", "拨弦": "Strings"}

        context.run_task(
            "SOSInstrumentSelect",
            {
                "SOSInstrumentSelect": {"expected": instrument},
                "SOSInstrumentSelectFinished": {
                    "template": f"SyndromeOfSilence/{instrument_map[instrument]}.png"
                },
            },
        )

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SOSSwitchStat")
class SOSSwitchStat(CustomAction):
    """
    局外演绎：无声综合征-切换待提升的属性
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        img = context.tasker.controller.cached_image

        context = context.clone()

        num_rois = [
            [444, 161, 53, 43],
            [599, 256, 52, 43],
            [544, 455, 52, 42],
            [223, 455, 53, 42],
            [169, 258, 52, 43],
        ]
        stat_icon_rois = [
            [378, 176, 53, 43],
            [534, 285, 53, 43],
            [471, 469, 53, 43],
            [280, 471, 52, 43],
            [219, 287, 52, 43],
        ]
        stat_names = ["力量", "反应", "奥秘", "感知", "激情"]

        results = []
        for i, roi in enumerate(num_rois):
            reco_detail = context.run_recognition(
                "OCR",
                img,
                {"OCR": {"recognition": "OCR", "roi": roi, "expected": r"\d"}},
            )
            if not reco_detail or not reco_detail.hit:
                logger.warning(f"无法识别属性数值: {stat_names[i]}")
                results.append(13)
                continue
            ocr_result = cast(OCRResult, reco_detail.best_result)
            results.append(int(ocr_result.text))

        # 选择数值最小的属性
        target_stat = stat_names[results.index(min(results))]
        logger.info(f"切换属性为: {target_stat}")
        context.run_action(
            "Click",
            pipeline_override={
                "Click": {
                    "action": "Click",
                    "target": stat_icon_rois[results.index(min(results))],
                }
            },
        )

        return CustomAction.RunResult(success=True)
