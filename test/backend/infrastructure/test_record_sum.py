# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral numeric aggregation preserves catalog scope and transaction semantics."""

import pytest
from nexent.storage.errors import CapabilityUnsupported, InvalidInput, ScopeDenied
from nexent.storage.models import Comparison, RecordQuery

from test.backend.infrastructure import test_record_store as record_fixtures
from test.backend.infrastructure.test_record_store import context

stores = record_fixtures.stores


def test_sum_is_scoped_and_empty_is_zero(stores):
    a, b = stores
    assert a.sum("jobs", "attempt", RecordQuery(), context=context()) == 0
    a.create("jobs", {"id": "one", "status": "queued", "attempt": 6}, context=context())
    b.create(
        "jobs", {"id": "two", "status": "queued", "attempt": 900}, context=context()
    )
    assert a.sum("jobs", "attempt", RecordQuery(), context=context()) == 6
    assert b.sum("jobs", "attempt", RecordQuery(), context=context()) == 900
    assert (
        a.sum(
            "jobs",
            "attempt",
            RecordQuery(where=Comparison("status", "eq", "done")),
            context=context(),
        )
        == 0
    )


@pytest.mark.parametrize("field", ["status", "missing", "SUM(attempt)"])
def test_sum_rejects_non_numeric_or_unknown_fields(stores, field):
    with pytest.raises(InvalidInput):
        stores[0].sum("jobs", field, RecordQuery(), context=context())


def test_sum_shares_transaction_and_rejects_other_dataset(stores):
    a, _ = stores
    with a.transaction(context=context()) as tx:
        tx.create(
            "jobs", {"id": "one", "status": "queued", "attempt": 2}, context=context()
        )
        assert tx.sum("jobs", "attempt", RecordQuery(), context=context()) == 2
    with pytest.raises(ScopeDenied):
        a.sum("other", "attempt", RecordQuery(), context=context())


def test_integer_sum_preserves_values_beyond_float_precision(stores):
    a, _ = stores
    value = 2**53 + 1
    a.create(
        "jobs", {"id": "one", "status": "queued", "attempt": value}, context=context()
    )
    result = a.sum("jobs", "attempt", RecordQuery(), context=context())
    assert type(result) is int and result == value


def test_group_sum_is_scoped_and_preserves_integer_totals(stores):
    a, b = stores
    assert a.sum_by("jobs", "attempt", "status", RecordQuery(), context=context()) == {}
    for store, key, status, value in (
        (a, "one", "queued", 2),
        (a, "two", "queued", 3),
        (a, "three", "done", 7),
        (b, "four", "queued", 900),
    ):
        store.create(
            "jobs", {"id": key, "status": status, "attempt": value}, context=context()
        )
    assert a.sum_by("jobs", "attempt", "status", RecordQuery(), context=context()) == {
        "queued": 5,
        "done": 7,
    }
    assert b.sum_by("jobs", "attempt", "status", RecordQuery(), context=context()) == {
        "queued": 900
    }


@pytest.mark.parametrize(
    "field,group", [("status", "attempt"), ("missing", "id"), ("attempt", "missing")]
)
def test_group_sum_rejects_invalid_fields(stores, field, group):
    with pytest.raises(InvalidInput):
        stores[0].sum_by("jobs", field, group, RecordQuery(), context=context())


def test_group_sum_keeps_the_callers_transaction_and_rollback(stores):
    a, _ = stores
    with pytest.raises(RuntimeError), a.transaction(context=context()) as tx:
        tx.create(
            "jobs", {"id": "new", "status": "queued", "attempt": 2}, context=context()
        )
        assert tx.sum_by(
            "jobs", "attempt", "status", RecordQuery(), context=context()
        ) == {"queued": 2}
        raise RuntimeError("rollback")
    assert a.sum_by("jobs", "attempt", "status", RecordQuery(), context=context()) == {}


def test_group_sum_rejects_null_keys_instead_of_returning_non_neutral_data(stores):
    a, _ = stores
    a.create("jobs", {"id": "new", "status": "queued", "attempt": 2}, context=context())
    with pytest.raises(CapabilityUnsupported):
        a.sum_by("jobs", "attempt", "detail", RecordQuery(), context=context())
