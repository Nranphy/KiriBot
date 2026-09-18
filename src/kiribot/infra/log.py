"""初始化 Loguru 与 Uvicorn 日志"""

import logging
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    """将标准库日志转发到 Loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        logger.opt(exception=record.exc_info).log(record.levelno, record.getMessage())


def configure_logging(level: str) -> None:
    """配置控制台日志，重复调用不重复输出"""
    logger.remove()
    logger.add(sys.stderr, level=level, backtrace=False, diagnose=False)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [InterceptHandler()]
        target.setLevel(level)
        target.propagate = False
