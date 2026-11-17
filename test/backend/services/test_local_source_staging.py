# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped staging journal keeps unbound local sources separate from knowledge files."""

from time import monotonic
from unittest.mock import ANY, Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from management.services.file.local_source_staging import LocalSourceStaging
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown, ScopeDenied
from nexent.storage.models import (
    OperationContext,
    StorageScope,
    WriteOutcome,
    WriteReceipt,
)

from infrastructure.rdb.local_source_staging import (
    DATASET,
    bind_local_source_staging,
    staging_catalog,
)


def context():
    return OperationContext(uuid4().hex, monotonic() + 10)


@pytest.fixture
def staging(monkeypatch):
    from infrastructure.rdb import local_source_staging as module

    _, original, _ = staging_catalog()
    table = original.to_metadata(sa.MetaData(), schema=None)
    monkeypatch.setattr(module, "table", table)
    engine = sa.create_engine("sqlite://")
    table.create(engine)
    port = bind_local_source_staging(
        StorageScope("management", "t", "u", {DATASET}), engine
    )
    journal = LocalSourceStaging(port)
    row = journal.reserve(
        "a" * 32, "/owned/a.txt", "a.txt", 4, "b" * 64, context=context()
    )
    try:
        yield journal, row, port, engine, table
    finally:
        port.close()
        engine.dispose()


def test_reserve_confirm_and_exact_alias_keep_source_and_audit(staging):
    journal, row, _, _, _ = staging
    assert row["state"] == "UPLOADING" and row["created_by"] == "u"
    assert row["knowledge_id"] is None and row["bound_file_id"] is None
    ready = journal.confirm(row, context=context())
    assert ready["state"] == "READY" and ready["version"] == row["version"] + 1
    assert journal.find("/owned/a.txt", context=context()) == ready
    with pytest.raises(NotFound):
        journal.find("a.txt", context=context())


@pytest.mark.parametrize("tenant,user", [("other", "u"), ("t", "other")])
def test_foreign_actor_cannot_select_or_mutate(staging, tenant, user):
    _, row, _, engine, _ = staging
    port = bind_local_source_staging(
        StorageScope("management", tenant, user, {DATASET}), engine
    )
    try:
        other = LocalSourceStaging(port)
        with pytest.raises(NotFound):
            other.find(row["local_source_path"], context=context())
        with pytest.raises((NotFound, ScopeDenied)):
            other.confirm(row, context=context())
    finally:
        port.close()


def test_binding_requires_current_edit_authorization_and_fixed_target(staging, mocker):
    journal, row, _, _, _ = staging
    ready = journal.confirm(row, context=context())
    authorization = Mock()
    authorization.resolve_knowledge.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        journal.bind(ready, 9, "c" * 32, authorization, context=context())
    assert (
        journal.find(ready["local_source_path"], context=context())["state"] == "READY"
    )
    authorization.resolve_knowledge.side_effect = None
    bound = journal.bind(ready, 9, "c" * 32, authorization, context=context())
    authorization.resolve_knowledge.assert_called_with(9, edit=True, context=ANY)
    assert (bound["state"], bound["knowledge_id"], bound["bound_file_id"]) == (
        "BINDING",
        9,
        "c" * 32,
    )
    with pytest.raises(Conflict):
        journal.bind(ready, 10, "d" * 32, authorization, context=context())
    done = journal.complete(bound, context=context())
    assert done["state"] == "BOUND" and done["bound_file_id"] == "c" * 32


def test_unknown_cas_is_reported_without_replay(staging, mocker):
    journal, row, port, _, _ = staging
    patch = mocker.patch.object(
        port,
        "patch",
        return_value=WriteReceipt("op", False, None, WriteOutcome.UNKNOWN),
    )
    with pytest.raises(OutcomeUnknown):
        journal.confirm(row, context=context())
    assert patch.call_count == 1
    assert (
        journal.find(row["local_source_path"], context=context())["state"]
        == "UPLOADING"
    )


def test_confirmed_write_followed_by_lost_read_is_unknown_without_second_write(
    staging, mocker
):
    journal, row, port, _, _ = staging
    original_get = port.get
    calls = 0

    def get(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            from nexent.storage.errors import Unavailable

            raise Unavailable()
        return original_get(*args, **kwargs)

    mocker.patch.object(port, "get", side_effect=get)
    patch = mocker.patch.object(port, "patch", wraps=port.patch)
    with pytest.raises(OutcomeUnknown):
        journal.confirm(row, context=context())
    assert patch.call_count == 1
    assert original_get(DATASET, row["stage_id"], context=context())["state"] == "READY"


def test_catalog_runtime_denied_and_all_columns_have_comments(staging):
    _, _, _, engine, _ = staging
    with pytest.raises(ScopeDenied):
        bind_local_source_staging(StorageScope("runtime", "t", "u", {DATASET}), engine)
    _, table, _ = staging_catalog()
    assert all(column.comment for column in table.c)


def test_duplicate_alias_is_rejected_instead_of_guessing(staging):
    journal, row, _, _, _ = staging
    journal.reserve(
        "e" * 32, row["local_source_path"], "a.txt", 4, "b" * 64, context=context()
    )
    with pytest.raises(ScopeDenied):
        journal.find(row["local_source_path"], context=context())


@pytest.mark.parametrize(
    "field,value",
    [(0, "bad"), (1, ""), (2, "x" * 1025), (3, -1), (3, True), (4, "bad")],
)
def test_invalid_source_metadata_rejected_before_insert(staging, field, value):
    journal, _, port, _, _ = staging
    args = ["f" * 32, "/owned/f.txt", "f.txt", 4, "b" * 64]
    args[field] = value
    from nexent.storage.errors import InvalidInput

    with pytest.raises(InvalidInput):
        journal.reserve(*args, context=context())
    assert port.get(DATASET, "f" * 32, context=context()) is None
