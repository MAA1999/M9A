import json
import os
from typing import Any

from analyzeContent import analyzeContent
from getContent import getContent


def save_activity_data(resource: Any, data: Any):
    """
    将活动数据保存到对应语言的JSON文件中

    Args:
        resource: 语言资源标识 ('cn', 'en', 'jp', 'tw')
        data: 要保存的数据，格式为 {version_id: {version_info}}

    Returns:
        bool: 是否成功保存
    """

    # 构建文件路径
    file_path = f"data/activity/{resource}.json"

    # 提取当前要保存的版本号 (只取第一个，假设每次只处理一个版本)
    version_id = next(iter(data.keys()), None)
    if not version_id:
        print("Error: No version ID found in data")
        return False

    print(f"Processing {resource} data for version: {version_id}")

    # 检查文件是否存在
    if os.path.exists(file_path):
        try:
            # 读取现有文件
            with open(file_path, encoding="utf-8") as f:
                try:
                    existing_data = json.load(f)
                    print(f"Successfully loaded existing data from {file_path}")
                except json.JSONDecodeError:
                    print(f"Warning: {file_path} exists but contains invalid JSON, treating as empty")
                    existing_data = {}

            # 检查版本号是否已存在
            if version_id in existing_data:
                print(f"Version {version_id} already exists in {file_path}, skipping")
                return False

            # 合并数据
            merged_data = {**existing_data, **data}
            print("Merging new version data with existing data")

        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return False
    else:
        print(f"{file_path} does not exist, creating new file")
        merged_data = data

    # 写入数据
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=4)
            f.write("\n")
        print(f"Successfully saved data to {file_path}")
        return True
    except Exception as e:
        print(f"Error writing to {file_path}: {e}")
        return False


if __name__ == "__main__":
    updated_resources = []
    skipped_resources = []
    failed_resources = []

    for resource in ["cn", "en", "jp", "tw"]:
        try:
            success, result = getContent(resource)
            if not success:
                print(f"[{resource}] Failed to fetch matching activity notice")
                failed_resources.append(resource)
                continue

            if result is None:
                print(f"[{resource}] Fetch reported success but returned empty result")
                failed_resources.append(resource)
                continue

            activity = analyzeContent(resource, result[-1])
            combat = activity.get("combat", {})
            start_time = combat.get("start_time")
            combat_end_time = combat.get("end_time")

            if start_time is None or combat_end_time is None:
                print(f"[{resource}] Parsed notice but combat time is incomplete, skipping version {result[1]}")
                failed_resources.append(resource)
                continue

            end_time = combat_end_time + 3 * 24 * 60 * 60 * 1000
            data = {
                f"{result[1]}": {
                    "version_name": result[2],
                    "start_time": start_time,
                    "end_time": end_time,
                    "activity": activity,
                }
            }

            saved = save_activity_data(resource, data)
            if saved:
                updated_resources.append(resource)
            else:
                skipped_resources.append(resource)
        except Exception as e:
            print(f"[{resource}] Unexpected error: {e}")
            failed_resources.append(resource)

    print(
        "Summary:",
        {
            "updated": updated_resources,
            "skipped": skipped_resources,
            "failed": failed_resources,
        },
    )
