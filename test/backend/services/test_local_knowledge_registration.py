# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual scoped records and DAC fence local alias publication around exclusive filesystem writes."""

import hashlib
import io
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from management.services.file import local_knowledge_source as module
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied
from nexent.storage.models import StorageScope, WriteOutcome, WriteReceipt

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records,  # noqa: F401
)
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def registration(records, resources, monkeypatch, tmp_path):  # noqa: F811
    port, engine, table = records
    _, update, resource_engine, tables = resources
    data = b"local source"
    digest = hashlib.sha256(data).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            table.update().values(
                file_size=len(data), created_by="user-a", source_sha256=digest
            )
        )
    record = port.get("knowledge_ingestion_files", "b" * 32, context=context())
    update(
        "cleanse_files",
        source_space=record["source_space"],
        source_key=record["source_key"],
        source_revision=record["source_revision"],
        source_sha256=digest,
    )
    authorized = bind_cleanse_resources(
        StorageScope("management", "tenant-a", "user-a", set(tables)), resource_engine
    )

    @contextmanager
    def ports(tenant_id, user_id, *, context):
        assert (tenant_id, user_id) == ("tenant-a", "user-a")
        yield port, authorized

    monkeypatch.setattr(module, "knowledge_ingestion_ports", ports)
    actor = SimpleNamespace(user_id="user-a", tenant_id="tenant-a")
    try:
        yield SimpleNamespace(**locals())
    finally:
        authorized.close()


def test_alias_registration_keeps_physical_source_unchanged_and_updates_audit(
    registration,
):
    s = registration
    row = module.publish_local_source(
        s.record, io.BytesIO(s.data), s.actor, s.tmp_path, context()
    )
    from pathlib import Path

    assert Path(row["local_source_path"]).read_bytes() == s.data
    assert (
        row["source_key"] == s.record["source_key"]
        and row["source_revision"] == s.record["source_revision"]
    )
    assert (
        row["version"] == s.record["version"] + 1
        and row["updated_by"] == s.actor.user_id
    )
    assert row["status"] == "UPLOADED" and row["ingestion_request"] is None


def test_revocation_prevents_local_filesystem_effect(registration):
    s = registration
    s.update("cleanse_memberships", delete_flag="Y")
    with pytest.raises(ScopeDenied):
        module.publish_local_source(
            s.record, io.BytesIO(s.data), s.actor, s.tmp_path, context()
        )
    assert not (s.tmp_path / "knowledge").exists()


@pytest.mark.parametrize("outcome", [WriteOutcome.CONFIRMED, WriteOutcome.UNKNOWN])
def test_alias_cas_failure_cleans_only_confirmed_loss_and_never_replays(
    registration, monkeypatch, outcome
):
    s = registration
    calls = []

    def patch(*args, context, **kwargs):
        calls.append(args)
        return WriteReceipt(context.operation_id, False, outcome=outcome)

    monkeypatch.setattr(s.port, "patch", patch)
    with pytest.raises(OutcomeUnknown if outcome is WriteOutcome.UNKNOWN else Conflict):
        module.publish_local_source(
            s.record, io.BytesIO(s.data), s.actor, s.tmp_path, context()
        )
    assert len(calls) == 1
    files = list((s.tmp_path / "knowledge").rglob("source.txt"))
    assert len(files) == (1 if outcome is WriteOutcome.UNKNOWN else 0)
