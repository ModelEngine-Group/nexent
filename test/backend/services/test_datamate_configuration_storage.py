# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded, tenant-scoped DataMate URL reads through the real neutral record adapter."""

from contextlib import contextmanager
from time import monotonic

import pytest
import sqlalchemy as sa
from contracts.constants.constants import DATAMATE_URL
from management.services.knowledge_base.providers.configuration import (
    datamate_configuration_url,
)
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import (
    OperationContext,
    PageRequest,
    RecordQuery,
    StorageScope,
)

from infrastructure.datamate_configuration import DATASET, bind_datamate_configuration
from infrastructure.rdb.tenant_config_record import TenantConfig


@pytest.fixture
def records():
    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    table = TenantConfig.__table__
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                {
                    "tenant_config_id": 1,
                    "tenant_id": "a",
                    "config_key": DATAMATE_URL,
                    "config_value": "http://old",
                    "delete_flag": "N",
                },
                {
                    "tenant_config_id": 2,
                    "tenant_id": "a",
                    "config_key": DATAMATE_URL,
                    "config_value": "http://current",
                    "delete_flag": "N",
                },
                {
                    "tenant_config_id": 3,
                    "tenant_id": "b",
                    "config_key": DATAMATE_URL,
                    "config_value": "http://other",
                    "delete_flag": "N",
                },
                {
                    "tenant_config_id": 4,
                    "tenant_id": "a",
                    "config_key": "API_KEY",
                    "config_value": "private",
                    "delete_flag": "N",
                },
                {
                    "tenant_config_id": 5,
                    "tenant_id": "a",
                    "config_key": DATAMATE_URL,
                    "config_value": "http://deleted",
                    "delete_flag": "Y",
                },
            ],
        )
    store = bind_datamate_configuration(
        StorageScope("management", "a", "configuration-reader", {DATASET}), engine
    )
    try:
        yield store
    finally:
        store.close()
        engine.dispose()


def operation():
    return OperationContext("datamate-url-test", monotonic() + 10)


def test_projection_excludes_other_tenant_secrets_and_deleted_rows(records):
    page = records.query(
        DATASET, RecordQuery(), PageRequest(limit=10), context=operation()
    )
    assert [row["config_value"] for row in page.items] == [
        "http://old",
        "http://current",
    ]
    assert set(page.items[0]) == {"tenant_config_id", "tenant_id", "config_value"}
    with pytest.raises(ScopeDenied):
        records.create(
            DATASET,
            {"tenant_config_id": 1, "tenant_id": "a", "config_value": "changed"},
            context=operation(),
        )


def test_reader_preserves_last_value_and_closes(records):
    closed = []

    @contextmanager
    def ports(tenant_id, *, context):
        assert tenant_id == "a"
        context.remaining()
        try:
            yield records
        finally:
            closed.append(True)

    assert datamate_configuration_url("a", ports=ports) == "http://current"
    assert closed == [True]


def test_absent_tenant_does_not_open_storage():
    def forbidden(*args, **kwargs):
        raise AssertionError("Missing tenant opened storage")

    assert datamate_configuration_url(None, ports=forbidden) == ""
    assert datamate_configuration_url("", ports=forbidden) == ""


def test_expired_deadline_prevents_storage():
    def forbidden(*args, **kwargs):
        raise AssertionError("Expired operation opened storage")

    with pytest.raises(DeadlineExceeded):
        datamate_configuration_url(
            "a", ports=forbidden, context=OperationContext("expired", monotonic() - 1)
        )


def test_read_failure_closes_and_does_not_retry():
    events = []

    class Broken:
        def query(self, *args, **kwargs):
            events.append("read")
            raise DeadlineExceeded()

    @contextmanager
    def ports(*args, **kwargs):
        try:
            yield Broken()
        finally:
            events.append("close")

    with pytest.raises(DeadlineExceeded):
        datamate_configuration_url("a", ports=ports)
    assert events == ["read", "close"]


@pytest.mark.parametrize(
    "scope",
    [
        StorageScope("runtime", "a", "reader", {DATASET}),
        StorageScope("management", None, "reader", {DATASET}, system=True),
        StorageScope("management", "a", "reader", {"other"}),
    ],
)
def test_binding_rejects_other_roles_system_and_namespaces(scope):
    with pytest.raises(ScopeDenied):
        bind_datamate_configuration(scope, None)


def test_empty_projection_preserves_default(records):
    ctx = operation()

    @contextmanager
    def ports(*args, **kwargs):
        from dataclasses import replace

        yield type(
            "Empty",
            (),
            {
                "query": lambda *a, **kw: replace(
                    records.query(DATASET, RecordQuery(), PageRequest(), context=ctx),
                    items=(),
                    next_cursor=None,
                )
            },
        )()

    assert datamate_configuration_url("a", ports=ports) == ""


def test_repeated_cursor_fails_without_replaying_read():
    from types import SimpleNamespace

    calls = []

    class Repeating:
        def query(self, *args, **kwargs):
            calls.append(kwargs.get("context"))
            return SimpleNamespace(items=(), next_cursor="same")

    @contextmanager
    def ports(*args, **kwargs):
        yield Repeating()

    with pytest.raises(Conflict):
        datamate_configuration_url("a", ports=ports)
    assert len(calls) == 2
