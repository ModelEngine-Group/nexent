# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Background-only exact statistics, with bounded archive work and complete publication."""

import logging
import threading
import time
from datetime import UTC, datetime

from ops.db.trajectory.catalog import TrajectoryCatalog

logger = logging.getLogger(__name__)


class StatisticsRefresher:
    def __init__(self, store, repository):
        from .projection import Projector

        self.projector = Projector(store, repository)
        self.repository = repository
        self._cache = {}
        self._cache_bytes = 0

    def refresh(self, tenants, kind, identity, check=lambda: None):
        from infrastructure.observability.trajectory_reader import JSONReader
        from ops.db.trajectory import statistics as database

        from .nodes import build_nodes
        from .primitives import Budget
        from .quantiles import DiskQuantiles

        with database.scope_lock(kind, identity) as acquired:
            if not acquired:
                return False
            record = database.read_scope(kind, identity)
            asof = datetime.now(UTC)
            if (
                record["complete"]
                and record["source_revision"] == record["computed_revision"]
                and record["next_refresh_at"]
                and record["next_refresh_at"] > asof
            ):
                return True
            values = database.duration_statistics(tenants, asof)
            with DiskQuantiles(check) as quantiles:
                for row in database.archive_rows(tenants, asof):
                    check()
                    owner = {
                        "tenant_id": row["tenant_id"],
                        "user_id": row["user_id"],
                        "conversation_id": str(row["conversation_id"]),
                        "agent_id": str(row["agent_id"])
                        if row["agent_id"] is not None
                        else None,
                    }
                    from infrastructure.observability.trajectory_store import (
                        CaptureIdentity,
                    )

                    ident = CaptureIdentity(
                        owner["tenant_id"],
                        owner["user_id"],
                        owner["conversation_id"],
                        owner["agent_id"],
                    )
                    meta = self.projector.store.manifest(ident)
                    run = self.projector.store._run(meta, str(row["trajectory_id"]))
                    if self.projector.archive.available(run) not in {
                        "available",
                        "partial",
                    }:
                        raise ValueError("Statistics archive is no longer readable")
                    cache_key = (
                        str(row["trajectory_id"]),
                        run["confirmed_sha256"],
                        meta["cleanup_version"],
                    )
                    samples = self._cache.get(cache_key)
                    if samples is None:
                        budget = Budget(seconds=30, max_bytes=256 * 1024 * 1024)

                        def checked(current_budget=budget, **kwargs):
                            check()
                            current_budget.check(**kwargs)

                        with self.projector.archive.opened(
                            owner, str(row["trajectory_id"]), budget
                        ) as (fd, _, confirmed):
                            nodes, _, _ = build_nodes(
                                JSONReader(
                                    fd, confirmed["confirmed_bytes"], check=checked
                                ).requests(),
                                conversation_id=ident.conversation_id,
                                complete=confirmed["capture_state"] == "ready",
                                check=checked,
                            )
                        samples = tuple(
                            n["ttft_ms"]
                            for n in nodes
                            if n["kind"] == "model" and n.get("ttft_ms") is not None
                        )
                        size = 256 + len(samples) * 32
                        if size < 64 * 1024 * 1024:
                            if self._cache_bytes + size > 64 * 1024 * 1024:
                                self._cache.clear()
                                self._cache_bytes = 0
                            self._cache[cache_key] = samples
                            self._cache_bytes += size
                    for value in samples:
                        quantiles.add(value)
                values.update(
                    {"ttft_" + key: value for key, value in quantiles.result().items()}
                )
            check()
            return database.publish(
                kind, identity, tenants, asof, record["source_revision"], values
            )


class SummaryWorker:
    """One managed service; scan compensation and refresh without blocking capture."""

    def __init__(self, store, repository):
        from .projection import Projector

        self.store, self.repository = store, repository
        self.projector = Projector(store, repository)
        self._pending = {}
        self._pending_lock = threading.Lock()
        self.store.on_publish = self.notify
        self._iterator = None
        self._next_scan = 0
        self._stopping = False

    def notify(self, identity):
        key = (identity.tenant_id, identity.owner_user_id, identity.conversation_id)
        with self._pending_lock:
            if len(self._pending) >= 1000 and key not in self._pending:
                logger.warning("trajectory.summary_queue_full")
                return
            self._pending[key] = identity

    def request_stop(self):
        self._stopping = True

    def check(self):
        if self._stopping:
            raise InterruptedError("Trajectory summary worker is stopping")

    def run(self, cancel_event):
        try:
            while not self._stopping and not cancel_event.is_set():
                try:
                    self.tick()
                except Exception as error:  # noqa: BLE001 - Keep background failures retryable and isolate Agent capture.
                    logger.warning(
                        "trajectory.summary_refresh_deferred exception_type=%s",
                        type(error).__name__,
                    )
                cancel_event.wait(0.2)
        finally:
            if self._iterator is not None:
                self._iterator.close()

    def tick(self):
        self.check()
        with self._pending_lock:
            pending = (
                self._pending.pop(next(iter(self._pending))) if self._pending else None
            )
        if pending is not None:
            self.projector.sync(pending, self.check)
        now = time.monotonic()
        if self._iterator is None and now >= self._next_scan:
            self.repository.placeholders()
            self.repository.compact()
            self._iterator = self.store.identities()
        if self._iterator is not None:
            try:
                identity = next(self._iterator)
            except StopIteration:
                self._iterator = None
                self._next_scan = now + 60
            else:
                try:
                    self.projector.sync(identity, self.check)
                except PermissionError:
                    pass
                except Exception as error:  # noqa: BLE001 - Keep background failures retryable and isolate Agent capture.
                    logger.warning(
                        "trajectory.summary_sync_deferred exception_type=%s",
                        type(error).__name__,
                    )
                return


class StatisticsWorker:
    """Refresh independently so a long historical scan never delays new execution projections."""

    def __init__(self, store, repository):
        self.refresher = StatisticsRefresher(store, repository)
        self._stopping = False

    def request_stop(self):
        self._stopping = True

    def check(self):
        if self._stopping:
            raise InterruptedError("Trajectory statistics worker is stopping")

    def run(self, cancel_event):
        while not self._stopping and not cancel_event.is_set():
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 - Background refresh leaves the last complete result readable.
                logger.warning(
                    "trajectory.statistics_check_deferred exception_type=%s",
                    type(error).__name__,
                )
            cancel_event.wait(60)

    def tick(self):
        from ops.services.trajectory.access import Actor

        tenants = TrajectoryCatalog().tenants(Actor("trajectory", "", "SU"))
        for kind, identity, scope in [("tenant", t, [t]) for t in tenants] + [
            ("global", "global", tenants)
        ]:
            self.check()
            try:
                self.refresher.refresh(scope, kind, identity, self.check)
            except Exception as error:  # noqa: BLE001 - Retry the failed scope without hiding other scopes.
                logger.warning(
                    "trajectory.statistics_refresh_deferred scope_type=%s exception_type=%s",
                    kind,
                    type(error).__name__,
                )
