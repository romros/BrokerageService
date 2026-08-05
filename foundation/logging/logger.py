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


class CompatibleLogger:
    """Façana Loguru compatible amb missatges legacy de logging (%s, %d, %.nf)."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def _log(self, level: str, message, *args, **kwargs):
        if args and isinstance(message, str) and "%" in message:
            try:
                message = message % args
                args = ()
            except (TypeError, ValueError):
                pass
        return getattr(self._wrapped.opt(depth=2), level)(message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        return self._log("debug", message, *args, **kwargs)

    def info(self, message, *args, **kwargs):
        return self._log("info", message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        return self._log("warning", message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        return self._log("error", message, *args, **kwargs)

    def critical(self, message, *args, **kwargs):
        return self._log("critical", message, *args, **kwargs)

    def bind(self, **kwargs):
        return CompatibleLogger(self._wrapped.bind(**kwargs))

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


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

        # File handler (DEBUG) with rotation — tolerant a permisos (volum muntat root-owned)
        log_dir = Path("logs")
        try:
            log_dir.mkdir(exist_ok=True)
            loguru_logger.add(
                "logs/sqpy_{time:YYYY-MM-DD}.log",
                rotation="00:00",  # Rotate at midnight
                retention="30 days",  # Keep logs for 30 days
                level="DEBUG",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                encoding="utf-8"
            )
        except (PermissionError, OSError) as e:
            # Volum logs root-owned o no escribible → només stderr (servei arranca igual)
            loguru_logger.warning(f"Log file disabled (permissions): {e}")

    def get_logger(self, module_name: str):
        """Get logger bound to module name"""
        return CompatibleLogger(loguru_logger.bind(name=module_name))


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
