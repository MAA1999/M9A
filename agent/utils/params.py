import json
from typing import Any

from .logger import logger


def parse_params(raw: str | None, *required_keys: str) -> dict[str, Any]:
    """
    解析 custom_action_param / custom_recognition_param JSON 字符串。

    Args:
        raw: 原始 JSON 字符串，可为 None 或空串
        required_keys: 必须存在的字段名

    Returns:
        解析后的 dict（raw 为空时返回空 dict）

    Raises:
        ValueError: JSON 格式错误、非对象类型、或缺少必填字段
    """
    if not raw:
        if required_keys:
            raise ValueError(f"参数为空，需要字段: {list(required_keys)}")
        return {}
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析失败: {e}") from e
    if not isinstance(params, dict):
        raise ValueError(f"参数必须是对象，得到: {type(params).__name__}")
    if required_keys:
        missing = [k for k in required_keys if k not in params]
        if missing:
            raise ValueError(f"缺少必填字段: {missing}")
    return params


def coerce_like(value: Any, default: Any, key: str) -> Any:
    """
    将 JSON 反序列化值按默认值的形状转换，用于参数覆盖。

    - 默认值为 tuple/list：接受 list/tuple，长度必须一致（如 ROI 必须 4 元），
      元素必须是数字，返回与默认值同类型
    - 默认值为 bool：仅接受 bool（注意 bool 是 int 子类，需先判）
    - 默认值为 int/float：接受数字并转换为对应类型
    - 默认值为 str：仅接受 str
    - 其他类型：要求类型完全一致

    Raises:
        ValueError: 形状或类型不匹配
    """
    if isinstance(default, (tuple, list)):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{key} 应为数组，得到 {type(value).__name__}")
        if len(value) != len(default):
            raise ValueError(f"{key} 长度应为 {len(default)}，得到 {len(value)}")
        if not all(isinstance(v, (int, float)) for v in value):
            raise ValueError(f"{key} 元素应为数字")
        return type(default)(value)
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} 应为布尔值，得到 {type(value).__name__}")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} 应为数字，得到 {type(value).__name__}")
        return int(value)
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} 应为数字，得到 {type(value).__name__}")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"{key} 应为字符串，得到 {type(value).__name__}")
        return value
    if type(value) is not type(default):
        raise ValueError(f"{key} 应为 {type(default).__name__}，得到 {type(value).__name__}")
    return value


class ParamOverrideMixin:
    """
    自定义识别参数覆盖混入：把 custom_recognition_param 中的小写 key
    覆盖到实例属性上（遮蔽同名大写类常量），实现「识别参数外置到
    pipeline JSON、Python 类常量作为默认值」的分层。

    - JSON key 约定 = 类常量名小写（如 sat_min -> SAT_MIN）
    - 仅 OVERRIDABLE 白名单内的常量可覆盖，未知 key 记 warning 后忽略
    - 值经 coerce_like 按默认值同形转换，非法值回落默认并记 error
    - 每次调用入口先清空上次的实例覆盖，防止跨节点串扰
    - 线程安全前提：MaaFramework 单 Tasker 的识别回调串行执行
    """

    OVERRIDABLE: frozenset[str] = frozenset()

    def apply_param_overrides(self, params: dict[str, Any]) -> None:
        for const in self.OVERRIDABLE:
            self.__dict__.pop(const, None)
        for key, value in params.items():
            if key == "query":
                continue
            const = key.upper()
            if const not in self.OVERRIDABLE:
                logger.warning(f"[{type(self).__name__}] 未知参数 {key}，已忽略")
                continue
            try:
                setattr(self, const, coerce_like(value, getattr(type(self), const), key))
            except ValueError as e:
                logger.error(f"[{type(self).__name__}] 参数 {key} 非法（{e}），回落默认值")
