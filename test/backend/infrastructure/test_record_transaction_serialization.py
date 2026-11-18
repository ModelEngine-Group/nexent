# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted transaction serialization must precede consumer work and release on failure."""

from time import monotonic
from unittest.mock import MagicMock

import pytest
from nexent.storage.errors import CapabilityUnsupported, DeadlineExceeded, InvalidInput
from nexent.storage.models import OperationContext, StorageScope
from sqlalchemy.exc import OperationalError

from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import DatasetCatalog


def store(locks, dialect="postgresql"):
    engine = MagicMock()
    engine.dialect.name = dialect
    engine.get_execution_options.return_value = {}
    connection = engine.connect.return_value
    connection.dialect.name = dialect
    connection.connection.driver_connection.autocommit = False
    return SQLRecordStore(
        StorageScope("management", "tenant", "actor", {"records"}),
        DatasetCatalog(()),
        {},
        engine,
        revision_fields={},
        transaction_locks=locks,
    ), connection


def test_trusted_lock_order_precedes_work_and_commit():
    records, connection = store(("tenant-lock", "user-lock", "name-lock"))
    context = OperationContext("locks", monotonic() + 10)
    with records.transaction(context=context):
        statements = [call.args[0] for call in connection.execute.call_args_list]
        locks = [
            statement.compile().params["lock_key"]
            for statement in statements
            if "pg_advisory_xact_lock" in str(statement)
        ]
        assert locks == ["tenant-lock", "user-lock", "name-lock"]
        connection.begin.return_value.commit.assert_not_called()
    connection.begin.return_value.commit.assert_called_once()
    connection.close.assert_called_once()


def test_failed_lock_rolls_back_without_entering_body_or_replaying():
    records, connection = store(("tenant-lock",))
    connection.execute.side_effect = DeadlineExceeded()
    with (
        pytest.raises(DeadlineExceeded),
        records.transaction(context=OperationContext("expired-lock", monotonic() + 10)),
    ):
        pytest.fail("Transaction body entered after failed lock")
    connection.begin.return_value.rollback.assert_called_once()
    connection.begin.return_value.commit.assert_not_called()
    connection.close.assert_called_once()
    assert connection.execute.call_count == 1


def test_serialization_is_not_silently_ignored_on_sqlite():
    with pytest.raises(CapabilityUnsupported):
        store(("tenant-lock",), dialect="sqlite")


def test_postgres_statement_timeout_is_a_deadline_and_rolls_back():
    records, connection = store(("tenant-lock",))
    original = RuntimeError("private provider diagnostic")
    original.pgcode = "57014"
    connection.execute.side_effect = [
        None,
        OperationalError("private SQL", {}, original),
    ]
    with (
        pytest.raises(DeadlineExceeded),
        records.transaction(context=OperationContext("lock-timeout", monotonic() + 10)),
    ):
        pytest.fail("Timed-out lock entered the transaction body")
    connection.begin.return_value.rollback.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize("locks", [["key"], ("same", "same"), ("",), ("x" * 513,)])
def test_rejects_invalid_trusted_lock_configuration(locks):
    with pytest.raises(InvalidInput):
        store(locks)
