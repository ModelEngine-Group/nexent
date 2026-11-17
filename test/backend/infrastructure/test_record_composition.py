# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Record engines remain bounded and every owned resource is released on failure."""

from importlib import import_module
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.constants import environment
from nexent.storage.errors import Conflict, OutcomeUnknown, Unavailable
from nexent.storage.models import OperationContext
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from infrastructure import source_upload, storage_ledger
from infrastructure.rdb import composition
from test.backend.infrastructure import test_record_store as record_fixtures

stores = record_fixtures.stores


@pytest.mark.parametrize(
    "snapshot,level", [(False, "READ COMMITTED"), (True, "REPEATABLE READ")]
)
def test_engine_has_finite_pool_connection_and_explicit_isolation(
    monkeypatch, mocker, snapshot, level
):
    monkeypatch.setattr(environment, "POSTGRES_PORT", "5432")
    create = mocker.patch.object(composition, "create_engine")
    composition.record_engine(
        OperationContext("engine", monotonic() + 2), snapshot=snapshot
    )
    args = create.call_args.kwargs
    assert 1 <= args["connect_args"]["connect_timeout"] <= 2
    assert 0 < args["pool_timeout"] <= 2
    assert args["pool_size"] == 1 and args["max_overflow"] == 0
    assert args["hide_parameters"] and args["isolation_level"] == level


def test_ledger_factory_closes_store_and_engine_even_after_cleanup_failure(mocker):
    engine = mocker.patch.object(storage_ledger, "record_engine").return_value
    store = mocker.patch.object(storage_ledger, "bind_ledger_records").return_value
    store.close.side_effect = RuntimeError("controlled cleanup error")
    with (
        pytest.raises(OutcomeUnknown),
        storage_ledger.ledger_record_ports(
            "tenant-a", "actor", context=OperationContext("cleanup", monotonic() + 2)
        ),
    ):
        pass
    store.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_discovery_factory_closes_all_handles_after_query_error(mocker):
    engine = mocker.patch.object(source_upload, "record_engine").return_value
    store = mocker.patch.object(source_upload, "bind_source_candidates").return_value
    with (
        pytest.raises(ValueError),
        source_upload.source_candidate_ports(
            "owner", context=OperationContext("query", monotonic() + 2)
        ),
    ):
        raise ValueError("controlled query error")
    store.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_all_cleanup_callbacks_run_without_exposing_error_message():
    first, second = Mock(side_effect=ValueError("private detail")), Mock()
    with pytest.raises(OutcomeUnknown):
        composition.close_owned(
            OperationContext("close", monotonic() + 2), [first, second]
        )
    first.assert_called_once()
    second.assert_called_once()


@pytest.mark.parametrize(
    "code,error_type",
    [("40001", Conflict), ("40P01", Conflict), ("08006", Unavailable)],
)
def test_only_known_transaction_aborts_are_retryable_conflicts(
    stores, code, error_type
):
    cause = RuntimeError("controlled provider failure")
    cause.pgcode = code
    connection = Mock()
    connection.dialect.name = "postgresql"
    connection.execute.side_effect = DBAPIError(
        "controlled statement", {}, cause, hide_parameters=True
    )
    with pytest.raises(error_type):
        stores[0]._execute(
            connection, None, OperationContext("provider-error", monotonic() + 2)
        )


def test_nested_live_dac_has_exactly_two_owned_connections(monkeypatch, mocker):
    monkeypatch.setattr(environment, 'POSTGRES_PORT', '5432')
    create = mocker.patch.object(composition, 'create_engine')
    composition.record_engine(OperationContext('nested-dac', monotonic() + 2), connections=2)
    assert create.call_args.kwargs['pool_size'] == 2
    assert create.call_args.kwargs['max_overflow'] == 0


@pytest.mark.parametrize('name,binding,factory', [
    ('infrastructure.knowledge_admission', 'bind_admission_records', 'knowledge_admission_ports'),
    ('infrastructure.knowledge_base_metadata', 'bind_base_metadata_records', 'knowledge_base_metadata_ports'),
])
def test_kb_compositions_reserve_transaction_and_live_dac_connections(mocker, name, binding, factory):
    module = import_module(name)
    engine = mocker.patch.object(module, 'record_engine')
    records = mocker.patch.object(module, binding).return_value
    resources = mocker.patch.object(module, 'bind_cleanse_resources').return_value
    operation = OperationContext('nested-dac', monotonic() + 2)
    with getattr(module, factory)(SimpleNamespace(user_id='actor', tenant_id='tenant'), context=operation):
        pass
    engine.assert_called_once_with(operation, connections=2)
    records.close.assert_called_once()
    resources.close.assert_called_once()
    engine.return_value.dispose.assert_called_once()


def test_pool_checkout_timeout_is_neutral_and_never_retried(stores, monkeypatch):
    connect = Mock(side_effect=PoolTimeoutError('private pool details'))
    monkeypatch.setattr(stores[0]._engine, 'connect', connect)
    with pytest.raises(Unavailable) as error:
        stores[0].get('jobs', 'one', context=OperationContext('pool-timeout', monotonic() + 2))
    assert 'private' not in str(error.value)
    connect.assert_called_once()
