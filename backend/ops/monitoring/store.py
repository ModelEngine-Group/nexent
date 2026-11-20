# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent Ops PostgreSQL control store."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from ops.monitoring.contracts import day_id, stable_key


BATCH = "ops.ops_monitoring_ingest_batch_t"
DAY = "ops.ops_monitoring_day_state_t"


class ControlStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def verify_schema(self) -> None:
        with self.engine.connect() as conn:
            installed = conn.execute(text("SELECT to_regclass(:batch), to_regclass(:day)"),
                                     {"batch": BATCH, "day": DAY}).one()
            if not all(installed):
                raise RuntimeError("Apply the Ops monitoring SQL migration before enabling Ops monitoring")

    @contextmanager
    def lock(self, namespace: str, tenant: str, kind: str) -> Iterator[Connection]:
        """Hold a session lock across transactions and release it before pooling."""
        key = stable_key(namespace, tenant, kind)
        with self.engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
            conn.commit()
            try:
                yield conn
            finally:
                try:
                    conn.rollback()
                    conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
                    conn.commit()
                except Exception:
                    conn.invalidate()
                    raise

    def enqueue(self, batch_id: UUID, tenant: str, kind: str, payload: str, affected_dates: list[date]) -> None:
        scope = {"id": batch_id, "tenant": tenant, "kind": kind, "payload": payload, "dates": affected_dates}
        with self.lock("source", tenant, kind) as conn, conn.begin():
            conn.execute(text(f"""
                INSERT INTO {BATCH} (batch_id, tenant_id, fact_kind, replay_payload, affected_dates)
                VALUES (:id, :tenant, :kind, CAST(:payload AS jsonb), CAST(:dates AS date[]))
                ON CONFLICT (batch_id) DO NOTHING
            """), scope)

    def batch_scopes(self) -> list:
        with self.engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT DISTINCT tenant_id, fact_kind FROM {BATCH}
                WHERE batch_state IN ('queued', 'pending') AND delete_flag = 'N'
                ORDER BY tenant_id, fact_kind
            """)).all()

    def next_batch(self, conn, tenant, kind):
        return conn.execute(text(f"""
            SELECT batch_id, batch_state, replay_payload, affected_dates, write_version FROM {BATCH}
            WHERE tenant_id=:tenant AND fact_kind=:kind AND batch_state IN ('queued', 'pending')
                  AND delete_flag = 'N'
            ORDER BY write_version LIMIT 1
        """), {"tenant": tenant, "kind": kind}).mappings().first()

    def stage(self, conn, batch_id, payload, days):
        conn.execute(text(f"""
            UPDATE {BATCH} SET batch_state='pending', replay_payload=CAST(:payload AS jsonb),
                affected_dates=CAST(:days AS date[]), update_time=timezone('UTC', now())
            WHERE batch_id=:id
        """), {"id": batch_id, "payload": payload, "days": days})

    def batch_failed(self, conn, batch_id, error_code):
        conn.execute(text(f"""
            UPDATE {BATCH} SET attempt_count=attempt_count+1, last_error_code=:code,
                update_time=timezone('UTC', now()) WHERE batch_id=:id
        """), {"id": batch_id, "code": error_code})

    def confirm(self, conn, batch, tenant, kind, coverage):
        for day in batch["affected_dates"]:
            conn.execute(text(f"""
                INSERT INTO {DAY} AS state (day_state_id, tenant_id, fact_kind, statistic_date,
                    source_revision, available_from_at)
                VALUES (:id, :tenant, :kind, :day, :revision, :coverage)
                ON CONFLICT (day_state_id) DO UPDATE SET
                    source_revision=greatest(state.source_revision, EXCLUDED.source_revision),
                    available_from_at=least(state.available_from_at, EXCLUDED.available_from_at),
                    update_time=timezone('UTC', now())
            """), {"id": day_id(tenant, kind, day), "tenant": tenant, "kind": kind, "day": day,
                   "revision": batch["write_version"], "coverage": coverage.get(day.isoformat())})
        conn.execute(text(f"""
            UPDATE {BATCH} SET batch_state='confirmed', replay_payload=NULL,
                confirmed_at=now(), last_error_code=NULL, update_time=timezone('UTC', now())
            WHERE batch_id=:id
        """), {"id": batch["batch_id"]})

    def dirty_scopes(self) -> list:
        with self.engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT DISTINCT tenant_id, fact_kind FROM {DAY}
                WHERE (published_source_revision IS NULL OR source_revision > published_source_revision)
                      AND delete_flag = 'N'
                ORDER BY tenant_id, fact_kind
            """)).all()

    def published_scopes(self) -> list:
        with self.engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT DISTINCT tenant_id, fact_kind FROM {DAY}
                WHERE publish_id IS NOT NULL AND delete_flag='N'
                ORDER BY tenant_id, fact_kind
            """)).all()

    def published_days(self, conn, tenant, kind):
        return conn.execute(text(f"""
            SELECT statistic_date, publish_id FROM {DAY}
            WHERE tenant_id=:tenant AND fact_kind=:kind AND publish_id IS NOT NULL AND delete_flag='N'
            ORDER BY statistic_date
        """), {"tenant": tenant, "kind": kind}).all()

    def dirty_days(self, conn, tenant, kind):
        return conn.execute(text(f"""
            SELECT statistic_date, source_revision FROM {DAY}
            WHERE tenant_id=:tenant AND fact_kind=:kind AND delete_flag='N'
                AND (published_source_revision IS NULL OR source_revision > published_source_revision)
            ORDER BY statistic_date
        """), {"tenant": tenant, "kind": kind}).all()

    def publish(self, conn, tenant, kind, days, publish_id, timepoint):
        for day, revision in days:
            result = conn.execute(text(f"""
                UPDATE {DAY} SET published_source_revision=:revision, publish_id=:publish,
                    source_snapshot_at=:timepoint, published_at=now(), last_error_code=NULL,
                    update_time=timezone('UTC', now())
                WHERE day_state_id=:id AND delete_flag='N' AND source_revision >= :revision
                    AND (published_source_revision IS NULL OR published_source_revision < :revision)
            """), {"id": day_id(tenant, kind, day), "revision": revision,
                   "publish": publish_id, "timepoint": timepoint})
            if result.rowcount != 1:
                raise RuntimeError("Monitoring publication lost its revision")

    def states(self, tenant: str | None, kind: str, start: date, end: date) -> list[dict]:
        with self.read_states(tenant, kind, start, end) as states:
            return states

    @contextmanager
    def read_states(self, tenant: str | None, kind: str, start: date, end: date, *, lock=False):
        tenant_clause = "AND tenant_id=:tenant" if tenant is not None else ""
        lock_clause = "FOR SHARE" if lock else ""
        with self.engine.begin() as conn:
            yield list(conn.execute(text(f"""
                SELECT tenant_id, statistic_date, source_revision, published_source_revision,
                       publish_id, source_snapshot_at, available_from_at
                FROM {DAY}
                WHERE fact_kind=:kind AND statistic_date BETWEEN :start AND :end AND delete_flag='N'
                    {tenant_clause}
                ORDER BY tenant_id, statistic_date
                {lock_clause}
            """), {"tenant": tenant, "kind": kind, "start": start, "end": end}).mappings())

    def has_failed_batches(self, tenant: str | None, kind: str, start: date, end: date) -> bool:
        """Report failures for the requested scope, including old batches without date metadata."""
        tenant_clause = "AND tenant_id=:tenant" if tenant is not None else ""
        with self.engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT 1 FROM {BATCH}
                    WHERE fact_kind=:kind AND delete_flag='N' AND last_error_code IS NOT NULL
                        AND batch_state IN ('queued', 'pending') {tenant_clause}
                        AND (
                            cardinality(affected_dates)=0
                            OR EXISTS (SELECT 1 FROM unnest(affected_dates) AS dates(day)
                                       WHERE day BETWEEN :start AND :end)
                        )
                )
            """), {"tenant": tenant, "kind": kind, "start": start, "end": end}).scalar_one()

    def failed_batch_tenants(self, tenants: Iterable[str], kind: str, start: date, end: date) -> set[str]:
        """Read failed tenants once, retaining the single-tenant failure predicate."""
        selected = list(tenants)
        if not selected:
            return set()
        with self.engine.connect() as conn:
            return set(conn.execute(text(f"""
                SELECT DISTINCT tenant_id FROM {BATCH}
                WHERE tenant_id=ANY(:tenants) AND fact_kind=:kind AND delete_flag='N'
                    AND last_error_code IS NOT NULL AND batch_state IN ('queued', 'pending')
                    AND (
                        cardinality(affected_dates)=0
                        OR EXISTS (SELECT 1 FROM unnest(affected_dates) AS dates(day)
                                   WHERE day BETWEEN :start AND :end)
                    )
            """), {"tenants": selected, "kind": kind, "start": start, "end": end}).scalars())

    def ensure_today(self, today: date) -> None:
        """Schedule empty daily statistics for previously observed scopes."""
        with self.engine.begin() as conn:
            scopes = conn.execute(text(f"""
                SELECT tenant_id, fact_kind, min(available_from_at) AS coverage, max(statistic_date) AS latest
                FROM {DAY} WHERE delete_flag='N' GROUP BY tenant_id, fact_kind
            """)).mappings().all()
            for scope in scopes:
                start = max(scope['latest'] + timedelta(days=1), today - timedelta(days=365))
                for offset in range((today - start).days + 1):
                    day = start + timedelta(days=offset)
                    conn.execute(text(f"""
                        INSERT INTO {DAY} (day_state_id, tenant_id, fact_kind, statistic_date, available_from_at)
                        VALUES (:id, :tenant_id, :fact_kind, :day, :coverage)
                        ON CONFLICT (day_state_id) DO NOTHING
                    """), {**scope, "id": day_id(scope['tenant_id'], scope['fact_kind'], day), "day": day})

    def coverage_starts(self, tenants, kind):
        with self.engine.connect() as conn:
            return dict(conn.execute(text(f"""
                SELECT tenant_id, min(available_from_at) FROM {DAY}
                WHERE tenant_id=ANY(:tenants) AND fact_kind=:kind AND delete_flag='N'
                GROUP BY tenant_id HAVING min(available_from_at) IS NOT NULL
            """), {"tenants": list(tenants), "kind": kind}).all())
