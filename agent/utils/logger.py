import os
import sys

try:
    from loguru import logger as _logger

    def setup_logger(log_dir="debug/custom", console_level="INFO"):
        """设置 loguru logger

        Args:
            log_dir: 日志文件目录
            console_level: 控制台输出等级 (DEBUG, INFO, WARNING, ERROR)
        """
        os.makedirs(log_dir, exist_ok=True)
        _logger.remove()

        # 定义日志级别的简短格式
        def format_level(record):
            level_map = {
                "INFO": "info",
                "ERROR": "err",
                "WARNING": "warn",
                "DEBUG": "debug",
                "CRITICAL": "critical",
                "SUCCESS": "success",
                "TRACE": "trace",
            }
            record["extra"]["level_short"] = level_map.get(
                record["level"].name, record["level"].name.lower()
            )
            return True

        _logger.add(
            sys.stderr,
            format="<level>{extra[level_short]}</level>:<level>{message}</level>",
            colorize=True,
            level=console_level,
            filter=format_level,
        )
        _logger.add(
            f"{log_dir}/{{time:YYYY-MM-DD}}.log",
            rotation="00:00",  # midnight
            retention="2 weeks",
            compression="zip",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            encoding="utf-8",
            enqueue=True,
            backtrace=True,  # 包含完整的异常回溯信息
            diagnose=True,  # 包含变量值信息
        )
        return _logger

    def change_console_level(level="DEBUG"):
        """动态修改控制台日志等级"""
        setup_logger(console_level=level)
        _logger.info(f"控制台日志等级已更改为: {level}")

    logger = setup_logger()
except ImportError:
    import logging

    class ShortLevelFormatter(logging.Formatter):
        """自定义 Formatter，使用简短的日志级别名称"""

        level_map = {
            "INFO": "info",
            "ERROR": "err",
            "WARNING": "warn",
            "DEBUG": "debug",
            "CRITICAL": "critical",
        }

        def format(self, record):
            record.level_short = self.level_map.get(
                record.levelname, record.levelname.lower()
            )
            return super().format(record)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ShortLevelFormatter("%(level_short)s:%(message)s"))
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
    logger = logging
