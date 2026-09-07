import logging
import logging.config
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from consts.const import (
    IS_DEBUG,
    LOG_BACKUP_COUNT,
    LOG_DIR,
    LOG_LEVEL,
    LOG_MAX_BYTES,
    LOG_ROTATION_INTERVAL,
)


class ColorFormatter(logging.Formatter):
    COLOR_MAP = {
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLOR_MAP.get(record.levelname, "")
        message = super().format(record)
        if color:
            message = f"{color}{message}{self.RESET}"
        return message


class HybridRotatingFileHandler(TimedRotatingFileHandler):
    """A handler that rotates on both time and size, whichever comes first.

    Rotation is triggered when EITHER:
      - The configured interval (LOG_ROTATION_INTERVAL days at midnight) has elapsed, OR
      - The current file exceeds LOG_MAX_BYTES.

    This avoids the common issue where a large log file grows unbounded between
    two rotation time windows.
    """

    def __init__(
        self,
        filename: str | Path,
        interval: int = 1,
        backupCount: int = 0,
        maxBytes: int = 0,
        **kwargs,
    ):
        self._max_bytes = maxBytes
        super().__init__(filename, interval=interval, backupCount=backupCount, **kwargs)

    def shouldRollover(self, record: logging.LogRecord) -> int:
        """Return > 0 if rollover needed, 0 otherwise."""
        # Check time-based rollover first (inherited from TimedRotatingFileHandler)
        time_check = super().shouldRollover(record)
        if time_check:
            return time_check

        # Check size-based rollover
        if self._max_bytes <= 0:
            return 0

        try:
            pos = self.stream.tell()
            if pos >= self._max_bytes:
                return 1
        except Exception:
            pass

        return 0

    def doRollover(self):
        self.mode = "a"
        super().doRollover()


def _make_file_handler(category: str) -> logging.Handler:
    """Create a hybrid time+size rotating file handler for a given category.

    Rotation is triggered when EITHER:
      - The configured interval (LOG_ROTATION_INTERVAL days at midnight) has elapsed, OR
      - The current file exceeds LOG_MAX_BYTES.

    The log file lives at: {LOG_DIR}/{category}/nexent_{category}.log
    """
    log_dir = Path(LOG_DIR)
    category_dir = log_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)
    log_path = category_dir / f"nexent_{category}.log"

    handler: logging.Handler = HybridRotatingFileHandler(
        log_path,
        when="midnight",
        interval=LOG_ROTATION_INTERVAL,
        backupCount=LOG_BACKUP_COUNT,
        maxBytes=LOG_MAX_BYTES,
        encoding="utf-8",
    )

    # File format (no color, machine-parseable)
    fmt = "%(asctime)s  %(levelname)-8s  %(name)-25s  %(message)s"
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    return handler


def _make_console_handler() -> logging.Handler:
    """Create a console handler with color formatting."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        ColorFormatter("[%(asctime)s %(levelname)-1s %(name)-1s] %(message)s", datefmt="%H:%M:%S")
    )
    return handler


def configure_logging(level: int | None = None, categories: list[str] | None = None):
    """Configure root logger with console + file handlers.

    Args:
        level: Log level for the root logger. If None, the effective level is
            computed as DEBUG when IS_DEBUG=true, otherwise LOG_LEVEL.
        categories: List of log categories to create file handlers for.
                    Defaults to the standard Nexent categories.
    """
    if categories is None:
        categories = ["config", "runtime", "northbound", "data_process", "model_call"]

    if level is None:
        level = logging.DEBUG if IS_DEBUG else getattr(logging, LOG_LEVEL, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Console handler (always present)
    root_logger.addHandler(_make_console_handler())

    # File handler per category
    for cat in categories:
        root_logger.addHandler(_make_file_handler(cat))

    root_logger.setLevel(level)


def get_uvicorn_logging_config(categories: list[str] | None = None) -> dict:
    """Return a dict-compatible logging config for uvicorn's log_config parameter.

    This config mirrors configure_logging(): console (color) + one file handler per
    category.  Pass this dict to uvicorn.run(..., log_config=get_uvicorn_logging_config())
    and call logging.config.dictConfig(config) yourself before starting uvicorn.
    """
    if categories is None:
        categories = ["config", "runtime", "northbound", "data_process", "model_call"]

    effective_level = "DEBUG" if IS_DEBUG else LOG_LEVEL
    level = effective_level  # string: "DEBUG" or "INFO"

    # --- Console handler (color, stdout) ---
    console_handler: dict[str, object] = {
        "class": "logging.StreamHandler",
        "level": level,
        "formatter": "color",
        "stream": "ext://sys.stdout",
    }

    # --- File handler per category (hybrid time+size) ---
    file_handlers: dict[str, object] = {}
    for cat in categories:
        cat_key = f"file_{cat}"
        log_dir = Path(LOG_DIR)
        log_path = str(log_dir / cat / f"nexent_{cat}.log")
        (log_dir / cat).mkdir(parents=True, exist_ok=True)

        file_handlers[cat_key] = {
            "class": f"{__name__}.HybridRotatingFileHandler",
            "level": level,
            "formatter": "plain",
            "filename": log_path,
            "when": "midnight",
            "interval": LOG_ROTATION_INTERVAL,
            "backupCount": LOG_BACKUP_COUNT,
            "maxBytes": LOG_MAX_BYTES,
            "encoding": "utf-8",
        }

    # --- Formatters ---
    formatters: dict[str, object] = {
        "color": {
            "()": f"{__name__}.ColorFormatter",
            "format": "[%(asctime)s %(levelname)-1s %(name)-1s] %(message)s",
            "datefmt": "%H:%M:%S",
        },
        "plain": {
            "format": "%(asctime)s  %(levelname)-8s  %(name)-25s  %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }

    # --- Root logger: console + all file handlers ---
    handler_names = ["console"] + [f"file_{cat}" for cat in categories]
    config: dict[str, object] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": {**{"console": console_handler}, **file_handlers},
        "root": {"level": level, "handlers": handler_names},
    }
    return config


def configure_elasticsearch_logging():
    """Configure logging for Elasticsearch client to reduce verbosity."""
    logging.getLogger("elastic_transport.transport").setLevel(logging.WARNING)
    logging.getLogger("elasticsearch.trace").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
