# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PostgreSQL connection and idempotent monitoring batch ingestion."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from uuid import UUID

from sqlalchemy import Engine, URL, create_engine, text
from sqlalchemy.engine import Connection

from contracts.constants.environment import (
    OPS_POSTGRES_DB,
    NEXENT_POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from infrastructure.monitoring.contracts import stable_key


BATCH = "ops.ops_monitoring_ingest_batch_t"
DAY = "ops.ops_monitoring_day_state_t"


def monitoring_engine():
    if not POSTGRES_HOST or not POSTGRES_USER or not OPS_POSTGRES_DB:
        raise RuntimeError("Ops monitoring requires the Nexent PostgreSQL connection")
    if OPS_POSTGRES_DB == (POSTGRES_DB or "nexent"):
        raise ValueError("OPS_POSTGRES_DB must differ from POSTGRES_DB")
    if len(OPS_POSTGRES_DB.encode("utf-8")) > 63:
        raise ValueError("OPS_POSTGRES_DB must not exceed 63 UTF-8 bytes")
    url = URL.create("postgresql+psycopg2", username=POSTGRES_USER, password=NEXENT_POSTGRES_PASSWORD,
                     host=POSTGRES_HOST, port=POSTGRES_PORT, database=OPS_POSTGRES_DB)
    return create_engine(url, pool_size=4, max_overflow=2, pool_pre_ping=True,
                         connect_args={"connect_timeout": 3, "options": "-c lock_timeout=4000"})


class BatchStore:
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
