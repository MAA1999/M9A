import re
import json
from datetime import datetime
from typing import Optional

import pytz
from bs4 import BeautifulSoup


def analyzeContent(resource: str, content):
    activity = {}

    if resource == "cn":
        combat_complete_flag = False
        re_release_find_flag = False
        re_release_compelete_flag = False

        if "全新主线篇章" in content:
            activity["combat"] = {}
            activity["combat"]["event_type"] = "MainStory"
        elif "【故事模式】" in content:
            activity["combat"] = {}
            activity["combat"]["event_type"] = "SideStory"
        try:
            content = json.loads(content)
        except Exception:
            # If content isn't valid JSON, treat it as raw HTML/text
            content = [content]

        for line in content:
            # line may be a dict with 'content', or a plain string
            if isinstance(line, dict):
                if "content" in line:
                    raw = line["content"]
                else:
                    # unexpected dict structure: skip with a warning
                    print("Warning: skipping line without 'content' key:", line)
                    continue
            else:
                raw = line

            text = re.sub(r"\r|<b>|</b>", "", raw)
            if re_release_find_flag and not re_release_compelete_flag:
                if "活动关卡开放时间" in text:
                    re_release_compelete_flag = True
                    activity["re-release"] = {}
                    re_release_duration = process_combat_duration_cn(text)
                    (
                        activity["re-release"]["start_time"],
                        activity["re-release"]["end_time"],
                    ) = convert_to_timestamps(re_release_duration)
                    continue
            if not combat_complete_flag and (
                "【故事模式】" in text or "【活动时间】" in text
            ):
                combat_complete_flag = True
                combat_duration = process_combat_duration_cn(text)
                activity["combat"]["start_time"], activity["combat"]["end_time"] = (
                    convert_to_timestamps(combat_duration)
                )
                continue
            if "限时重映" in text:
                re_release_find_flag = True
                continue
        return activity
    elif resource == "en":

        soup = BeautifulSoup(content, "html.parser")
        p_tags = soup.find_all("p")

        main_compelete_flag = False

        for i, p in enumerate(p_tags):
            html_content = str(p)
            if "New Main Story" in html_content:
                activity["combat"] = {}
                activity["combat"]["event_type"] = "MainStory"
                break
            elif "Main Event" in html_content:
                activity["combat"] = {}
                activity["combat"]["event_type"] = "SideStory"
                break

        for i, p in enumerate(p_tags):
            html_content = str(p)
            text = p.get_text().strip()
            if (
                not main_compelete_flag
                and activity["combat"]["event_type"] == "MainStory"
            ):
                if "After the version update on" in text:
                    main_compelete_flag = True
                    combat_duration = process_combat_duration_en(text)
                    activity["combat"]["start_time"], activity["combat"]["end_time"] = (
                        convert_to_timestamps(combat_duration)
                    )
            if "Story Mode" in text:
                if "UTC" not in text:
                    text = p.find_next("p").get_text().strip()
                combat_duration = process_combat_duration_en(text)
                activity["combat"]["start_time"], activity["combat"]["end_time"] = (
                    convert_to_timestamps(combat_duration)
                )
            if "[Event Stages]" in text:
                activity["re-release"] = {}
                if "UTC" not in text:
                    text = p.find_next("p").get_text().strip()
                re_release_duration = process_combat_duration_en(text)
                (
                    activity["re-release"]["start_time"],
                    activity["re-release"]["end_time"],
                ) = convert_to_timestamps(re_release_duration)
                continue

    elif resource == "jp":

        soup = BeautifulSoup(content, "html.parser")
        p_tags = soup.find_all("p")

        main_compelete_flag = False

        for i, p in enumerate(p_tags):
            html_content = str(p)
            if "新メインストーリー" in html_content:
                activity["combat"] = {}
                activity["combat"]["event_type"] = "MainStory"
                break
            elif "イベント本編" in html_content:
                activity["combat"] = {}
                activity["combat"]["event_type"] = "SideStory"
                break

        for i, p in enumerate(p_tags):
            html_content = str(p)
            text = p.get_text().strip()
            if (
                not main_compelete_flag
                and activity["combat"]["event_type"] == "MainStory"
            ):
                if "イベント期間" in text:
                    main_compelete_flag = True
                    combat_duration = process_combat_duration_jp(text)
                    activity["combat"]["start_time"], activity["combat"]["end_time"] = (
                        convert_to_timestamps(combat_duration)
                    )
            # Story Mode
            if "ストーリーモード" in text:
                combat_duration = process_combat_duration_jp(text)
                activity["combat"]["start_time"], activity["combat"]["end_time"] = (
                    convert_to_timestamps(combat_duration)
                )
                continue
            # re-release
            if "【イベントステージ】開放期間：" in text or "ステージ開放期間" in text:
                activity["re-release"] = {}
                re_release_duration = process_combat_duration_jp(text)
                (
                    activity["re-release"]["start_time"],
                    activity["re-release"]["end_time"],
                ) = convert_to_timestamps(re_release_duration)
                continue

    elif resource == "tw":

        soup = BeautifulSoup(content, "html.parser")
        tz_tw = pytz.timezone("Asia/Taipei")
        base_year = datetime.now(tz_tw).year
        base_month = None

        news_time_tag = soup.find("div", class_="news-time")
        if news_time_tag:
            news_time_match = re.search(
                r"(\d{4})/(\d{2})/(\d{2})", news_time_tag.get_text()
            )
            if news_time_match:
                base_year = int(news_time_match.group(1))
                base_month = int(news_time_match.group(2))

        p_tags = soup.find_all("p")
        current_section = None

        for p in p_tags:
            text = p.get_text().strip()
            if not text:
                continue

            if "全新主線" in text or "活動正篇" in text:
                activity.setdefault("combat", {})
                activity["combat"]["event_type"] = "MainStory"
                current_section = "combat"
                continue

            if "限時重映" in text and "活動" in text:
                activity.setdefault("re-release", {})
                current_section = "re-release"
                continue

            if current_section:
                duration_text = extract_tw_duration_segment(text)
                if duration_text:
                    try:
                        formatted = process_combat_duration_tw(
                            duration_text, base_year, base_month
                        )
                        (
                            activity[current_section]["start_time"],
                            activity[current_section]["end_time"],
                        ) = convert_to_timestamps(formatted)
                        if current_section == "combat":
                            current_section = None
                        elif current_section == "re-release":
                            current_section = None
                    except ValueError:
                        continue

    return activity


def convert_to_timestamps(time_range_str):
    """
    将时间范围字符串转换为毫秒时间戳，正确处理夏令时
    """
    # 提取时间和时区
    pattern = r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*-\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*(?:\d{2}:\d{2})?\s*\(UTC([+-]?\d+)\)"
    match = re.search(pattern, time_range_str)

    if not match:
        raise ValueError(f"无法解析时间字符串: {time_range_str}")

    start_time_str, end_time_str, utc_offset = match.groups()
    utc_offset = int(utc_offset)

    # 使用正确的时区对象 - 更智能地处理夏令时
    # 对于UTC-5，使用美国东部时间或类似时区
    if utc_offset == -5:
        # 使用美国东部时区，会自动处理夏令时
        tz = pytz.timezone("America/New_York")
    else:
        # 使用固定偏移时区（不处理夏令时）
        tz = pytz.FixedOffset(utc_offset * 60)  # pytz使用分钟作为偏移

    # 解析时间字符串并附加时区信息
    naive_start = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")
    naive_end = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M")

    # 正确地将naive时间本地化到指定时区
    start_time = tz.localize(naive_start)
    end_time = tz.localize(naive_end)

    # 如果结束时间是xx:59格式，添加59秒
    if end_time.minute == 59:
        end_time = end_time.replace(second=59)

    # 转换为UTC毫秒时间戳
    start_timestamp_ms = int(start_time.timestamp() * 1000)
    end_timestamp_ms = int(end_time.timestamp() * 1000)

    return start_timestamp_ms, end_timestamp_ms


def process_combat_duration_cn(duration: str):

    # 定义北京时区 (UTC+8)
    beijing_tz = pytz.timezone("Asia/Shanghai")

    # 获取北京时区的当前时间
    now = datetime.now(beijing_tz)
    current_year = now.year

    # 定义正则表达式来匹配开始和结束时间
    start_pattern = r"(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{1,2})"
    end_pattern = r"-\s*(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{1,2})"

    start_match = re.search(start_pattern, duration)
    end_match = re.search(end_pattern, duration)

    if not start_match or not end_match:
        print("无法匹配日期格式")
        return duration

    # 提取开始时间
    start_month, start_day, start_hour, start_minute = map(int, start_match.groups())
    # 提取结束时间
    end_month, end_day, end_hour, end_minute = map(int, end_match.groups())

    # 处理可能的跨年情况
    start_year = current_year
    end_year = current_year

    # 如果当前月份已经超过了结束月份，认为结束日期是下一年
    if now.month > end_month and start_month > end_month:
        end_year = current_year + 1

    # 如果开始月份大于结束月份，认为结束日期是下一年
    if start_month > end_month:
        end_year = current_year + 1

    # 创建完整的日期时间对象
    try:
        start_datetime = datetime(
            start_year,
            start_month,
            start_day,
            start_hour,
            start_minute,
            tzinfo=beijing_tz,
        )
        end_datetime = datetime(
            end_year, end_month, end_day, end_hour, end_minute, tzinfo=beijing_tz
        )

        # 如果结束分钟是59，添加59秒以包含整个分钟
        if end_minute == 59:
            end_datetime = end_datetime.replace(second=59)

        # 格式化为目标格式
        formatted_result = f"{start_datetime.strftime('%Y-%m-%d %H:%M')} - {end_datetime.strftime('%Y-%m-%d %H:%M')} (UTC+8)"

        return formatted_result

    except ValueError as e:
        print(f"日期转换错误: {e}")
        return duration


def process_combat_duration_en(duration: str):

    start_pattern = r"After the version update on (\d{4}-\d{2}-\d{2})"
    match = re.search(start_pattern, duration)
    if match:
        start_date = match.group(1)
        start_time = f"{start_date} 10:00"
        duration = duration.replace(match.group(0), start_time)

    return duration


def process_combat_duration_jp(duration: str):
    # 移除前缀，但保留更新后的标记用于正则匹配
    if "ストーリーモード：" in duration:
        duration = duration.replace("ストーリーモード：", "")
    if "開放期間：" in duration:
        duration = duration.split("開放期間：")[-1]

    # 在输出正则匹配前保存原始字符串
    original_duration = duration

    # 定义日本时区 (UTC+9)
    jst = pytz.timezone("Asia/Tokyo")

    # 先检查是否有"更新后"类型的表述，并提取日期
    update_pattern = r"(\d{4})年(\d{1,2})月(\d{1,2})日（[月火水木金土日]）\s*(アップデート後|更新後|メンテナンス後)"
    update_match = re.search(update_pattern, original_duration)

    if update_match:
        year, month, day, update_text = update_match.groups()
        year, month, day = map(int, [year, month, day])

        # 替换为明确的时间格式
        replacement = f"{year}年{month}月{day}日 10:00"
        duration = re.sub(update_pattern, replacement, original_duration)

    # 处理标准格式的时间范围
    # 支持结束日期包含年份的格式，如: 2025年12月11日 10:00～2026年1月19日（月） 4:59
    start_pattern = r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:（[月火水木金土日]）)?\s*(\d{1,2}):(\d{1,2})"
    end_pattern = r"[～〜]\s*(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日(?:（[月火水木金土日]）)?\s*(\d{1,2}):(\d{1,2})"

    start_match = re.search(start_pattern, duration)
    end_match = re.search(end_pattern, duration)

    # 如果仍然无法匹配，返回原始字符串
    if not start_match or not end_match:
        return f"无法解析: {original_duration}"

    # 解析开始时间
    start_year, start_month, start_day, start_hour, start_minute = map(
        int, start_match.groups()
    )
    naive_start = datetime(start_year, start_month, start_day, start_hour, start_minute)
    start_date = jst.localize(naive_start)  # 本地化到JST时区

    # 解析结束时间（允许结束年可选）
    end_groups = end_match.groups()
    # end_groups = (end_year_or_None, end_month, end_day, end_hour, end_minute)
    if end_groups[0]:
        end_year = int(end_groups[0])
    else:
        end_year = start_year
    end_month = int(end_groups[1])
    end_day = int(end_groups[2])
    end_hour = int(end_groups[3])
    end_minute = int(end_groups[4])

    # 若结束月小于开始月，则推断为下一年
    if end_year == start_year and end_month < start_month:
        end_year = start_year + 1

    naive_end = datetime(end_year, end_month, end_day, end_hour, end_minute)
    end_date = jst.localize(naive_end)  # 本地化到JST时区

    # 如果结束分钟是59，添加59秒
    if end_minute == 59:
        end_date = end_date.replace(second=59)

    # 格式化为标准时间范围字符串 (UTC+9)
    duration = f"{start_date.strftime('%Y-%m-%d %H:%M')} - {end_date.strftime('%Y-%m-%d %H:%M')} (UTC+9)"

    return duration


def extract_tw_duration_segment(text: str):
    match = re.search(r"(\d{1,2}/\d{1,2}.*)", text)
    if match:
        return match.group(1)
    return None


def process_combat_duration_tw(
    duration: str, base_year: int, base_month: Optional[int]
):

    taipei_tz = pytz.timezone("Asia/Taipei")

    cleaned = duration
    cleaned = cleaned.replace("版本更新後", "10:00")
    cleaned = cleaned.replace("版本更新后", "10:00")
    cleaned = cleaned.replace("～", "-")
    cleaned = cleaned.replace("~", "-")
    cleaned = cleaned.replace("〜", "-")
    cleaned = cleaned.replace("—", "-")
    cleaned = cleaned.replace("－", "-")
    cleaned = cleaned.replace("至", "-")
    cleaned = re.sub(r"^[^\d]+", "", cleaned)
    cleaned = re.sub(r"[【】「」]", "", cleaned)

    pattern = r"(\d{1,2})/(\d{1,2})\s*(\d{1,2}:\d{2})?\s*-\s*(\d{1,2})/(\d{1,2})\s*(\d{1,2}:\d{2})"
    match = re.search(pattern, cleaned)

    if not match:
        raise ValueError(f"无法解析台湾站时间范围: {duration}")

    start_month, start_day, start_time, end_month, end_day, end_time = match.groups()
    start_month = int(start_month)
    start_day = int(start_day)
    end_month = int(end_month)
    end_day = int(end_day)

    if not start_time:
        start_time = "10:00"

    start_hour, start_minute = map(int, start_time.split(":"))
    end_hour, end_minute = map(int, end_time.split(":"))

    def resolve_year(month: int) -> int:
        year = base_year
        if base_month is not None:
            diff = month - base_month
            if diff <= -6:
                year = base_year + 1
            elif diff >= 6:
                year = base_year - 1
        return year

    start_year = resolve_year(start_month)
    end_year = resolve_year(end_month)

    if (end_year, end_month, end_day, end_hour, end_minute) < (
        start_year,
        start_month,
        start_day,
        start_hour,
        start_minute,
    ):
        if end_month < start_month or (
            end_month == start_month and end_day < start_day
        ):
            end_year = start_year + 1
        else:
            end_year = start_year

    start_datetime = taipei_tz.localize(
        datetime(start_year, start_month, start_day, start_hour, start_minute)
    )
    end_datetime = taipei_tz.localize(
        datetime(end_year, end_month, end_day, end_hour, end_minute)
    )

    if end_minute == 59:
        end_datetime = end_datetime.replace(second=59)

    return (
        f"{start_datetime.strftime('%Y-%m-%d %H:%M')} - "
        f"{end_datetime.strftime('%Y-%m-%d %H:%M')} (UTC+8)"
    )
