from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler


def _console_formatter() -> logging.Formatter:
    return logging.Formatter("%(levelname).1s:%(message)s")


def _file_formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    )


def setup_logger(log_dir: str = "debug/custom", console_level: str = "INFO") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("agent")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(resolve_level(console_level))
    console_handler.setFormatter(_console_formatter())
    logger.addHandler(console_handler)

    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "runtime.log"),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_file_formatter())
    logger.addHandler(file_handler)
    return logger


def change_console_level(level: str) -> None:
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(resolve_level(level))


def resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, level.upper(), logging.INFO)


logger = setup_logger()
