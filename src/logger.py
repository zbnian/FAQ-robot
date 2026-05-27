"""
日志模块 - 时间轮转日志，保留7天
"""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime
from config.settings import settings


def setup_logger(name: str = "faq-bot") -> logging.Logger:
    """
    设置日志

    Args:
        name: 日志记录器名称

    Returns:
        Logger实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "faq-bot.log"

    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=settings.log_retention_days,
        encoding="utf-8"
    )

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    return logger


logger = setup_logger()