# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SUM-DEFAULT-01 read only the actual tenant's default model through SI."""

from contextlib import contextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.storage.errors import Conflict, DeadlineExceeded, ScopeDenied
from nexent.storage.models import OperationContext

from infrastructure.rdb.tenant_config_record import TenantConfig
from test.backend.services.test_summary_metadata import context
from test.backend.services.test_summary_metadata import (
    storage as storage,  # noqa: PLC0414 - Re-export the shared fixture.
)


def seed(s, value, **kwargs):
    data = {
        "tenant_config_id": kwargs.pop("key", 1),
        "tenant_id": "tenant-a",
        "config_key": "LLM_ID",
        "config_value": value,
        "delete_flag": "N",
    }
    data.update(kwargs)
    with s.engine.begin() as conn:
        conn.execute(TenantConfig.__table__.insert(), data)


@pytest.mark.parametrize(
    "value,expected",
    [("7", 7), ("0", 0), ("-2", -2), (" 5 ", 5), ("", None), (None, None)],
)
def test_default_keeps_existing_integer_conversion(storage, value, expected):
    seed(storage, value)
    assert storage.service.default_model(storage.actor, context=context()) == expected
    assert (
        storage.opened[-1].tenant_id == "tenant-a"
        and storage.opened[-1].actor_id == "reader"
    )


def test_absent_deleted_foreign_and_unrelated_defaults_are_not_used(storage):
    s = storage
    seed(s, "8", delete_flag="Y")
    seed(s, "9", key=2, tenant_id="tenant-b")
    seed(s, "10", key=3, config_key="EMBEDDING_ID")
    assert s.service.default_model(s.actor, context=context()) is None


def test_invalid_and_duplicate_values_are_explicit(storage):
    s = storage
    seed(s, "invalid")
    with pytest.raises(ValueError):
        s.service.default_model(s.actor, context=context())
    seed(s, "8", key=2)
    with pytest.raises(Conflict):
        s.service.default_model(s.actor, context=context())


def test_identity_revocation_is_not_a_missing_default(storage):
    s = storage
    seed(s, "7")
    s.identity.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        s.service.default_model(s.actor, context=context())
    assert not s.opened
    s.identity.side_effect = [({"tenant_id": "tenant-a"}, ("DEV",), [5]), ScopeDenied()]
    with pytest.raises(ScopeDenied):
        s.service.default_model(s.actor, context=context())


def test_expired_default_never_opens_ports(storage):
    with pytest.raises(DeadlineExceeded):
        storage.service.default_model(
            storage.actor, context=OperationContext("expired-default", monotonic() - 1)
        )
    assert not storage.opened


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "tenant-b"},
        {"actor_id": "other"},
        {"service_role": "runtime"},
        {"resource_prefix": "other/"},
        {"system": True, "tenant_id": None},
    ],
)
def test_wrong_record_scope_fails_before_query(storage, change, mocker):
    s = storage
    from nexent.storage.models import StorageScope

    query = Mock(side_effect=AssertionError("Mismatched record scope queried"))

    @contextmanager
    def ports(*args, **kwargs):
        yield (
            SimpleNamespace(
                scope=replace(
                    StorageScope("management", "tenant-a", "reader", {"default"}),
                    **change,
                ),
                query=query,
            ),
            None,
        )

    s.service.ports = ports
    with pytest.raises(ScopeDenied):
        s.service.default_model(s.actor, context=context())
    query.assert_not_called()
