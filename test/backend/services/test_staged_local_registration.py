# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current DAC and pinned source identity fence alias transfer and staging completion."""

from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from management.services.file import staged_local_binding as module
from management.services.file.local_source_staging import LocalSourceStaging
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.local_source_staging import (
    DATASET,
    bind_local_source_staging,
    staging_catalog,
)
from test.backend.infrastructure.test_knowledge_ingestion_records import (
    records,  # noqa: F401
)
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_local_knowledge_registration import (
    registration,  # noqa: F401
)


@pytest.fixture
def transfer(registration, monkeypatch):  # noqa: F811
    s = registration
    from infrastructure.rdb import local_source_staging as staging_module

    _, source, _ = staging_catalog()
    table = source.to_metadata(sa.MetaData(), schema=None)
    monkeypatch.setattr(staging_module, "table", table)
    engine = sa.create_engine("sqlite://")
    table.create(engine)
    port = bind_local_source_staging(
        StorageScope("management", s.actor.tenant_id, s.actor.user_id, {DATASET}),
        engine,
    )

    @contextmanager
    def staging_ports(tenant, user, *, context):
        assert (tenant, user) == (s.actor.tenant_id, s.actor.user_id)
        yield port

    @contextmanager
    def knowledge_ports(tenant, user, *, context):
        yield s.port, s.authorized

    monkeypatch.setattr(module, "local_source_staging_port", staging_ports)
    monkeypatch.setattr(module, "knowledge_ingestion_ports", knowledge_ports)
    journal = LocalSourceStaging(port)
    initial = journal.reserve(
        "a" * 32,
        "/owned/staged.txt",
        "staged.txt",
        len(s.data),
        s.digest,
        context=context(),
    )
    ready = journal.confirm(initial, context=context())
    binding = journal.bind(
        ready,
        s.record["knowledge_id"],
        s.record["file_id"],
        KnowledgeFileAuthorization(s.authorized, user_id=s.actor.user_id),
        context=context(),
    )
    try:
        yield s, journal, binding
    finally:
        port.close()
        engine.dispose()


def test_alias_transfer_confirms_same_file_and_finishes_staging(transfer):
    s, journal, binding = transfer
    row = module.finish_staged_binding(binding, s.actor, context())
    assert (
        row["file_id"] == s.record["file_id"]
        and row["local_source_path"] == binding["local_source_path"]
    )
    assert (
        row["source_key"] == s.record["source_key"]
        and row["source_sha256"] == s.record["source_sha256"]
    )
    assert (
        journal.find(binding["local_source_path"], context=context())["state"]
        == "BOUND"
    )


@pytest.mark.parametrize("revoked", [False, True])
def test_changed_source_or_current_revocation_does_not_register_alias(
    transfer, revoked
):
    s, journal, binding = transfer
    if revoked:
        s.update("cleanse_memberships", delete_flag="Y")
    else:
        binding["source_sha256"] = "f" * 64
    with pytest.raises(ScopeDenied if revoked else Conflict):
        module.finish_staged_binding(binding, s.actor, context())
    assert (
        journal.find(binding["local_source_path"], context=context())["state"]
        == "BINDING"
    )
    assert (
        s.port.get("knowledge_ingestion_files", s.record["file_id"], context=context())[
            "local_source_path"
        ]
        is None
    )
