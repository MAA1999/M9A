import re
import json
import requests
from bs4 import BeautifulSoup


CN_CONTENT_URL = "https://notice.sl916.com/noticecp/client/query"
OTHER_URL = "https://re1999.bluepoch.com/activity/official/websites/information/query"

PATTERNS = {
    "cn": r"(\d+\.\d+)\s*「([^」]+)」版本活动一览",
    "en": r"Ver\.\s+(\d+\.\d+)\s+\[([^\]]+)\]\s+Preview",
    "jp": r"Ver\.\s+(\d+\.\d+)\s*「([^」]+)」情報一覧",
    "tw": r"(\d+\.\d+)\s*「([^」]+)」版本活動一覽",
}

TW_NEWS_URL = "https://re1999.movergames.com/news.html?type=2#news"
TW_PAGE_BASE_URL = "https://re1999.movergames.com/page/"

GAME_IDS = {"cn": 50001, "en": 60001, "jp": 70001}


def getContent(resource: str):
    if resource == "cn":
        data = json.loads(
            requests.get(
                url=CN_CONTENT_URL,
                params={
                    "gameId": 50001,
                    "channelId": 100,
                    "subChannelId": 1009,
                    "serverType": 4,
                },
            ).text
        )
        if data["msg"] == "成功":
            data = data["data"]
            for item in data:
                item = item["contentMap"]["zh-CN"]
                title = re.sub(
                    r"\r|<b>|</b>", "", json.loads(item["content"])[0]["content"]
                )
                content = item["content"]
                match = re.search(PATTERNS["cn"], title)
                if match:
                    return True, (resource, match.group(1), match.group(2), content)
    elif resource in ["en", "jp"]:
        data = json.loads(
            requests.post(
                url=OTHER_URL,
                json={
                    "informationType": 2,
                    "current": 1,
                    "pageSize": 5,
                    "gameId": GAME_IDS[resource],
                },
            ).text
        )
        if data["msg"] == "成功":
            data = data["data"]["pageData"]
            for item in data:
                title, content = item["title"], item["content"]
                match = re.search(PATTERNS[resource], title)
                if match:
                    return True, (resource, match.group(1), match.group(2), content)
    elif resource == "tw":
        # 获取新闻列表页面
        response = requests.get(TW_NEWS_URL)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        # 查找所有新闻项
        news_items = soup.find_all("a", class_="news-item")

        for item in news_items:
            title = item.find("span", class_="news-title").get_text().strip()
            match = re.search(PATTERNS["tw"], title)

            if match:
                # 提取详情页面链接
                detail_url = item.get("href")
                if detail_url.startswith("./page/"):
                    detail_url = TW_PAGE_BASE_URL + detail_url.replace("./page/", "")

                # 获取详情页面内容
                detail_response = requests.get(detail_url)
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
