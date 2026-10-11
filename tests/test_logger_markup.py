import io
import logging

from loguru import logger as loguru_logger

from agent.utils import pienv
from agent.utils.logger import (
    _CONSOLE_FORMAT,
    _ConsoleFormatter,
    _enrich_console_message,
    _format_mfaa_message,
    _format_mxu_html_message,
)


def _use_client(monkeypatch, client_name: str) -> None:
    """让 logger 走指定客户端分支（logger.py 通过 pienv.client_name() 判定客户端）。"""
    monkeypatch.setattr(pienv, "client_name", lambda: client_name)


def _render_via_loguru(monkeypatch, client_name: str, message: str) -> str:
    """用生产同一套格式串 + filter 走真实 loguru 控制台渲染路径。"""
    _use_client(monkeypatch, client_name)
    buf = io.StringIO()
    sink_id = loguru_logger.add(
        buf,
        format=_CONSOLE_FORMAT,
        colorize=False,
        level="TRACE",
        filter=_enrich_console_message,
    )
    try:
        loguru_logger.log("WARNING", message)
    finally:
        loguru_logger.remove(sink_id)
    return buf.getvalue()


def _std_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("m9a", logging.WARNING, __file__, 1, message, None, None)


def test_mxu_restores_font_markup() -> None:
    """colorize_name 产出的 <font color> 标记在转义后应还原，供 MXU 日志面板渲染。"""
    line = '材料 <font color="#E5A32A">自走惊吓夜</font> 已达标'
    html = _format_mxu_html_message("INFO", line)
    assert '<font color="#E5A32A">自走惊吓夜</font>' in html
    assert "&lt;font" not in html


def test_mxu_keeps_other_markup_escaped() -> None:
    """白名单之外的 HTML（脚本、非法色值、残缺标签）必须保持转义。"""
    html = _format_mxu_html_message("INFO", '<script>alert("x")</script> <font color="red">x</font>')
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "&lt;font color=&quot;red&quot;&gt;" in html


def test_mxu_wraps_each_line_in_level_span() -> None:
    html = _format_mxu_html_message("WARNING", "第一行\n第二行")
    lines = html.split("\n")
    assert lines == [
        '<span style="color:darkorange;">第一行</span>',
        '<span style="color:darkorange;">第二行</span>',
    ]


def test_mfaa_prefixes_every_line() -> None:
    """MFAAvalonia 逐行解析 agent 输出、只认带 level 前缀的行，多行消息必须逐行补前缀。"""
    assert _format_mfaa_message("WARNING", "第一行\n第二行") == "warn:第一行\nwarn:第二行"


def test_mfaa_single_line_keeps_single_prefix() -> None:
    assert _format_mfaa_message("INFO", "签到日历文本: 已签到") == "info:签到日历文本: 已签到"


def test_mfaa_drops_trailing_newline_line() -> None:
    """结尾换行不能变成一条裸 "info:" 空日志（MFAAvalonia 会收下它）。"""
    assert _format_mfaa_message("INFO", "第一行\n") == "info:第一行"
    assert _format_mxu_html_message("INFO", "第一行\n") == '<span style="color:forestgreen;">第一行</span>'


def test_console_formatter_prefixes_every_line_for_mfaa(monkeypatch) -> None:
    """无 loguru 时的标准 logging 回退路径同样要逐行补前缀。"""
    _use_client(monkeypatch, "MFAAvalonia")
    assert _ConsoleFormatter().format(_std_record("第一行\n第二行")) == "warn:第一行\nwarn:第二行"


def test_loguru_console_sink_renders_each_client(monkeypatch) -> None:
    """真实 loguru 控制台路径：格式串 + filter 必须对三种客户端各自成立。

    MXU 的 HTML 只能出现在 extra 字段值里；若改成 callable format，loguru 会把
    <span> 当颜色标记解析并直接抛 ValueError（这里的用例就是守这一点）。
    """
    assert _render_via_loguru(monkeypatch, "MFAAvalonia", "第一行\n第二行") == "warn:第一行\nwarn:第二行\n"
    assert _render_via_loguru(monkeypatch, "MXU", "第一行\n第二行") == (
        '<span style="color:darkorange;">第一行</span>\n<span style="color:darkorange;">第二行</span>\n'
    )
    assert _render_via_loguru(monkeypatch, "", "第一行\n第二行") == "\033[33m第一行\n第二行\033[0m\n"


def test_console_paths_agree_for_every_client(monkeypatch) -> None:
    """loguru 控制台与标准 logging 回退对同一输入、同一客户端必须一致（仅多一个结尾换行）。"""
    for client in ("MFAAvalonia", "MXU", ""):
        message = "第一行\n第二行"
        assert (
            _render_via_loguru(monkeypatch, client, message) == _ConsoleFormatter().format(_std_record(message)) + "\n"
        )
