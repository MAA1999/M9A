import re
import sys
import json
import random
from typing import Any, Dict, List, Union, Optional

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType
from utils.logger import logger


@AgentServer.custom_recognition("MultiRecognition")
class MultiRecognition(CustomRecognition):
    """
    多算法组合识别。

    参数格式：
    {
        "nodes": string[],
        "logic": {
            "type": "AND|OR|CUSTOM",
            "expression": string
        },
        "return": string|int[4]|None
    }

    字段说明：
    - nodes: 节点名称数组，按顺序对应 $0、$1、$2...
    - logic: 逻辑判断条件
      - type: 逻辑类型，默认"AND"
        - "AND": 所有节点都识别成功
        - "OR": 任意节点识别成功
        - "CUSTOM": 使用自定义表达式
      - expression: 自定义逻辑表达式，仅当type="CUSTOM"时使用
        - 使用 $0、$1、$2... 引用nodes数组中的节点
        - 使用 {NodeName} 引用其他已执行节点的识别结果
        - 支持 AND、OR、NOT 逻辑运算符和括号分组
    - return: 返回的ROI区域
      - int[4]格式: 直接返回固定坐标 [x, y, w, h]
      - string格式: 基于识别结果计算ROI表达式
        - 支持 $0、$1、$2 引用节点的识别区域
        - 支持 {NodeName} 引用其他已执行节点的识别区域
        - 支持 UNION($0,$1): 计算并集
        - 支持 INTERSECTION($0,$1): 计算交集
        - 支持 OFFSET($0,dx,dy,dw,dh): 偏移调整
        - 支持嵌套计算
    """

    def __init__(self):
        super().__init__()
        self._context: Optional[Context] = None
        self._argv: Optional[CustomRecognition.AnalyzeArg] = None
        self._external_node_cache: Optional[Dict[str, bool]] = None
        self._external_roi_cache: Optional[Dict[str, Optional[RectType]]] = None

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            self._context = context
            self._argv = argv
            # 初始化缓存
            self._external_node_cache = {}
            self._external_roi_cache = {}

            params = json.loads(argv.custom_recognition_param)
            nodes = params.get("nodes", [])
            logic = params.get("logic", {"type": "AND"})
            return_value = params.get("return", None)

            if not nodes:
                logger.error("nodes字段不能为空或空数组")
                return None

            if return_value is None or return_value == "":
                logger.error("return字段不能为空")
                return None

            # 执行每个节点的识别
            node_results = {}
            for i, node_name in enumerate(nodes):
                index_key = f"${i}"

                reco_detail = context.run_recognition(node_name, argv.image)

                if reco_detail and reco_detail.hit:
                    # 标准化ROI，将[0,0,0,0]转换为实际全屏坐标，其它不变
                    normalized_roi = self._normalize_roi(list(reco_detail.box))
                    node_results[index_key] = normalized_roi
                else:
                    node_results[index_key] = None

            # 逻辑判断
            if not self._check_logic_condition(logic, node_results):
                return None

            # ROI计算
            final_roi = self._process_return_value(return_value, node_results)
            if final_roi:
                logger.debug(f"MultiRecognition识别成功，返回ROI: {final_roi}")
                return CustomRecognition.AnalyzeResult(box=final_roi, detail={})
            else:
                return None

        except Exception as e:
            logger.error(f"MultiRecognition执行出错: {e}")
            return None

        finally:
            self._context = None
            self._argv = None
            self._external_node_cache = None
            self._external_roi_cache = None

    def _ensure_external_nodes_cached(self, node_names: List[str]) -> None:
        """
        确保指定的外部节点信息已缓存
        """
        # 确保缓存已初始化
        if self._external_node_cache is None:
            self._external_node_cache = {}
        if self._external_roi_cache is None:
            self._external_roi_cache = {}

        # 找出还未缓存的节点
        uncached_nodes = [
            name for name in node_names if name not in self._external_node_cache
        ]

        if not uncached_nodes:
            return  # 所有节点都已缓存

        task_id = self._argv.task_detail.task_id
        task_detail = self._context.tasker.get_task_detail(task_id)

        if task_detail and task_detail.nodes:
            for node_detail in reversed(task_detail.nodes):
                if node_detail.name in uncached_nodes:
                    # 缓存识别结果
                    recognition_success = (
                        node_detail.recognition is not None
                        and node_detail.recognition.box is not None
                    )
                    self._external_node_cache[node_detail.name] = recognition_success

                    # 缓存ROI
                    if recognition_success:
                        # 标准化外部节点的ROI
                        external_roi = self._normalize_roi(
                            list(node_detail.recognition.box)
                        )
                        self._external_roi_cache[node_detail.name] = external_roi
                    else:
                        self._external_roi_cache[node_detail.name] = None

                    uncached_nodes.remove(node_detail.name)

        # 对于未找到的节点，标记为失败
        for remaining_node in uncached_nodes:
            logger.warning(f"外部节点 {remaining_node} 未找到")
            self._external_node_cache[remaining_node] = False
            self._external_roi_cache[remaining_node] = None

    def _check_logic_condition(
        self,
        logic: Dict[str, Any],
        node_results: Dict[str, Optional[RectType]],
    ) -> bool:
        """检查逻辑条件是否满足"""
        logic_type = logic.get("type", "AND")

        if logic_type == "AND":
            for key, result in node_results.items():
                if result is None:
                    return False
            return True

        elif logic_type == "OR":
            for key, result in node_results.items():
                if result is not None:
                    return True
            return False

        elif logic_type == "CUSTOM":
            expression = logic.get("expression", "")
            if expression == "":
                logger.error("未提供expression")
                return False

            return self._evaluate_logic_expression(expression, node_results)

        else:
            logger.error(f"不支持的logic类型: {logic_type}")
            return False

    def _evaluate_logic_expression(
        self,
        expression: str,
        node_results: Dict[str, Optional[RectType]],
    ) -> bool:
        """计算逻辑表达式"""
        try:
            eval_expression = expression

            # 处理 {NodeName} 引用其他已执行节点
            if "{" in eval_expression:
                external_node_names = list(
                    set(re.findall(r"\{([^}]+)\}", eval_expression))
                )

                if external_node_names:
                    # 确保外部节点信息已缓存
                    self._ensure_external_nodes_cached(external_node_names)

                    # 替换外部节点引用
                    for node_name in external_node_names:
                        recognition_success = self._external_node_cache.get(
                            node_name, False
                        )
                        bool_value = "True" if recognition_success else "False"
                        eval_expression = eval_expression.replace(
                            f"{{{node_name}}}", bool_value
                        )

            # 替换 $0、$1、$2... 为对应的识别结果
            for key, result in node_results.items():
                bool_value = "True" if result is not None else "False"
                eval_expression = eval_expression.replace(key, bool_value)

            eval_expression = eval_expression.replace("AND", "and")
            eval_expression = eval_expression.replace("OR", "or")
            eval_expression = eval_expression.replace("NOT", "not")

            # 计算表达式
            result = eval(eval_expression)

            return bool(result)

        except Exception as e:
            logger.error(f"逻辑表达式计算失败: {expression}, 错误: {e}")
            return False

    def _process_return_value(
        self,
        return_value: Union[str, List[int]],
        node_results: Dict[str, Optional[RectType]],
    ) -> Optional[RectType]:
        """
        处理return值，支持直接坐标和表达式计算
        """
        try:
            if isinstance(return_value, list) and len(return_value) == 4:
                # 直接返回坐标数组 [x, y, w, h]
                try:
                    result = [int(x) for x in return_value]
                    return result
                except (ValueError, TypeError):
                    logger.error(f"return坐标格式错误: {return_value}")
                    return None

            elif isinstance(return_value, str):
                # 计算ROI表达式
                return self._calculate_roi_expression(return_value, node_results)

            else:
                logger.error(f"return值类型错误，应为int[4]或string: {return_value}")
                return None

        except Exception as e:
            logger.error(f"处理return值失败: {return_value}, 错误: {e}")
            return None

    def _calculate_roi_expression(
        self,
        expression: str,
        node_results: Dict[str, Optional[RectType]],
    ) -> Optional[RectType]:
        """
        计算ROI表达式
        """
        try:
            eval_expression = expression.strip()

            # 处理 {NodeName} 引用其他已执行节点的ROI
            if "{" in eval_expression:
                eval_expression = self._replace_external_node_rois(eval_expression)
                # 检查是否有无效ROI
                if eval_expression is None:
                    logger.warning("外部节点ROI引用失败，ROI计算失败")
                    return None

            # 替换 $0, $1, $2... 为对应的ROI坐标
            for key, roi in node_results.items():
                if roi is not None:
                    roi_str = f"[{roi[0]},{roi[1]},{roi[2]},{roi[3]}]"
                    eval_expression = eval_expression.replace(key, roi_str)
                else:
                    eval_expression = eval_expression.replace(key, "[0,0,0,0]")

            # 处理函数调用：UNION, INTERSECTION, OFFSET
            result = self._evaluate_roi_functions(eval_expression)

            if result and len(result) == 4:
                final_roi = [int(x) for x in result]

                # 统一边界处理：与全屏ROI取交集
                screen_roi = self._normalize_roi([0, 0, 0, 0])
                clipped_roi = self._calculate_intersection(final_roi, screen_roi)

                if clipped_roi == [0, 0, 0, 0]:
                    logger.warning(f"ROI计算结果完全超出屏幕范围: {final_roi}")
                    return None

                if clipped_roi != final_roi:
                    logger.debug(f"ROI结果裁剪: {final_roi} -> {clipped_roi}")

                return clipped_roi
            else:
                logger.error(f"ROI计算结果无效: {result}")
                return None

        except Exception as e:
            logger.error(f"ROI表达式计算失败: {expression}, 错误: {e}")
            return None

    def _replace_external_node_rois(self, expression: str) -> Optional[str]:
        """
        替换表达式中的 {NodeName} 为对应的ROI坐标
        """
        external_node_names = re.findall(r"\{([^}]+)\}", expression)

        if external_node_names:
            # 确保外部节点信息已缓存
            self._ensure_external_nodes_cached(external_node_names)

            # 替换外部节点ROI引用
            for node_name in external_node_names:
                roi = self._external_roi_cache.get(node_name)

                if roi is not None:
                    roi_str = f"[{roi[0]},{roi[1]},{roi[2]},{roi[3]}]"
                    expression = expression.replace(f"{{{node_name}}}", roi_str)
                else:
                    expression = expression.replace(f"{{{node_name}}}", "[0,0,0,0]")

        return expression

    def _evaluate_roi_functions(self, expression: str) -> Optional[List[int]]:
        """
        计算ROI函数表达式
        """

        # 处理嵌套函数调用，从内向外
        while True:
            # 查找最内层的函数调用
            match = re.search(r"(\w+)\(([^()]*)\)", expression)
            if not match:
                break

            func_name = match.group(1)
            func_args = match.group(2)
            full_match = match.group(0)

            # 计算函数结果
            func_result = self._execute_roi_function(func_name, func_args)
            if func_result is None:
                return None

            # 替换函数调用为结果
            result_str = (
                f"[{func_result[0]},{func_result[1]},{func_result[2]},{func_result[3]}]"
            )
            expression = expression.replace(full_match, result_str, 1)

        # 最终表达式应该是一个ROI数组
        try:
            if expression.startswith("[") and expression.endswith("]"):
                # 解析 [x,y,w,h] 格式
                coords = expression[1:-1].split(",")
                return [int(x.strip()) for x in coords]
            else:
                logger.error(f"无法解析最终ROI表达式: {expression}")
                return None
        except Exception as e:
            logger.error(f"解析最终ROI失败: {expression}, 错误: {e}")
            return None

    def _execute_roi_function(
        self, func_name: str, func_args: str
    ) -> Optional[List[int]]:
        """
        执行具体的ROI函数
        """
        try:
            args = self._parse_function_args(func_args)

            if func_name == "UNION":
                if len(args) != 2:
                    logger.error(f"UNION函数需要2个参数，得到{len(args)}个: {args}")
                    return None
                roi1 = self._parse_roi_arg(args[0])
                roi2 = self._parse_roi_arg(args[1])
                if roi1 and roi2:
                    return self._calculate_union(roi1, roi2)

            elif func_name == "INTERSECTION":
                if len(args) != 2:
                    logger.error(
                        f"INTERSECTION函数需要2个参数，得到{len(args)}个: {args}"
                    )
                    return None
                roi1 = self._parse_roi_arg(args[0])
                roi2 = self._parse_roi_arg(args[1])
                if roi1 and roi2:
                    return self._calculate_intersection(roi1, roi2)

            elif func_name == "OFFSET":
                if len(args) != 5:
                    logger.error(f"OFFSET函数需要5个参数，得到{len(args)}个: {args}")
                    return None
                roi = self._parse_roi_arg(args[0])
                if roi:
                    dx, dy, dw, dh = [int(x) for x in args[1:5]]
                    return self._calculate_offset(roi, dx, dy, dw, dh)

            else:
                logger.error(f"不支持的ROI函数: {func_name}")
                return None

        except Exception as e:
            logger.error(f"执行ROI函数失败: {func_name}({func_args}), 错误: {e}")
            return None

    def _parse_roi_arg(self, arg: str) -> Optional[List[int]]:
        """
        解析ROI参数 [x,y,w,h]
        """
        try:
            if arg.startswith("[") and arg.endswith("]"):
                coords = arg[1:-1].split(",")
                roi = [int(x.strip()) for x in coords]
                return roi
            else:
                logger.error(f"无效的ROI参数格式: {arg}")
                return None
        except Exception as e:
            logger.error(f"解析ROI参数失败: {arg}, 错误: {e}")
            return None

    def _parse_function_args(self, args_str: str) -> List[str]:
        """
        智能解析函数参数，正确处理包含方括号的ROI参数
        """
        args = []
        current_arg = ""
        bracket_count = 0

        for char in args_str:
            if char == "[":
                bracket_count += 1
                current_arg += char
            elif char == "]":
                bracket_count -= 1
                current_arg += char
            elif char == "," and bracket_count == 0:
                # 只有在方括号外的逗号才作为参数分隔符
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        # 添加最后一个参数
        if current_arg:
            args.append(current_arg.strip())

        return args

    def _calculate_union(self, roi1: List[int], roi2: List[int]) -> List[int]:
        """
        计算两个ROI的并集
        """
        x1, y1, w1, h1 = roi1
        x2, y2, w2, h2 = roi2

        if w1 == 0 and h1 == 0:
            return roi2
        elif w2 == 0 and h2 == 0:
            return roi1

        # 计算边界
        left = min(x1, x2)
        top = min(y1, y2)
        right = max(x1 + w1, x2 + w2)
        bottom = max(y1 + h1, y2 + h2)

        return [left, top, right - left, bottom - top]

    def _calculate_intersection(self, roi1: List[int], roi2: List[int]) -> List[int]:
        """
        计算两个ROI的交集
        """
        x1, y1, w1, h1 = roi1
        x2, y2, w2, h2 = roi2

        # 计算交集边界
        left = max(x1, x2)
        top = max(y1, y2)
        right = min(x1 + w1, x2 + w2)
        bottom = min(y1 + h1, y2 + h2)

        # 检查是否有交集
        if left >= right or top >= bottom:
            return [0, 0, 0, 0]

        return [left, top, right - left, bottom - top]

    def _calculate_offset(
        self, roi: List[int], dx: int, dy: int, dw: int, dh: int
    ) -> List[int]:
        """
        计算ROI偏移
        """
        x, y, w, h = roi
        new_x = x + dx
        new_y = y + dy
        new_w = w + dw
        new_h = h + dh

        return [new_x, new_y, new_w, new_h]

    def _normalize_roi(self, roi: List[int]) -> List[int]:
        """
        标准化ROI，将[0,0,0,0]转换为实际的全屏坐标
        图像缩放规则：较短边缩放到720，长边按比例缩放
        """
        if roi == [0, 0, 0, 0]:
            original_height, original_width = self._argv.image.shape[:2]

            if original_width <= original_height:
                scaled_width = 720
                scaled_height = int(original_height * (720 / original_width))
            else:
                scaled_height = 720
                scaled_width = int(original_width * (720 / original_height))

            normalized_roi = [0, 0, scaled_width, scaled_height]
            logger.debug(
                f"全屏ROI标准化: 原始尺寸({original_width}x{original_height}) -> 缩放尺寸({scaled_width}x{scaled_height})"
            )
            return normalized_roi

        return roi


@AgentServer.custom_recognition("Count")
class Count(CustomRecognition):
    """
    节点匹配次数计数器，task_id变化时自动重置

    参数格式:
    {
        "target": int,
        "recognition": dict
    }

    字段说明:
    - target: 目标匹配次数，默认sys.maxsize
    - recognition: v2协议的recognition字段
      - type: 识别类型，默认DirectHit
      - param: 识别相关字段
    """

    record = {}

    def __init__(self):
        super().__init__()
        # 生成形如 count_16位数字 的唯一标志符
        self._identifier = f"count_{random.randint(1000000000000000, 9999999999999999)}"
        # 上次使用时的 task_id
        self._pre_task_id = 0
        logger.debug(f"Count实例创建，标志符: {self._identifier}")

    @classmethod
    def reset_count(cls, node_name: Optional[str] = None) -> None:
        """
        重置计数器

        Args:
            node_name: 要重置的节点名称，如果为None则重置所有节点
        """
        if node_name is None:
            cls.record.clear()
            logger.debug("重置所有Count计数器")
        elif node_name in cls.record:
            del cls.record[node_name]
            logger.debug(f"重置Count计数器: {node_name}")
        else:
            logger.warning(f"未找到要重置的Count节点: {node_name}")

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            params = json.loads(argv.custom_recognition_param)
            if not params:
                params = {"target": sys.maxsize, "recognition": {"type": "DirectHit"}}
            target_count = params.get("target", sys.maxsize)
            recognition = params.get("recognition", {"type": "DirectHit"})

            if not isinstance(target_count, int) or target_count < 0:
                logger.error(f"无效的target值: {target_count}")
                return None

            node_name = argv.node_name

            # task_id 发生变化，重置计数器
            if argv.task_detail.task_id != self._pre_task_id:
                Count.reset_count()
                self._pre_task_id = argv.task_detail.task_id

            # 初始化节点数据
            if node_name not in Count.record:
                Count.record[node_name] = {"count": 0, "target": target_count}

            # 未达指定次数
            if Count.record[node_name]["count"] < target_count:
                context.override_pipeline(
                    {self._identifier: {"recognition": recognition}}
                )
                reco_detail = context.run_recognition(self._identifier, argv.image)

                # 识别成功
                if reco_detail and reco_detail.hit:
                    Count.record[node_name]["count"] += 1
                    # logger.debug(
                    #     f"Count识别成功: {node_name}, 当前计数: {Count.record[node_name]['count']}"
                    # )
                    return CustomRecognition.AnalyzeResult(
                        box=reco_detail.box,
                        detail={
                            "node": node_name,
                            "count": Count.record[node_name]["count"],
                        },
                    )
                else:
                    # 识别失败
                    return None
            else:
                # 已达指定次数
                return None

        except Exception as e:
            logger.error(f"Count识别失败: {e}")
            return None


@AgentServer.custom_recognition("CheckStopping")
class CheckStopping(CustomRecognition):
    """
    检查任务是否即将停止。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        if context.tasker.stopping:
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 0, 0],
                detail={"node": "CheckStopping", "stopping": True},
            )
        else:
            return None
