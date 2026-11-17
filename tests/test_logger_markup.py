import io
import logging
import sys
from pathlib import Path

from loguru import logger as loguru_logger

from agent.utils import pienv
from agent.utils.logger import (
    _CONSOLE_FORMAT,
    _ConsoleFormatter,
    _enrich_console_message,
    _enrich_file_template,
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


def test_fallback_stacklevel_points_at_caller(caplog) -> None:
    """标准 logging 回退路径的 funcName/lineno 必须指向调用方，而不是 _log 内部。

    包装类在调用方之上多叠两层帧（debug()/info()/_log），findCaller 默认会停在内
    部那一行；修正是把包装帧数加进 stacklevel。
    """
    from agent.utils.logger import _BraceFormatLogger

    wrapper = _BraceFormatLogger(logging.getLogger("m9a-test"))
    with caplog.at_level(logging.INFO, logger="m9a-test"):
        wrapper.info("定位测试")  # ← 断言应指到这一行
    caller_lineno = sys._getframe().f_lineno - 1

    assert caplog.records
    record = caplog.records[-1]
    assert record.funcName == "test_fallback_stacklevel_points_at_caller"
    assert record.filename == Path(__file__).name
    assert record.lineno == caller_lineno


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _brace_logger() -> tuple[logging.Logger, _ListHandler]:
    from agent.utils.logger import _BraceFormatLogger

    handler = _ListHandler()
    wrapped = logging.getLogger("m9a-brace-format-test")
    wrapped.handlers.clear()
    wrapped.propagate = False
    wrapped.setLevel(logging.DEBUG)
    wrapped.addHandler(handler)
    return _BraceFormatLogger(wrapped), handler  # type: ignore[return-value]


def test_brace_logger_leaves_percent_placeholders_to_stdlib() -> None:
    """%s 消息不能走 str.format：format 会忽略多余参数，%s 会原样打进日志。"""
    logger, handler = _brace_logger()
    logger.error("DisableNode: %s", "missing")

    assert handler.records[0].getMessage() == "DisableNode: missing"


def test_brace_logger_expands_brace_placeholders() -> None:
    logger, handler = _brace_logger()
    logger.debug("{}={}", "key", "value")

    assert handler.records[0].getMessage() == "key=value"


def _file_log_record(message: str, *args: object) -> logging.LogRecord:
    """走 loguru 0.8 真实路径取 record，再喂给文件 sink 的 template filter 与 format。"""
    records = []

    def sink(msg) -> None:
        records.append(msg.record)

    sink_id = loguru_logger.add(sink, format="{message}")
    try:
        loguru_logger.debug(message, *args)
    finally:
        loguru_logger.remove(sink_id)
    return records[0]


def test_file_sink_template_field_tracks_brace_call_sites() -> None:
    """有占位符时文件日志应附 template（同一调用点不同参数聚成一条的关键）。"""
    record = _file_log_record("{}={}", "key", "value")
    _enrich_file_template(record)
    assert record["extra"]["template"] == " | tpl={}={}"


def test_file_sink_template_field_blank_when_no_placeholders() -> None:
    """无占位符时 message 即 template，按 message 聚合等价，附字段留空省一格。"""
    record = _file_log_record("plain literal")
    _enrich_file_template(record)
    assert record["extra"]["template"] == ""


def test_file_sink_format_appends_timezone_and_template() -> None:
    """文件 sink 的 format 必须带时区偏移（跨时区排查不用猜）+ template 字段。"""
    buf = io.StringIO()
    sink_id = loguru_logger.add(
        buf,
        format="{time:YYYY-MM-DD HH:mm:ss.SSSZ} | {level: <8} | {name}:{function}:{line} | {message}{extra[template]}",
        filter=_enrich_file_template,
    )
    try:
        loguru_logger.debug("{}={}", "key", "value")
    finally:
        loguru_logger.remove(sink_id)
    line = buf.getvalue().rstrip("\n")
    # 末尾的时区偏移如 +08:00 / -05:00 / Z
    import re

    assert re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}(?:Z|[+-]\d{2}:\d{2}) \| DEBUG", line)
    assert line.endswith("key=value | tpl={}={}")
