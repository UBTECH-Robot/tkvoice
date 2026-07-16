
import logging
from logging import StreamHandler, Formatter

# 通用日志等级，可以在这里修改
LOG_LEVEL = logging.INFO  # DEBUG / INFO / WARNING / ERROR / CRITICAL

def setup_logger(name=None):
    """
    创建一个 logger，并使用统一格式和日志级别。
    :param name: 日志名，None 表示 root logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    if not logger.hasHandlers():
        handler = StreamHandler()
        formatter = Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
