"""Background scheduler for evaluation maintenance tasks.

Runs independently of API requests — no fire-and-forget from request handlers.
"""
import logging
import threading
import time

from database.agent_evaluation_db import cleanup_aged_evaluations, reap_stale_runs
from database.client import get_db_session
from database.db_models import AgentEvaluation


logger = logging.getLogger(__name__)

# Check intervals (seconds)
STALE_CHECK_INTERVAL = 300   # every 5 minutes
AGED_CLEANUP_INTERVAL = 3600  # every hour

_running = False
_thread: threading.Thread | None = None


def _run_loop():
    """Maintenance loop: periodically reap stale runs and cleanup aged data."""
    last_cleanup = 0.0
    while _running:
        try:
            now = time.time()
            # Reap stale RUNNING tasks every STALE_CHECK_INTERVAL
            time.sleep(STALE_CHECK_INTERVAL)

            # Find all distinct tenant_ids that have any evaluation data
            with get_db_session() as session:
                tenants = session.query(AgentEvaluation.tenant_id).distinct().all()
            for (tid,) in tenants:
                try:
                    count = reap_stale_runs(tid)
                    if count:
                        logger.info("Reaped %d stale RUNNING evaluations for tenant %s", count, tid)
                except Exception as exc:
                    logger.warning("reap_stale_runs failed for tenant %s: %s", tid, exc)

            # Run aged cleanup every AGED_CLEANUP_INTERVAL
            if now - last_cleanup >= AGED_CLEANUP_INTERVAL:
                last_cleanup = now
                for (tid,) in tenants:
                    try:
                        count = cleanup_aged_evaluations(tid)
                        if count:
                            logger.info("Cleaned up %d aged evaluations for tenant %s", count, tid)
                    except Exception as exc:
                        logger.warning("cleanup_aged_evaluations failed for tenant %s: %s", tid, exc)

        except Exception as exc:
            logger.error("Evaluation maintenance loop error: %s", exc)
            time.sleep(60)  # back off on persistent failure


def start():
    """Start the evaluation maintenance background thread."""
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_run_loop, daemon=True, name="eval-maintenance")
    _thread.start()
    logger.info("Evaluation maintenance scheduler started (stale=%ds, aged=%ds)",
                STALE_CHECK_INTERVAL, AGED_CLEANUP_INTERVAL)


def stop():
    """Stop the maintenance thread (for clean shutdown)."""
    global _running
    _running = False
    logger.info("Evaluation maintenance scheduler stopped")
