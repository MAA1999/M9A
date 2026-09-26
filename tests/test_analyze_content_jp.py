from pathlib import Path

from tools.activity_data.analyzeContent import _analyze_jp_lines, _find_jp_date_range

# 真实公告快照：日服 Ver. 3.8「世紀末スケール」情報一覧，经 _extract_html_text_lines 提取。
# 该公告曾暴露日服解析缺陷：【标题】与日期分两行存放，正文描述句又含"イベント期間"字样，
# 导致主活动档期被万圣节小活动「前夜の挨拶」(10/31～11/3) 覆盖
FIXTURE_LINES = (
    (Path(__file__).parent / "fixtures" / "activity_jp_ver38_notice_lines.txt").read_text(encoding="utf-8").splitlines()
)

# 2026-09-24 10:00:00 JST（版本更新后）～ 2026-11-02 04:59:59 JST
COMBAT_START = 1790211600000
COMBAT_END = 1793563199000
# 复刻「長き夜に汽笛は鳴る」：2026-10-23 05:00:00 JST
RE_RELEASE_START = 1792699200000


def test_analyze_jp_38_side_story_parses_main_event_window() -> None:
    activity = _analyze_jp_lines(FIXTURE_LINES)

    assert activity["combat"]["event_type"] == "SideStory"
    assert activity["combat"]["start_time"] == COMBAT_START
    assert activity["combat"]["end_time"] == COMBAT_END


def test_analyze_jp_38_parses_re_release_window() -> None:
    activity = _analyze_jp_lines(FIXTURE_LINES)

    assert activity["re-release"]["start_time"] == RE_RELEASE_START
    assert activity["re-release"]["end_time"] == COMBAT_END


def test_find_jp_date_range_follows_date_line_after_header() -> None:
    lines = [
        "イベント本編",
        "【ストーリーモード】",
        "2026年9月24日（木）アップデート後～11月2日（月）4:59",
        "イベント期間中、「世紀末スケール」のストーリーとイベントステージを遊べます。",
        "【イベント期間】2026年10月31日（土）0:00〜11月3日（火）4:59",
    ]

    # 标题行自身无日期时，向下找到日期行
    assert _find_jp_date_range(lines, 1, window=3) == (COMBAT_START, COMBAT_END)

    # 只认"能解析出日期范围"的行：从描述句（含"イベント期間"字样但无日期）起搜索时，
    # 描述句本身不会被当作结果，搜索继续到下一条可解析的日期行
    assert _find_jp_date_range(lines, 3, window=3) == (1793372400000, 1793649599000)
