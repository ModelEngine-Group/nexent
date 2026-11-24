# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Control-store binding, revision guards and empty-day scheduling boundaries."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from ops.monitoring.contracts import day_id
from ops.monitoring.store import ControlStore


DAY = date(2026, 11, 23)


@pytest.fixture
def database():
    engine, conn = MagicMock(), MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.begin.return_value.__enter__.return_value = conn
    return ControlStore(engine), conn


def statement(conn, index=-1):
    args = conn.execute.call_args_list[index].args
    return " ".join(str(args[0]).split()), args[1] if len(args) > 1 else None


@pytest.mark.parametrize("method,predicate", [
    ("batch_scopes", "batch_state IN ('queued', 'pending')"),
    ("dirty_scopes", "source_revision > published_source_revision"),
    ("published_scopes", "publish_id IS NOT NULL"),
])
def test_scope_enumeration_keeps_only_active_work(database, method, predicate):
    store, conn = database
    conn.execute.return_value.all.return_value = [("t", "model")]
    assert getattr(store, method)() == [("t", "model")]
    sql, _ = statement(conn)
    assert predicate in sql and "delete_flag" in sql
    assert "ORDER BY tenant_id, fact_kind" in sql


def test_batch_read_staging_and_failure_keep_identity_and_order(database):
    store, conn = database
    batch = {"batch_id": "b", "batch_state": "queued", "write_version": 7}
    conn.execute.return_value.mappings.return_value.first.return_value = batch
    assert store.next_batch(conn, "t", "model") is batch
    sql, params = statement(conn)
    assert "ORDER BY write_version LIMIT 1" in sql and "delete_flag = 'N'" in sql
    assert params == {"tenant": "t", "kind": "model"}
    store.stage(conn, "b", '{"writes":[]}', [DAY])
    sql, params = statement(conn)
    assert "batch_state='pending'" in sql and "CAST(:payload AS jsonb)" in sql
    assert params == {"id": "b", "payload": '{"writes":[]}', "days": [DAY]}
    store.batch_failed(conn, "b", "WRITE_FAILED")
    sql, params = statement(conn)
    assert "attempt_count=attempt_count+1" in sql
    assert params == {"id": "b", "code": "WRITE_FAILED"}


def test_confirmation_marks_all_affected_days_before_discarding_replay(database):
    store, conn = database
    previous = DAY - timedelta(days=1)
    store.confirm(conn, {"batch_id": "b", "write_version": 7, "affected_dates": [previous, DAY]},
                  "t", "model", {DAY.isoformat(): "2026-11-23T00:00:00Z"})
    assert conn.execute.call_count == 3
    for index, day in enumerate([previous, DAY]):
        sql, params = statement(conn, index)
        assert "greatest(state.source_revision, EXCLUDED.source_revision)" in sql
        assert "least(state.available_from_at, EXCLUDED.available_from_at)" in sql
        assert params["id"] == day_id("t", "model", day) and params["revision"] == 7
        assert params["coverage"] == ("2026-11-23T00:00:00Z" if day == DAY else None)
    sql, params = statement(conn)
    assert "batch_state='confirmed', replay_payload=NULL" in sql
    assert "last_error_code=NULL" in sql and params == {"id": "b"}


@pytest.mark.parametrize("method,required", [("dirty_days", "source_revision > published_source_revision"),
                                            ("published_days", "publish_id IS NOT NULL")])
def test_day_selection_is_tenant_and_kind_scoped(database, method, required):
    store, conn = database
    conn.execute.return_value.all.return_value = [(DAY, 7)]
    assert getattr(store, method)(conn, "t", "model") == [(DAY, 7)]
    sql, params = statement(conn)
    assert required in sql and "ORDER BY statistic_date" in sql
    assert "tenant_id=:tenant AND fact_kind=:kind" in sql
    assert params == {"tenant": "t", "kind": "model"}


@pytest.mark.parametrize("rowcount", [0, 1, 2])
def test_publication_requires_exactly_one_live_revision(database, rowcount):
    store, conn = database
    conn.execute.return_value.rowcount = rowcount
    publish_id, timepoint = uuid4(), datetime.now(timezone.utc)
    if rowcount == 1:
        store.publish(conn, "t", "model", [(DAY, 7)], publish_id, timepoint)
    else:
        with pytest.raises(RuntimeError, match="lost its revision"):
            store.publish(conn, "t", "model", [(DAY, 7)], publish_id, timepoint)
    sql, params = statement(conn)
    assert "source_revision >= :revision" in sql and "published_source_revision < :revision" in sql
    assert "delete_flag='N'" in sql
    assert params == {"id": day_id("t", "model", DAY), "revision": 7, "publish": publish_id, "timepoint": timepoint}


@pytest.mark.parametrize("tenant", [None, "t"])
@pytest.mark.parametrize("lock", [False, True])
def test_state_reads_preserve_scope_and_optional_publication_lock(database, tenant, lock):
    store, conn = database
    rows = [{"tenant_id": "t", "statistic_date": DAY}]
    conn.execute.return_value.mappings.return_value = iter(rows)
    with store.read_states(tenant, "model", DAY, DAY, lock=lock) as result:
        assert result == rows
        store.engine.begin.return_value.__exit__.assert_not_called()
    sql, params = statement(conn)
    assert ("FOR SHARE" in sql) is lock
    assert ("AND tenant_id=:tenant" in sql) is (tenant is not None)
    assert params == {"tenant": tenant, "kind": "model", "start": DAY, "end": DAY}


def test_states_materializes_rows_within_transaction(database):
    store, conn = database
    conn.execute.return_value.mappings.return_value = iter([{"tenant_id": "t"}])
    assert store.states("t", "model", DAY, DAY) == [{"tenant_id": "t"}]
    store.engine.begin.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("tenant,failed", [(None, False), ("t", True)])
def test_failed_batch_probe_includes_legacy_batches_without_date_metadata(database, tenant, failed):
    store, conn = database
    conn.execute.return_value.scalar_one.return_value = failed
    assert store.has_failed_batches(tenant, "model", DAY, DAY) is failed
    sql, params = statement(conn)
    assert "cardinality(affected_dates)=0 OR EXISTS" in sql and "day BETWEEN :start AND :end" in sql
    assert "batch_state IN ('queued', 'pending')" in sql and "last_error_code IS NOT NULL" in sql
    assert ("AND tenant_id=:tenant" in sql) is (tenant is not None)
    assert params["start"] == DAY and params["end"] == DAY


@pytest.mark.parametrize("age,expected", [(0, 0), (2, 2), (1000, 366)])
def test_today_scheduling_preserves_coverage_and_bounds_backfill_to_one_year(database, age, expected):
    store, conn = database
    scope = {"tenant_id": "t", "fact_kind": "model", "coverage": "original",
             "latest": DAY - timedelta(days=age)}
    conn.execute.return_value.mappings.return_value.all.return_value = [scope]
    store.ensure_today(DAY)
    inserted = [statement(conn, i) for i in range(1, conn.execute.call_count)]
    assert len(inserted) == expected
    if expected:
        assert inserted[-1][1]["day"] == DAY
        assert inserted[0][1]["day"] == DAY - timedelta(days=expected - 1)
    for sql, params in inserted:
        assert "ON CONFLICT (day_state_id) DO NOTHING" in sql
        assert params["coverage"] == "original"
        assert params["id"] == day_id("t", "model", params["day"])


def test_coverage_start_is_earliest_known_time_per_selected_tenant(database):
    store, conn = database
    conn.execute.return_value.all.return_value = [("t", "original")]
    assert store.coverage_starts(iter(["t"]), "model") == {"t": "original"}
    sql, params = statement(conn)
    assert "min(available_from_at)" in sql and "HAVING min(available_from_at) IS NOT NULL" in sql
    assert params == {"tenants": ["t"], "kind": "model"}
