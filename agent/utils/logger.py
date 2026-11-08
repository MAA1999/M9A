import html
import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from typing import Any

from . import pienv
from .runtime_paths import default_work_root

LEVEL_SHORT_NAMES = {
    "INFO": "info",
    "ERROR": "err",
    "WARNING": "warn",
    "DEBUG": "debug",
    "CRITICAL": "critical",
    "SUCCESS": "success",
    "TRACE": "trace",
}

ANSI_LEVEL_COLORS = {
    "TRACE": "\033[34m",
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "SUCCESS": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m\033[37m",
}

HTML_LEVEL_COLORS = {
    "TRACE": "royalblue",
    "DEBUG": "deepskyblue",
    "INFO": "forestgreen",
    "SUCCESS": "forestgreen",
    "WARNING": "darkorange",
    "ERROR": "crimson",
    "CRITICAL": "firebrick",
}


def _client_name_key() -> str:
    return pienv.client_name().strip().upper()


def _is_mfaa_client() -> bool:
    return _client_name_key() == "MFAAVALONIA"


def _is_mxu_client() -> bool:
    return _client_name_key() == "MXU"


def _resolve_console_stream():
    if _is_mxu_client():
        return sys.stdout
    return sys.stderr


def _short_level_name(level_name: str) -> str:
    return LEVEL_SHORT_NAMES.get(level_name, level_name.lower())


def _ansi_level_color(level_name: str) -> str:
    return ANSI_LEVEL_COLORS.get(level_name, "")


def _split_lines(message: str) -> list[str]:
    """按行拆分，丢掉结尾换行造成的空尾行。

    MFAAvalonia 把裸的 "info:" 也当作一条合法日志，尾行不丢会多出一条空日志条目。
    """
    lines = message.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


# MXU 的日志面板按 HTML 渲染。消息整体转义后只还原 material_catalog.colorize_name
# 产出的白名单标记（纯色名 + 六位色值），其余内容保持转义，避免注入。
_ESCAPED_FONT_MARKUP_RE = re.compile(r"&lt;font color=&quot;(#[0-9A-Fa-f]{6})&quot;&gt;(.*?)&lt;/font&gt;")


def _restore_font_markup(escaped: str) -> str:
    return _ESCAPED_FONT_MARKUP_RE.sub(lambda m: f'<font color="{m.group(1)}">{m.group(2)}</font>', escaped)


def _format_mxu_html_message(level_name: str, message: str) -> str:
    color = HTML_LEVEL_COLORS.get(level_name, "inherit")
    escaped = _restore_font_markup(html.escape(message))
    return "\n".join(f'<span style="color:{color};">{line}</span>' for line in _split_lines(escaped))


# MFAAvalonia 逐行解析 agent 输出，只认带 level 前缀的行，没有前缀的行会被它丢进自己的内部
# 日志、不进任务面板。多行消息因此必须逐行补前缀，否则第二行起在 GUI 里看不到。
def _format_mfaa_message(level_name: str, message: str) -> str:
    short = _short_level_name(level_name)
    return "\n".join(f"{short}:{line}" for line in _split_lines(message))


def _format_console_message(level_name: str, message: str) -> str:
    """控制台日志的唯一渲染分支，loguru 与标准 logging 两条路径共用。"""
    if _is_mfaa_client():
        return _format_mfaa_message(level_name, message)
    if _is_mxu_client():
        return _format_mxu_html_message(level_name, message)

    level_color = _ansi_level_color(level_name)
    color_reset = "\033[0m" if level_color else ""
    return f"{level_color}{message}{color_reset}"


_has_loguru = False
_loguru_logger: Any = None

try:
    from loguru import logger as _imported_loguru_logger

    _loguru_logger = _imported_loguru_logger
    _has_loguru = True
except ImportError:
    pass


class _ConsoleFormatter(logging.Formatter):
    """无 loguru 时的标准 logging 回退路径。"""

    def format(self, record: Any):
        return _format_console_message(record.levelname, record.getMessage())


# loguru 的格式串只取这一个字段。渲染结果必须走字段值，不能改成 callable format：
# loguru 会把 callable 的返回值再当格式串解析颜色标记（MXU 的 <span> 会直接抛错），
# 且 callable 路径不会补结尾换行。字段值在解析之后才代入，两个坑都不会踩到。
_CONSOLE_FORMAT = "{extra[console_message]}"


def _enrich_console_message(record: Any) -> bool:
    record["extra"]["console_message"] = _format_console_message(record["level"].name, str(record["message"]))
    return True


_FILE_FORMAT = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s")
_std_logger = logging.getLogger("m9a")


class _BraceFormatLogger:
    """Delegate wrapper that pre-renders loguru-style {} placeholders for stdlib logging.

    项目里的调用点大量写成 logger.debug("{}={}", key, value)。回退到标准 logging 时这些
    参数会被当 % 占位处理而抛 TypeError（Logging error）；这里在记录前先把 msg.format(*args) 展开。
    """

    def __init__(self, wrapped: logging.Logger) -> None:
        self._wrapped = wrapped

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    # 用户调用点到 logging 的内部帧共两层：debug()/info()/… 一层、_log() 一层。
    # findCaller 的默认 stacklevel=1 会停在 _log 里这一行，%(funcName)s:%(lineno)d 全部指错；
    # 在调用方给的 stacklevel 之上再补这两层包装帧。
    _WRAPPER_FRAMES = 2

    def _render(self, msg: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        if args and isinstance(msg, str):
            try:
                rendered = msg.format(*args, **{k: v for k, v in kwargs.items() if k != "exc_info"})
            except Exception:
                rendered = msg
            kwargs = {k: v for k, v in kwargs.items() if k in ("exc_info", "stack_info", "stacklevel", "extra")}
            return rendered, kwargs
        return msg, kwargs

    def _log(self, level: int, msg: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        msg, kwargs = self._render(msg, args, kwargs)
        kwargs["stacklevel"] = int(kwargs.get("stacklevel") or 1) + self._WRAPPER_FRAMES
        self._wrapped.log(level, msg, **kwargs)

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, args, kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, args, kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, args, kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, args, kwargs)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, args, kwargs)

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, args, kwargs)

    def opt(self, *args: Any, **kwargs: Any) -> "_BraceFormatLogger":
        return self  # loguru 特有；回退路径直接忽略 opt(...) 的语义，仍可用 .debug 等


def _resolve_level(level: Any) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def _setup_loguru_logger(log_dir: str = "debug/custom", console_level: str = "INFO"):
    os.makedirs(log_dir, exist_ok=True)
    _loguru_logger.remove()

    _loguru_logger.add(
        _resolve_console_stream(),
        format=_CONSOLE_FORMAT,
        colorize=False,
        level=console_level,
        filter=_enrich_console_message,
    )
    _loguru_logger.add(
        f"{log_dir}/{{time:YYYY-MM-DD}}.log",
        rotation="00:00",
        retention="2 weeks",
        compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )
    return _loguru_logger


def _setup_std_logger(log_dir: str = "debug/custom", console_level: str = "INFO"):
    os.makedirs(log_dir, exist_ok=True)

    _std_logger.handlers.clear()
    _std_logger.setLevel(logging.DEBUG)
    _std_logger.propagate = False

    console_handler = logging.StreamHandler(_resolve_console_stream())
    console_handler.setLevel(_resolve_level(console_level))
    console_handler.setFormatter(_ConsoleFormatter())
    _std_logger.addHandler(console_handler)

    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "runtime.log"),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_FILE_FORMAT)
    _std_logger.addHandler(file_handler)

    # 标准 logging 用 % 占位，loguru 用 {}。回退路径上把所有调用方的 {} 占位先渲染成
    # 最终字符串，否则 record.getMessage() 会在格式化时抛 TypeError（Logging error）。
    return _BraceFormatLogger(_std_logger)


def setup_logger(log_dir: str | None = None, console_level: str = "INFO"):
    """设置 logger（优先 loguru，无 loguru 时回退到标准 logging）"""
    resolved_log_dir = log_dir or str(default_work_root() / "debug" / "custom")
    if _has_loguru:
        return _setup_loguru_logger(log_dir=resolved_log_dir, console_level=console_level)
    return _setup_std_logger(log_dir=resolved_log_dir, console_level=console_level)


def change_console_level(level: str = "DEBUG"):
    """动态修改控制台日志等级"""
    setup_logger(console_level=level)
    logger.info(f"控制台日志等级已更改为: {level}")


logger = setup_logger()

__all__ = ["setup_logger", "change_console_level", "logger"]
