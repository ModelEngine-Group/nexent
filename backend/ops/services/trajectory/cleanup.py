# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scoped cleanup batches with a fixed UTC cutoff and bounded work."""

import time
from datetime import timedelta

from infrastructure.observability.trajectory_audit import cleanup_audit
from infrastructure.observability.trajectory_io import (
    TrajectoryConflict,
    TrajectoryCorrupt,
)
from infrastructure.observability.trajectory_store import parse_time, timestamp

from .access import authorize
from .archive import identity, storage_error
from .primitives import QueryError


def cleanup(service, actor, before_days, cursor=None):
    if type(before_days) is not int or not 1 <= before_days <= 3650:
        raise QueryError("invalid_before_days")
    # The authenticated current tenant is the only cleanup target; filters never select it.
    authorize(service.catalog, actor, actor.tenant_id)
    binding = {"actor": actor.binding, "tenant": actor.tenant_id, "days": before_days}
    state = (
        service.references.resolve(cursor, "cleanup", **binding)
        if cursor
        else {
            **binding,
            "cutoff": timestamp(
                service.archive.store.clock() - timedelta(days=before_days)
            ),
            "conversation_after": 0,
            "turn_after": 0,
        }
    )
    result = dict.fromkeys(
        (
            "scanned_runs",
            "deleted_runs",
            "deleted_bytes",
            "skipped_active",
            "pending_runs",
            "failed_runs",
        ),
        0,
    )
    with cleanup_audit(
        source="manual",
        actor_id=actor.user_id,
        tenant_id=actor.tenant_id,
        before_days=before_days,
        cutoff_at=state["cutoff"],
        counts=result,
    ):
        candidates = service.catalog.cleanup_candidates(
            actor.tenant_id, state["conversation_after"], limit=1001
        )
        deadline, progressed, next_state = time.monotonic() + 2, False, None
        store = service.archive.store
        try:
            with (
                store._root() as root,
                root.lock(".cleanup.lock", blocking=False),
            ):
                for row in candidates[:1000]:
                    if (
                        time.monotonic() >= deadline
                        or result["scanned_runs"] >= 1000
                        or result["deleted_runs"] >= 100
                    ):
                        next_state = state
                        break
                    service.recheck(actor, row)
                    meta = service.archive.manifest(row)
                    if meta:
                        batch = store.cleanup(
                            identity(row),
                            before_days=before_days,
                            cutoff_at=parse_time(state["cutoff"]),
                            after_turn=state["turn_after"]
                            if int(row["conversation_id"])
                            == state["conversation_after"]
                            else 0,
                            scan_limit=1000 - result["scanned_runs"],
                            delete_limit=100 - result["deleted_runs"],
                            deadline=deadline,
                            lock_held=True,
                        )
                        for key in result:
                            result[key] += batch[key]
                        if batch["next_turn"] is not None:
                            state = {
                                **state,
                                "conversation_after": int(row["conversation_id"]),
                                "turn_after": batch["next_turn"],
                            }
                            next_state = state
                            break
                    progressed = True
                    state = {
                        **state,
                        "conversation_after": int(row["conversation_id"]),
                        "turn_after": 2147483647,
                    }
                else:
                    if len(candidates) > 1000:
                        next_state = state
        except TrajectoryConflict as error:
            if "locked" in str(error):
                raise QueryError("cleanup_busy", 409, retry_after=2) from error
            raise storage_error(error) from error
        except (OSError, TrajectoryCorrupt) as error:
            raise storage_error(error) from error
        if next_state and not progressed and result["scanned_runs"] == 0:
            raise QueryError("cleanup_budget_exceeded", 503, retry_after=2)
        return {
            "cutoff_at": state["cutoff"],
            **result,
            "next_cursor": service.references.issue("cleanup", next_state)
            if next_state
            else None,
            "done": next_state is None,
        }
