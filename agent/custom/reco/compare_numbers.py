import re
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from utils.maa_types import is_hit, ocr_text
from utils.params import parse_params

_OPERATORS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@AgentServer.custom_recognition("CompareNumbers")
class CompareNumbers(CustomRecognition):
    """通用数字比较识别。

    从 OCR 文本中提取数字，按指定运算符比较，命中时返回比较结果。

    参数格式：
    {
        "roi": [x, y, w, h],       // OCR 区域（必填）
        "operator": "<",            // 比较运算符（必填）：< <= > >= == !=
        "value": 30,               // 固定值（可选）：传此值则与它比，否则两数互比
        "pattern": "...",           // 自定义正则（可选）：两个捕获组提取数字
        "separator": "/",           // 分隔符（可选）：自动构建正则 (\\d+)\\s*X\\s*(\\d+)
        "split_at": 2               // 分割位数（可选）：只找到一个数时按此位数切开
    }

    提取优先级：pattern > separator > 自动模式
    自动模式：提取文本中所有数字序列，取前两个；仅一个时按 split_at 切开。

    返回 detail:
    {
        "ocr_text": "25/30",       // OCR 原始文本
        "first": 25,               // 提取的第一个数字
        "second": 30,              // 提取的第二个数字（或 value 值）
        "operator": "<",           // 比较运算符
        "result": true,            // 比较结果
        "reason": ""               // 不命中时说明原因
    }

    命中时 box 为 OCR 文本实际位置，不命中时 box 为 None。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult | None:
        params = parse_params(argv.custom_recognition_param, "roi", "operator")
        roi = params["roi"]
        operator = params["operator"]

        if operator not in _OPERATORS:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": f"不支持的运算符: {operator}"},
            )

        value: Any = params.get("value")
        pattern: str | None = params.get("pattern")
        separator: str | None = params.get("separator")
        split_at: int | None = params.get("split_at")

        # 1. OCR
        ocr_detail = context.run_recognition(
            "OCR",
            argv.image,
            {"OCR": {"recognition": "OCR", "roi": roi, "expected": ".+", "only_rec": True}},
        )
        if not is_hit(ocr_detail):
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "OCR 未识别到文本"},
            )

        text = ocr_text(ocr_detail)
        if not text:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={"reason": "OCR 返回空文本"},
            )

        # 2. 提取数字
        numbers = self._extract_numbers(text, pattern, separator, split_at)
        if numbers is None:
            return CustomRecognition.AnalyzeResult(
                box=None,
                detail={
                    "ocr_text": text,
                    "reason": f"无法从文本中提取两个数字: {text}",
                },
            )

        first, second = numbers

        # 3. 比较
        if value is not None:
            result = _OPERATORS[operator](first, value)
            second = value
        else:
            result = _OPERATORS[operator](first, second)

        detail: dict[str, Any] = {
            "ocr_text": text,
            "first": first,
            "second": second,
            "operator": operator,
            "result": result,
        }

        if not result:
            detail["reason"] = f"比较结果不满足: {first} {operator} {second} = false"
            return CustomRecognition.AnalyzeResult(box=None, detail=detail)

        return CustomRecognition.AnalyzeResult(
            box=ocr_detail.box,
            detail=detail,
        )

    @staticmethod
    def _extract_numbers(
        text: str,
        pattern: str | None,
        separator: str | None,
        split_at: int | None,
    ) -> tuple[int, int] | None:
        # 优先级 1: 自定义正则
        if pattern:
            m = re.search(pattern, text)
            if m and m.lastindex and m.lastindex >= 2:
                return (int(m.group(1)), int(m.group(2)))
            return None

        # 优先级 2: 显式分隔符
        if separator:
            escaped = re.escape(separator)
            m = re.search(rf"(\d+)\s*{escaped}\s*(\d+)", text)
            if m:
                return (int(m.group(1)), int(m.group(2)))
            return None

        # 优先级 3: 自动模式
        nums = re.findall(r"\d+", text)
        if len(nums) >= 2:
            return (int(nums[0]), int(nums[1]))
        if len(nums) == 1 and split_at is not None:
            num_str = nums[0]
            if 0 < split_at < len(num_str):
                return (int(num_str[:split_at]), int(num_str[split_at:]))
        return None
