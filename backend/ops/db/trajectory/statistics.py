# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Short PG transactions around a session advisory lock; archive scans hold no MVCC snapshot."""

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, text, update
from sqlalchemy.dialects.postgresql import insert

# isort: split
from management.db.client import db_client, get_db_session
from management.db.trajectory.models import TrajectoryStatistics as Statistics
from management.db.trajectory.repository import scope_uuid
from ops.db.trajectory.queries import BASE, _statement


@contextmanager
def scope_lock(kind, identity):
    key = int.from_bytes(
        hashlib.sha256(scope_uuid(kind, identity).encode()).digest()[:8], signed=True
    )
    with db_client.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        ).scalar()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
                except Exception:
                    connection.invalidate()
                    raise


def read_scope(kind, identity):
    key = scope_uuid(kind, identity)
    with get_db_session() as session:
        session.execute(
            insert(Statistics)
            .values(
                statistics_id=key,
                scope_type=kind,
                scope_id=identity,
                source_revision=1,
                computed_revision=0,
                complete=False,
                definition_version=1,
                created_by="trajectory",
                updated_by="trajectory",
                delete_flag="N",
            )
            .on_conflict_do_nothing(index_elements=[Statistics.statistics_id])
        )
        row = session.get(Statistics, key)
        return {
            column.name: getattr(row, column.name)
            for column in Statistics.__table__.columns
        }


def duration_statistics(tenants, asof):
    params = {"tenants": tenants, "asof": asof.replace(tzinfo=None)}
    # Terminal metric facts are immutable. Late publication is excluded by update_time.
    base = BASE + " AND e.create_time <= :asof"
    sql = f"""WITH base AS ({base}), valid AS (
        SELECT * FROM base WHERE status IN ('success','error','partial') AND update_time<=:asof
      ), conversations AS (
        SELECT CASE WHEN count(*)=count(duration_ms) THEN sum(duration_ms) END AS duration_ms
        FROM valid GROUP BY conversation_id
      )
      SELECT (SELECT count(*) FROM valid WHERE turn_no>0) AS execution_count,
        count(duration_ms) AS duration_sample_count,sum(duration_ms) AS duration_sum_ms,
        avg(duration_ms) AS duration_mean_ms,
        percentile_cont(0.5) WITHIN GROUP(ORDER BY duration_ms) AS duration_p50_ms,
        percentile_cont(0.9) WITHIN GROUP(ORDER BY duration_ms) AS duration_p90_ms,
        percentile_cont(0.99) WITHIN GROUP(ORDER BY duration_ms) AS duration_p99_ms,
        (SELECT count(duration_ms) FROM conversations) AS conversation_duration_sample_count,
        (SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY duration_ms) FROM conversations) AS conversation_duration_p50_ms,
        (SELECT percentile_cont(0.9) WITHIN GROUP(ORDER BY duration_ms) FROM conversations) AS conversation_duration_p90_ms,
        (SELECT percentile_cont(0.99) WITHIN GROUP(ORDER BY duration_ms) FROM conversations) AS conversation_duration_p99_ms
      FROM valid"""
    with get_db_session() as session:
        session.execute(text("SET LOCAL statement_timeout = '30000ms'"))
        data = dict(session.execute(_statement(sql), params).mappings().one())
        data["conversation_count"] = session.execute(
            text("""SELECT count(DISTINCT c.conversation_id)
            FROM nexent.conversation_record_t c
            JOIN nexent.user_tenant_t ut ON ut.user_id=c.created_by AND ut.delete_flag='N'
            JOIN nexent.user_account_t u ON u.user_id=c.created_by AND u.delete_flag='N'
            WHERE c.delete_flag='N' AND ut.tenant_id IN :tenants AND c.create_time<=:asof""").bindparams(
                bindparam("tenants", expanding=True)
            ),
            params,
        ).scalar()
        return data


def archive_rows(tenants, asof, batch=100):
    after = "00000000-0000-0000-0000-000000000000"
    while True:
        with get_db_session() as session:
            session.execute(text("SET LOCAL statement_timeout = '30000ms'"))
            rows = [
                dict(r)
                for r in session.execute(
                    _statement(
                        BASE
                        + """
              AND e.status IN ('success','error','partial') AND e.update_time<=:asof
              AND e.create_time<=:asof AND e.trajectory_id>:after
              ORDER BY e.trajectory_id LIMIT :limit"""
                    ),
                    {
                        "tenants": tenants,
                        "asof": asof.replace(tzinfo=None),
                        "after": after,
                        "limit": batch,
                    },
                ).mappings()
            ]
        if not rows:
            return
        yield from rows
        after = str(rows[-1]["trajectory_id"])


def publish(kind, identity, tenants, asof, revision, values):
    """Cleanup or ownership changes invalidate a scan; new runs leave it dirty for the next refresh."""
    with get_db_session() as session:
        session.execute(text("SET LOCAL statement_timeout = '30000ms'"))
        params = {"tenants": tenants, "asof": asof.replace(tzinfo=None)}
        invalid = session.execute(
            _statement("""SELECT EXISTS (
          SELECT 1 FROM nexent.trajectory_execution_t e
          JOIN nexent.user_tenant_t ut ON ut.user_id=e.created_by
          WHERE e.create_time<=:asof
          AND (ut.tenant_id IN :tenants AND e.update_time>:asof
               AND (e.status IN ('expired','corrupt') OR e.delete_flag='Y')
               OR ut.update_time>:asof)
        )"""),
            params,
        ).scalar()
        if invalid:
            return False
        session.execute(
            update(Statistics)
            .where(Statistics.statistics_id == scope_uuid(kind, identity))
            .values(
                **values,
                computed_revision=revision,
                computed_at=datetime.now(UTC),
                next_refresh_at=datetime.now(UTC) + timedelta(seconds=60),
                complete=True,
                definition_version=1,
                updated_by="trajectory",
                update_time=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        return True
