"""
Application Logger - Singleton

Thread-safe, centralized logging with:
- Console output (INFO level)
- File output with rotation (DEBUG level)
- Consistent formatting
"""


from pathlib import Path
from typing import Optional
import sys

from loguru import logger as loguru_logger


class ApplicationLogger:
    """Singleton logger for entire application"""

    _instance: Optional['ApplicationLogger'] = None
    _configured: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._configured:
            self._configure()
            ApplicationLogger._configured = True

    def _configure(self):
        """Configure logger once"""
        # Remove default handler
        loguru_logger.remove()

        # Console handler (INFO)
        loguru_logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
            level="INFO",
            colorize=True
        )

        # File handler (DEBUG) with rotation
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        loguru_logger.add(
            "logs/sqpy_{time:YYYY-MM-DD}.log",
            rotation="00:00",  # Rotate at midnight
            retention="30 days",  # Keep logs for 30 days
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            encoding="utf-8"
        )

    def get_logger(self, module_name: str):
        """Get logger bound to module name"""
        return loguru_logger.bind(name=module_name)


# Global accessor (façana pattern)
def get_logger(module_name: str):
    """
    Get application logger for module

    Usage:
        from foundation.logging import get_logger

        logger = get_logger(__name__)
        logger.info("Message")
        logger.debug("Debug info")
        logger.error("Error occurred")
    """
    app_logger = ApplicationLogger()
    return app_logger.get_logger(module_name)
