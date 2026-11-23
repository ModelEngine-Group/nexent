# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bulk batch-failure reads keep scope, dates and database errors intact."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from ops.monitoring.store import BATCH, ControlStore


START, END = date(2026, 11, 18), date(2026, 11, 19)


@pytest.fixture
def database():
    engine = MagicMock()
    return ControlStore(engine), engine.connect.return_value.__enter__.return_value


def test_empty_failure_scope_does_not_open_a_connection(database):
    store, _ = database
    assert store.failed_batch_tenants(iter(()), "model", START, END) == set()
    store.engine.connect.assert_not_called()


def test_bulk_failure_read_binds_all_tenants_in_one_query(database):
    store, conn = database
    conn.execute.return_value.scalars.return_value = iter(["b", "b"])
    assert store.failed_batch_tenants(iter(["a", "b"]), "model", START, END) == {"b"}
    store.engine.connect.assert_called_once()
    conn.execute.assert_called_once()
    statement, params = conn.execute.call_args.args
    sql = " ".join(str(statement).split())
    assert f"SELECT DISTINCT tenant_id FROM {BATCH}" in sql
    assert "tenant_id=ANY(:tenants)" in sql
    assert "fact_kind=:kind" in sql and "delete_flag='N'" in sql
    assert "last_error_code IS NOT NULL" in sql and "batch_state IN ('queued', 'pending')" in sql
    assert "cardinality(affected_dates)=0 OR EXISTS" in sql and "day BETWEEN :start AND :end" in sql
    assert params == {"tenants": ["a", "b"], "kind": "model", "start": START, "end": END}


@pytest.mark.parametrize("failure", ["connect", "query"])
def test_bulk_failure_read_propagates_database_errors(database, failure):
    store, conn = database
    if failure == "connect":
        store.engine.connect.side_effect = RuntimeError("unavailable")
    else:
        conn.execute.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        store.failed_batch_tenants({"a"}, "model", START, END)
