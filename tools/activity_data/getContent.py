import re
import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CN_CONTENT_URL = "https://notice.sl916.com/noticecp/client/query"
OTHER_URL = "https://re1999.bluepoch.com/activity/official/websites/information/query"

PATTERNS = {
    "cn": r"(\d+\.\d+)\s*「([^」]+)」版本活动一览",
    "tw": r"(\d+\.\d+)\s*「([^」]+)」版本活動一覽",
}

TW_NEWS_URL = "https://re1999.movergames.com/news.html?type=2#news"
TW_PAGE_BASE_URL = "https://re1999.movergames.com/page/"

# 使用较大的范围兼容官方公告分类调整。
EN_JP_INFO_TYPES = [5, 2, 3]
EN_JP_PAGE_SIZE = 20
EN_JP_MAX_PAGES = 3

REQUEST_TIMEOUT = 30
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; M9A-activity-updater/1.0)",
}

GAME_IDS = {"cn": 50001, "en": 60001, "jp": 70001}


def _request_json(method: str, url: str, **kwargs):
    try:
        response = requests.request(
            method=method,
            url=url,
            timeout=REQUEST_TIMEOUT,
            headers=REQUEST_HEADERS,
            **kwargs,
        )
        response.raise_for_status()
        return True, response.json()
    except Exception as e:
        print(f"Request failed for {url}: {e}")
        return False, None


def _is_en_detail_notice(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title).lower()
    return "preview" in normalized or "overview" in normalized


def _is_jp_detail_notice(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title)
    return "情報一覧" in normalized or "イベント一覧" in normalized


def _extract_content_lines(content: str):
    soup = BeautifulSoup(content, "html.parser")
    lines = []
    for text in soup.stripped_strings:
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized:
            lines.append(normalized)
    return lines


def _extract_en_version_and_name(title: str):
    version_match = re.search(r"Ver\.?\s*(\d+\.\d+)", title, re.IGNORECASE)
    if not version_match:
        version_match = re.search(r"^\s*(\d+\.\d+)\s+\[", title)
    if not version_match:
        return None, None

    # 优先抓取中括号里的版本名，如 [The Midnight Whistle]
    name_match = re.search(r"\[([^\]]+)\]", title)
    if name_match:
        return version_match.group(1), name_match.group(1).strip()

    # 次选抓取引号内容，如 "The Campaign's Tale"
    quote_match = re.search(r"[\"“”]([^\"“”]+)[\"“”]", title)
    if quote_match:
        return version_match.group(1), quote_match.group(1).strip()

    return version_match.group(1), version_match.group(1)


def _extract_jp_version_and_name(title: str):
    version_match = re.search(r"Ver\.?\s*(\d+\.\d+)", title, re.IGNORECASE)
    if not version_match:
        version_match = re.search(r"^\s*(\d+\.\d+)\s*「", title)
    if not version_match:
        return None, None

    name_match = re.search(r"「([^」]+)」", title)
    if name_match:
        return version_match.group(1), name_match.group(1).strip()

    return version_match.group(1), version_match.group(1)


def _parse_version_key(version_id: str):
    match = re.match(r"^(\d+)\.(\d+)$", version_id or "")
    if not match:
        return -1, -1
    return int(match.group(1)), int(match.group(2))


def _infer_version_from_content(content: str, known_version_name_pairs):
    if not known_version_name_pairs:
        return None, None

    content_text = " ".join(_extract_content_lines(content))
    for version_id, version_name in sorted(
        known_version_name_pairs,
        key=lambda x: _parse_version_key(x[0]),
        reverse=True,
    ):
        if version_name and version_name in content_text:
            return version_id, version_name

    return None, None


def _get_content_for_en_or_jp(resource: str):
    game_id = GAME_IDS[resource]
    known_version_name_pairs = []
    candidate_detail_notices = []

    for information_type in EN_JP_INFO_TYPES:
        for page in range(1, EN_JP_MAX_PAGES + 1):
            ok, data = _request_json(
                "POST",
                OTHER_URL,
                json={
                    "informationType": information_type,
                    "current": page,
                    "pageSize": EN_JP_PAGE_SIZE,
                    "gameId": game_id,
                },
            )
            if not ok or not data or data.get("msg") != "成功":
                continue

            page_data = data.get("data", {}).get("pageData", [])
            if not page_data:
                break

            for item in page_data:
                title = item.get("title", "")
                content = item.get("content", "")
                if not title or not content:
                    continue

                if resource == "en":
                    explicit_version_id, explicit_version_name = (
                        _extract_en_version_and_name(title)
                    )
                else:
                    explicit_version_id, explicit_version_name = (
                        _extract_jp_version_and_name(title)
                    )

                if (
                    explicit_version_id
                    and explicit_version_name
                    and explicit_version_name != explicit_version_id
                ):
                    pair = (explicit_version_id, explicit_version_name)
                    if pair not in known_version_name_pairs:
                        known_version_name_pairs.append(pair)

                if resource == "en":
                    if not _is_en_detail_notice(title):
                        continue
                else:
                    if not _is_jp_detail_notice(title):
                        continue

                candidate_detail_notices.append(
                    {
                        "title": title,
                        "content": content,
                        "version_id": explicit_version_id,
                        "version_name": explicit_version_name,
                    }
                )

    for item in candidate_detail_notices:
        version_id = item["version_id"]
        version_name = item["version_name"]
        if version_id:
            if not version_name or version_name == version_id:
                inferred_id, inferred_name = _infer_version_from_content(
                    item["content"], known_version_name_pairs
                )
                if inferred_id:
                    version_id, version_name = inferred_id, inferred_name
            return True, (resource, version_id, version_name, item["content"])

        inferred_id, inferred_name = _infer_version_from_content(
            item["content"], known_version_name_pairs
        )
        if inferred_id:
            return True, (resource, inferred_id, inferred_name, item["content"])

    return False, None


def getContent(resource: str):
    if resource == "cn":
        ok, data = _request_json(
            "GET",
            CN_CONTENT_URL,
            params={
                "gameId": 50001,
                "channelId": 100,
                "subChannelId": 1009,
                "serverType": 4,
            },
        )
        if ok and data and data.get("msg") == "成功":
            data = data.get("data", [])
            for item in data:
                item = item.get("contentMap", {}).get("zh-CN")
                if not item:
                    continue

                content = item.get("content", "")
                if not content:
                    continue

                try:
                    title = re.sub(
                        r"\r|<b>|</b>", "", json.loads(content)[0]["content"]
                    )
                except Exception:
                    continue

                match = re.search(PATTERNS["cn"], title)
                if match:
                    return True, (resource, match.group(1), match.group(2), content)
    elif resource in ["en", "jp"]:
        return _get_content_for_en_or_jp(resource)
    elif resource == "tw":
        # 获取新闻列表页面
        response = requests.get(
            TW_NEWS_URL,
            timeout=REQUEST_TIMEOUT,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        # 查找所有新闻项
        news_items = soup.find_all("a", class_="news-item")

        for item in news_items:
            title_tag = item.find("span", class_="news-title")
            if not title_tag:
                continue

            title = title_tag.get_text().strip()
            match = re.search(PATTERNS["tw"], title)

            if match:
                # 提取详情页面链接
                detail_url = item.get("href", "")
                if not detail_url:
                    continue
                detail_url = urljoin(TW_NEWS_URL, detail_url)

                # 获取详情页面内容
                detail_response = requests.get(
                    detail_url,
                    timeout=REQUEST_TIMEOUT,
                    headers=REQUEST_HEADERS,
                )
                detail_response.raise_for_status()
                detail_response.encoding = "utf-8"
                detail_soup = BeautifulSoup(detail_response.text, "html.parser")

                # 提取内容区域（根据实际HTML结构调整）
                content_div = detail_soup.find("div", class_="content")
                if content_div:
                    content = str(content_div)
                else:
                    # 备用方案：获取整个body
                    content = str(detail_soup)

                return True, (resource, match.group(1), match.group(2), content)

    return False, None


if __name__ == "__main__":
    data0 = getContent("cn")
    data1 = getContent("en")
    data2 = getContent("jp")
    data3 = getContent("tw")

    print("CN:", data0)
    print("EN:", data1)
    print("JP:", data2)
    print("TW:", data3)
