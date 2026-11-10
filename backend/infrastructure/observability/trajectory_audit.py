# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Emit safe cleanup facts without changing the operation's result or failure."""

import json
import logging
from contextlib import contextmanager

from contracts.errors.trajectory import QueryError

from .trajectory_io import TrajectoryConflict, TrajectoryCorrupt

logger = logging.getLogger(__name__)
COUNTERS = (
    "scanned_runs",
    "deleted_runs",
    "deleted_bytes",
    "skipped_active",
    "pending_runs",
    "failed_runs",
)
SAFE_ERRORS = {
    "trajectory_not_found",
    "administrator_required",
    "cleanup_busy",
    "storage_busy",
    "storage_unavailable",
    "trajectory_corrupt",
    "lookup_unavailable",
    "cleanup_budget_exceeded",
    "query_budget_exceeded",
}


def _error_code(error):
    if isinstance(error, QueryError) and error.code in SAFE_ERRORS:
        return error.code
    if isinstance(error, TrajectoryCorrupt):
        return "trajectory_corrupt"
    if isinstance(error, TrajectoryConflict):
        return "storage_busy"
    if isinstance(error, OSError):
        return "storage_unavailable"
    return "cleanup_failed" if isinstance(error, Exception) else "cleanup_interrupted"


def _identifier(value):
    return "".join(str(value).split())[:256] if value is not None else None


@contextmanager
def cleanup_audit(
    *,
    source,
    tenant_id,
    before_days,
    cutoff_at,
    counts,
    actor_id=None,
    conversation_id=None,
    emit_empty=True,
):
    """Log one accepted batch; counters are confirmed progress if the batch raises."""
    error = None
    try:
        yield
    except BaseException as caught:
        error = caught
        raise
    finally:
        try:
            counters = {key: counts.get(key, 0) for key in COUNTERS}
            changed = any(
                counters[key] for key in ("deleted_runs", "pending_runs", "failed_runs")
            )
            if emit_empty or changed or error is not None:
                failed = error is not None or counters["failed_runs"] > 0
                event = {
                    "source": source,
                    "actor_id": _identifier(actor_id),
                    "tenant_id": _identifier(tenant_id),
                    "conversation_id": _identifier(conversation_id),
                    "before_days": before_days,
                    "cutoff_at": cutoff_at,
                    **counters,
                    "counts_complete": error is None,
                    "status": "failed"
                    if failed
                    else ("pending" if counters["pending_runs"] else "success"),
                    "error_code": _error_code(error)
                    if error is not None
                    else ("delete_failed" if counters["failed_runs"] else None),
                }
                logger.log(
                    logging.WARNING if failed else logging.INFO,
                    "trajectory.cleanup %s",
                    json.dumps(event, separators=(",", ":"), allow_nan=False),
                )
        except Exception:  # noqa: BLE001, S110 - A failed log handler must not mask cleanup or recurse into logging.
            pass
