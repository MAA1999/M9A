import logging

from agent.utils import pienv
from agent.utils.logger import (
    _ConsoleFormatter,
    _enrich_record,
    _format_mfaa_message,
    _format_mxu_html_message,
    _resolve_console_format,
)


def _use_mfaa_client(monkeypatch) -> None:
    """让 logger 走 MFAAvalonia 分支（logger.py 通过 pienv.client_name() 判定客户端）。"""
    monkeypatch.setattr(pienv, "client_name", lambda: "MFAAvalonia")


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


def test_console_formatter_prefixes_every_line_for_mfaa(monkeypatch) -> None:
    """无 loguru 时的标准 logging 回退路径同样要逐行补前缀。"""
    _use_mfaa_client(monkeypatch)
    record = logging.LogRecord("m9a", logging.WARNING, __file__, 1, "第一行\n第二行", None, None)
    assert _ConsoleFormatter().format(record) == "warn:第一行\nwarn:第二行"


def test_resolve_console_format_uses_mfaa_message(monkeypatch) -> None:
    """loguru 路径的格式串必须取逐行前缀后的字段，而不是裸 message。"""
    _use_mfaa_client(monkeypatch)
    assert _resolve_console_format() == "{extra[mfaa_message]}"


def test_enrich_record_fills_mfaa_message() -> None:
    """loguru 路径靠 filter 填充 extra，格式串取不到该字段会直接报错，这里守住填充。"""

    class _Level:
        name = "ERROR"

    extra: dict[str, object] = {}
    record: dict[str, object] = {"level": _Level(), "message": "第一行\n第二行", "extra": extra}
    assert _enrich_record(record) is True
    assert extra["mfaa_message"] == "err:第一行\nerr:第二行"
