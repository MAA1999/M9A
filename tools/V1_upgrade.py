from math import e
import os
import json


def get_unique_resource_paths():
    # 获取当前脚本所在目录
    current_dir = os.path.join(os.getcwd(), "assets")
    # 构建 interface.json 文件的路径
    json_file_path = os.path.join(current_dir, "interface.json")

    try:
        # 打开并读取 JSON 文件
        with open(json_file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        # 提取 resource 键的值
        resource_list = data.get("resource", [])

        unique_paths = set()
        for resource in resource_list:
            paths = resource.get("path", [])
            for path in paths:
                # 替换 . 为当前工作目录
                full_path = path.replace(".", current_dir)
                unique_paths.add(full_path)

        return sorted(list(unique_paths))
    except FileNotFoundError:
        print("未找到 interface.json 文件")
        return []
    except Exception as e:
        print(f"读取文件时出错: {e}")
        return []


def get_pipeline_files(input_path):
    """
    遍历指定路径下的 pipeline 文件夹，返回其中所有文件的路径。

    :param input_path: 输入的基础路径
    :return: 包含 pipeline 文件夹内所有文件路径的列表
    """
    pipeline_path = os.path.join(input_path, "pipeline")
    file_paths = []

    # 检查 pipeline 文件夹是否存在
    if os.path.exists(pipeline_path) and os.path.isdir(pipeline_path):
        # 遍历 pipeline 文件夹及其子文件夹
        for root, dirs, files in os.walk(pipeline_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_paths.append(file_path)
    return file_paths


def process_node(node):
    """
    处理 JSON 节点中的 action 和 recognition 字段。

    :param node: JSON 节点
    :return: 处理后的 JSON 节点
    """
    action_fields = [
        "target",
        "target_offset",
        "begin",
        "end",
        "duration",
        "begin_offset",
        "end_offset",
        "starting",
        "key",
        "package",
        "input_text",
        "custom_action",
        "custom_action_param",
        "exec",
        "args",
        "detach",
    ]
    recognition_fields = [
        "only_rec",
        "roi",
        "replace",
        "roi_offset",
        "expected",
        "expected_code",
        "template",
        "template_code",
        "green_mask",
        "index",
        "method",
        "threshold",
        "order_by",
        "count",
        "detector",
        "connected",
        "upper",
        "lower",
        "ratio",
        "model",
        "labels",
        "custom_recognition",
        "custom_recognition_param",
    ]

    # 处理 action 字段
    action_params = {}
    original_action_type = node.get("action")
    for field in action_fields:
        if field in node:
            action_params[field] = node.pop(field)
    # 当 type 和 action_params 都为空时，不写入action 字段
    if original_action_type or action_params:
        node["action"] = {
            **(
                {"type": original_action_type}
                if original_action_type and original_action_type != "Unknown"
                else {}
            ),
            **({"param": action_params} if action_params else {}),
        }
    else:
        node.pop("action", None)

    # 处理 recognition 字段
    recognition_params = {}
    original_recognition_type = node.get("recognition")
    for field in recognition_fields:
        if field in node:
            recognition_params[field] = node.pop(field)

    # 当 type 和 recognition_params 都为空时，不写入 recognition 字段
    if original_recognition_type or recognition_params:
        node["recognition"] = {
            **(
                {"type": original_recognition_type}
                if original_recognition_type and original_recognition_type != "Unknown"
                else {}
            ),
            **({"param": recognition_params} if recognition_params else {}),
        }
    else:
        node.pop("recognition", None)

    return node


def process_pipeline_override(pipeline_override):
    """
    处理 pipeline_override 中的每个节点。

    :param pipeline_override: pipeline_override 字典
    :return: 处理后的 pipeline_override 字典
    """
    if isinstance(pipeline_override, dict):
        for key, value in pipeline_override.items():
            if isinstance(value, dict):
                pipeline_override[key] = process_node(value)
    return pipeline_override


def traverse_and_modify(obj):
    """
    递归遍历对象，处理其中的 pipeline_override 字段。

    :param obj: 要遍历的对象
    :return: 处理后的对象
    """
    if isinstance(obj, dict):
        if "pipeline_override" in obj:
            obj["pipeline_override"] = process_pipeline_override(
                obj["pipeline_override"]
            )
        for key, value in obj.items():
            obj[key] = traverse_and_modify(value)
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            obj[index] = traverse_and_modify(item)
    return obj


def modify_json_file(file_path):
    """
    读取指定路径的 JSON 文件，将其中每个节点的 action 和 recognition 字段进行替换。

    :param file_path: JSON 文件的路径
    :return: 若操作成功返回 True，否则返回 False
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        if "interface.json" in file_path:
            data = traverse_and_modify(data)
        else:
            if isinstance(data, dict):
                for key in list(data.keys()):
                    if isinstance(data[key], dict):
                        data[key] = process_node(data[key])

        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)

        return True
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return False


def main():
    # 获取唯一资源路径
    resource_paths = get_unique_resource_paths()
    for path in resource_paths:
        # 获取每个路径下 pipeline 文件夹内的文件路径
        pipeline_files = get_pipeline_files(path)
        for file in pipeline_files:
            if file.endswith(".json"):
                # 修改 JSON 文件
                success = modify_json_file(file)
                if success:
                    print(f"成功修改文件: {file}")
                else:
                    print(f"修改文件失败: {file}")

    # 处理 interface.json 文件
    current_dir = os.path.join(os.getcwd(), "assets")
    interface_file_path = os.path.join(current_dir, "interface.json")
    if os.path.exists(interface_file_path):
        success = modify_json_file(interface_file_path)
        if success:
            print(f"成功修改文件: {interface_file_path}")
        else:
            print(f"修改文件失败: {interface_file_path}")


if __name__ == "__main__":
    main()
