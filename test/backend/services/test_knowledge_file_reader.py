# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current-reader DAC selects own/shared lifecycle metadata without Runtime impersonation."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import NotFound, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import knowledge_file_read as module
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def reader(resources, monkeypatch):  # noqa: F811
    _, update, actor_engine, tables = resources
    monkeypatch.setattr(module, "knowledge", tables["cleanse_knowledge"])
    definition, original = module.file_read_catalog()
    table = sa.Table(
        "file_read",
        sa.MetaData(),
        *(
            sa.Column(
                f.name,
                original.c[f.name].type,
                primary_key=original.c[f.name].primary_key,
                nullable=original.c[f.name].nullable,
            )
            for f in definition.fields
        ),
    )
    monkeypatch.setattr(module, "files", table)
    engine = sa.create_engine("sqlite://")
    table.create(engine)
    with engine.begin() as c:
        c.execute(
            table.insert(),
            {
                "file_id": "b" * 32,
                "tenant_id": "tenant-a",
                "knowledge_id": 1,
                "index_name": "kb-one",
                "original_filename": "a.txt",
                "status": "FAILED",
                "stage": "FAILED",
                "error_code": "PARSE_FAILED",
                "error_message": "error",
                "error_stage": "PROCESS",
                "object_name": "knowledge/a.txt",
                "delete_flag": "N",
            },
        )
        c.execute(
            table.insert(),
            {
                "file_id": "c" * 32,
                "tenant_id": ASSET_OWNER_TENANT_ID,
                "knowledge_id": 2,
                "index_name": "shared",
                "original_filename": "shared.txt",
                "status": "COMPLETED",
                "stage": "COMPLETE",
                "object_name": "knowledge/shared.txt",
                "delete_flag": "N",
            },
        )
    with actor_engine.begin() as c:
        c.execute(
            tables["cleanse_knowledge"].insert(),
            {
                "knowledge_id": 2,
                "index_name": "shared",
                "tenant_id": ASSET_OWNER_TENANT_ID,
                "created_by": "asset-user",
                "group_ids": "[]",
                "ingroup_permission": "EDIT",
                "knowledge_sources": "elasticsearch",
                "delete_flag": "N",
            },
        )
    opened = []

    @contextmanager
    def ports(actor, *, context):
        knowledge = module.bind_readable_knowledge(actor, actor_engine)
        identity = bind_cleanse_resources(
            StorageScope(
                "management",
                actor.tenant_id,
                actor.user_id,
                {
                    "cleanse_memberships",
                    "cleanse_accounts",
                    "cleanse_groups",
                    "cleanse_group_memberships",
                },
            ),
            actor_engine,
        )
        files = []

        def file_scope(tenant):
            opened.append((tenant, actor.user_id))
            port = module.bind_file_reads(tenant, actor.user_id, engine)
            files.append(port)
            return port

        try:
            yield knowledge, identity, file_scope
        finally:
            for port in files + [identity, knowledge]:
                port.close()

    actor = ServicePrincipal("user-a", "tenant-a")
    try:
        yield SimpleNamespace(
            service=KnowledgeFileReader(ports=ports),
            actor=actor,
            update=update,
            engine=engine,
            table=table,
            opened=opened,
            ports=ports,
            actor_engine=actor_engine,
            tables=tables,
        )
    finally:
        engine.dispose()


def test_current_reader_gets_exact_error_fields_without_task_owner_lookup(reader):
    r = reader
    result = r.service.error_info(
        "kb-one", "knowledge/a.txt", r.actor, context=context()
    )
    assert result == {
        "status": "success",
        "error_code": "PARSE_FAILED",
        "error_message": "error",
        "error_stage": "PROCESS",
        "failed_at": None,
    }
    assert r.opened == [("tenant-a", "user-a")]


def test_shared_asset_keeps_original_read_only_dac_and_actual_reader_identity(reader):
    result = reader.service.error_info(
        "shared", "knowledge/shared.txt", reader.actor, context=context()
    )
    assert result["error_code"] is None and result["error_stage"] == "COMPLETE"
    assert reader.opened == [(ASSET_OWNER_TENANT_ID, "user-a")]


def test_revoked_membership_does_not_open_file_records(reader):
    reader.update("cleanse_memberships", delete_flag="Y")
    with pytest.raises(ScopeDenied):
        reader.service.error_info(
            "kb-one", "knowledge/a.txt", reader.actor, context=context()
        )
    assert reader.opened == []


def test_authorized_group_reader_keeps_own_identity_for_other_uploads(reader):
    with reader.actor_engine.begin() as c:
        for name, values in (
            (
                "cleanse_memberships",
                {
                    "user_tenant_id": 2,
                    "user_id": "user-b",
                    "tenant_id": "tenant-a",
                    "delete_flag": "N",
                },
            ),
            (
                "cleanse_accounts",
                {
                    "account_id": 2,
                    "user_id": "user-b",
                    "tenant_id": "tenant-a",
                    "user_roles": ["DEV"],
                    "delete_flag": "N",
                },
            ),
            (
                "cleanse_group_memberships",
                {
                    "group_user_id": 2,
                    "user_id": "user-b",
                    "tenant_id": "tenant-a",
                    "group_id": 10,
                    "delete_flag": "N",
                },
            ),
        ):
            c.execute(reader.tables[name].insert(), values)
    result = reader.service.error_info(
        "kb-one",
        "knowledge/a.txt",
        ServicePrincipal("user-b", "tenant-a"),
        context=context(),
    )
    assert result["error_code"] == "PARSE_FAILED" and reader.opened == [
        ("tenant-a", "user-b")
    ]


def test_metadata_handle_is_read_only(reader):
    from nexent.storage.models import FieldPatch

    with reader.ports(reader.actor, context=context()) as (_, _, files):
        port = files("tenant-a")
        with pytest.raises(ScopeDenied):
            port.patch(
                module.FILES,
                "b" * 32,
                FieldPatch(set_values={"error_code": "CHANGED"}),
                context=context(),
            )


def test_latest_path_record_and_naive_timestamp_match_existing_contract(reader):
    from datetime import datetime, timezone

    with reader.engine.begin() as c:
        c.execute(
            reader.table.insert(),
            {
                "file_id": "d" * 32,
                "tenant_id": "tenant-a",
                "knowledge_id": 1,
                "index_name": "kb-one",
                "original_filename": "a.txt",
                "status": "FAILED",
                "stage": "FAILED",
                "object_name": "knowledge/a.txt",
                "error_code": "NEWER",
                "failed_at": datetime(2026, 11, 17, 1, 2, 3, tzinfo=timezone.utc),
                "update_time": datetime(2026, 11, 17, 1, 2, 3, tzinfo=timezone.utc),
                "delete_flag": "N",
            },
        )
        c.execute(
            reader.table.update()
            .where(reader.table.c.file_id == "b" * 32)
            .values(update_time=datetime(2026, 11, 16, tzinfo=timezone.utc))
        )
    result = reader.service.error_info(
        "kb-one", "knowledge/a.txt", reader.actor, context=context()
    )
    assert (
        result["error_code"] == "NEWER"
        and result["failed_at"] == "2026-11-17T01:02:03Z"
    )


def test_file_id_cannot_select_another_kb_or_fall_back_to_a_matching_path(reader):
    with pytest.raises(NotFound):
        reader.service.error_info(
            "kb-one",
            "knowledge/a.txt",
            reader.actor,
            file_id="c" * 32,
            context=context(),
        )


def test_other_tenant_cannot_read_private_kb(reader):
    with pytest.raises((ScopeDenied, ValueError)):
        reader.service.error_info(
            "kb-one",
            "knowledge/a.txt",
            ServicePrincipal("user-a", "other"),
            context=context(),
        )
    assert reader.opened == []


def test_missing_knowledge_base_keeps_original_missing_resource_message(reader):
    with pytest.raises(ValueError, match="Knowledge base 'missing' not found"):
        reader.service.error_info("missing", "a.txt", reader.actor, context=context())
    assert reader.opened == []
