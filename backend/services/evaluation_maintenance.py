"""Background scheduler for evaluation maintenance tasks.

Runs independently of API requests — no fire-and-forget from request handlers.
"""
import logging
import threading
import time

from database.agent_evaluation_db import (
    cleanup_aged_evaluations,
    list_dispatchable_pending_runs,
    reap_stale_runs,
)
from database.client import get_db_session
from database.db_models import AgentEvaluation


logger = logging.getLogger(__name__)

# Check intervals (seconds)
STALE_CHECK_INTERVAL = 300   # every 5 minutes
AGED_CLEANUP_INTERVAL = 3600  # every hour

_running = False
_thread: threading.Thread | None = None


def _run_tenant_task(tenants, task, log_template, warn_label):
    """Run *task* for each tenant, logging results and swallowing per-tenant errors."""
    for (tid,) in tenants:
        try:
            count = task(tid)
            if count:
                logger.info(log_template, count, tid)
        except Exception as exc:
            logger.warning("%s failed for tenant %s: %s", warn_label, tid, exc)


def _dispatch_pending_runs(runs):
    """Resume durable pending runs through the existing runtime dispatcher."""
    if not runs:
        return

    from services.runtime_proxy_service import dispatch_agent_evaluation_run

    for run in runs:
        run_id = run.get("agent_evaluation_id")
        tenant_id = run.get("tenant_id")
        user_id = run.get("created_by")
        if not run_id or not tenant_id or not user_id:
            logger.warning(
                "Cannot redispatch pending evaluation %s without tenant and creator",
                run_id,
            )
            continue
        try:
            dispatch_agent_evaluation_run(
                agent_evaluation_id=int(run_id),
                user_id=str(user_id),
                tenant_id=str(tenant_id),
            )
        except Exception as exc:
            # Keep the row PENDING. The next maintenance pass can use the same
            # idempotent runtime claim once the runtime service is available.
            logger.warning(
                "Pending evaluation dispatch failed for run %s: %s",
                run_id,
                exc,
            )


def _run_loop():
    """Maintenance loop: periodically reap stale runs and cleanup aged data."""
    last_cleanup = 0.0
    while _running:
        try:
            now = time.time()
            _dispatch_pending_runs(list_dispatchable_pending_runs())

            # Reap stale RUNNING tasks every STALE_CHECK_INTERVAL
            time.sleep(STALE_CHECK_INTERVAL)

            # Find all distinct tenant_ids that have any evaluation data
            with get_db_session() as session:
                tenants = session.query(AgentEvaluation.tenant_id).distinct().all()

            _run_tenant_task(
                tenants,
                reap_stale_runs,
                "Reaped %d stale RUNNING evaluations for tenant %s",
                "reap_stale_runs",
            )

            # Run aged cleanup every AGED_CLEANUP_INTERVAL
            if now - last_cleanup >= AGED_CLEANUP_INTERVAL:
                last_cleanup = now
                _run_tenant_task(
                    tenants,
                    cleanup_aged_evaluations,
                    "Cleaned up %d aged evaluations for tenant %s",
                    "cleanup_aged_evaluations",
                )

        except Exception as exc:
            logger.exception("Evaluation maintenance loop error: %s", exc)
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
