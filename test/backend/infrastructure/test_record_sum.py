# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral numeric aggregation preserves catalog scope and transaction semantics."""

import pytest
from nexent.storage.errors import InvalidInput, ScopeDenied
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
