"""Periodic cleanup for durable knowledge-base upload lifecycle rows."""

import logging
import threading
import time

from consts.const import (
    KB_FILE_LIFECYCLE_CLEANUP_INTERVAL_SECONDS,
    KB_FILE_LIFECYCLE_RETENTION_DAYS,
)
from database.knowledge_file_lifecycle_db import cleanup_expired_file_records

logger = logging.getLogger(__name__)

_running = False
_thread: threading.Thread | None = None


def _run_loop() -> None:
    """Run cleanup in a daemon thread; database failures are retried later."""
    global _running
    while _running:
        try:
            deleted = cleanup_expired_file_records(
                retention_days=KB_FILE_LIFECYCLE_RETENTION_DAYS,
            )
            if deleted:
                logger.info("Removed %d expired knowledge-file lifecycle rows", deleted)
        except Exception as exc:
            logger.warning("Knowledge-file lifecycle cleanup failed: %s", exc)
        time.sleep(max(60, KB_FILE_LIFECYCLE_CLEANUP_INTERVAL_SECONDS))


def start() -> None:
    """Start the process-local cleanup loop once."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(
        target=_run_loop,
        daemon=True,
        name="knowledge-file-maintenance",
    )
    _thread.start()


def stop() -> None:
    """Request loop shutdown during application shutdown."""
    global _running
    _running = False
