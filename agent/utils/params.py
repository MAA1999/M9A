import json


def parse_params(raw: str | None, *required_keys: str) -> dict:
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
