# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real record queries and DAC policy over a controlled relational backend."""

import pytest
import sqlalchemy as sa
from contracts.knowledge_cleanse import KnowledgeCleanseLookup
from management.services.file.cleanse_authorization import KnowledgeCleanseAuthorization
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb import cleanse_resources
from test.backend.services.test_cleanse_jobs import context, request
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


@pytest.fixture
def resources(monkeypatch):
    metadata, tables = sa.MetaData(), {}
    for name, original in cleanse_resources.TABLES.items():
        columns = []
        for field in cleanse_resources.FIELDS[name].split():
            column = original.c[field]
            kind = sa.JSON() if field == "user_roles" else column.type
            columns.append(
                sa.Column(
                    field,
                    kind,
                    primary_key=column.primary_key,
                    nullable=column.nullable,
                )
            )
        tables[name] = sa.Table(name, metadata, *columns)
    monkeypatch.setattr(cleanse_resources, "TABLES", tables)
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    source = knowledge_request().source
    fixtures = {
        "cleanse_files": [
            {
                "file_id": "b" * 32,
                "tenant_id": "tenant-a",
                "knowledge_id": 1,
                "status": "UPLOADED",
                "original_filename": "source.txt",
                "source_generation": 0,
                "source_space": source.space,
                "source_key": source.key,
                "source_revision": source.version,
                "source_sha256": source.sha256,
                "delete_flag": "N",
            }
        ],
        "cleanse_knowledge": [
            {
                "knowledge_id": 1,
                "tenant_id": "tenant-a",
                "index_name": "kb-one",
                "created_by": "user-a",
                "group_ids": "[10]",
                "ingroup_permission": "EDIT",
                "knowledge_sources": "upload",
                "delete_flag": "N",
            }
        ],
        "cleanse_memberships": [
            {
                "user_tenant_id": 1,
                "user_id": "user-a",
                "tenant_id": "tenant-a",
                "delete_flag": "N",
            }
        ],
        "cleanse_accounts": [
            {
                "account_id": 1,
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "user_roles": ["DEV"],
                "delete_flag": "N",
            }
        ],
        "cleanse_group_memberships": [
            {
                "group_user_id": 1,
                "tenant_id": "tenant-a",
                "user_id": "user-a",
                "group_id": 10,
                "delete_flag": "N",
            }
        ],
        "cleanse_groups": [
            {"group_id": 10, "tenant_id": "tenant-a", "delete_flag": "N"}
        ],
    }
    with engine.begin() as conn:
        for name, rows in fixtures.items():
            conn.execute(tables[name].insert(), rows)

    def authorize(tenant="tenant-a"):
        records = cleanse_resources.bind_cleanse_resources(
            StorageScope("management", tenant, "worker", set(tables)), engine
        )
        return KnowledgeCleanseAuthorization(records, user_id="user-a")

    def update(dataset, **values):
        with engine.begin() as conn:
            conn.execute(tables[dataset].update().values(**values))

    yield authorize, update, engine, tables
    engine.dispose()


def test_authorizes_pinned_source_with_current_identity(resources):
    authorize, _, _, _ = resources
    assert (
        authorize().authorize(knowledge_request(), context=context())
        == knowledge_request().source
    )


@pytest.mark.parametrize(
    "dataset,values",
    [
        ("cleanse_memberships", {"delete_flag": "Y"}),
        ("cleanse_accounts", {"user_roles": []}),
        ("cleanse_knowledge", {"delete_flag": "Y"}),
        ("cleanse_files", {"status": "DELETE_REQUESTED"}),
        ("cleanse_files", {"source_generation": 1}),
        ("cleanse_files", {"knowledge_id": 2}),
        ("cleanse_files", {"source_revision": "different"}),
        ("cleanse_files", {"source_sha256": None}),
        ("cleanse_files", {"original_filename": "different.pdf"}),
    ],
)
def test_revoked_or_stale_resource_refused(resources, dataset, values):
    authorize, update, _, _ = resources
    update(dataset, **values)
    with pytest.raises(ScopeDenied):
        authorize().authorize(knowledge_request(), context=context())


def test_cross_tenant_and_run_requests_are_refused(resources):
    authorize, _, _, _ = resources
    with pytest.raises(ScopeDenied):
        authorize("tenant-b").authorize(knowledge_request(), context=context())
    with pytest.raises(ScopeDenied):
        authorize().authorize(request(), context=context())


def test_group_revocation_is_rechecked_live(resources):
    authorize, update, _, _ = resources
    update("cleanse_knowledge", created_by="other")
    check = authorize()
    check.authorize(knowledge_request(), context=context())
    update("cleanse_groups", tenant_id="other-tenant")
    with pytest.raises(ScopeDenied):
        check.authorize(knowledge_request(), context=context())


def test_read_only_can_inspect_but_cannot_submit(resources):
    authorize, update, _, _ = resources
    update("cleanse_knowledge", created_by="other", ingroup_permission="READ_ONLY")
    check = authorize()
    with pytest.raises(ScopeDenied):
        check.authorize(knowledge_request(), context=context())
    lookup = KnowledgeCleanseLookup(
        knowledge_id=1, file_id="b" * 32, file_version=0, job_id="c" * 32
    )
    assert check.authorize(lookup, context=context()) == knowledge_request().source


def test_duplicate_account_fails_closed(resources):
    authorize, _, engine, tables = resources
    with engine.begin() as conn:
        conn.execute(
            tables["cleanse_accounts"]
            .insert()
            .values(
                account_id=2,
                tenant_id="tenant-a",
                user_id="user-a",
                user_roles=["ADMIN"],
                delete_flag="N",
            )
        )
    with pytest.raises(ScopeDenied):
        authorize().authorize(knowledge_request(), context=context())


@pytest.mark.parametrize(
    "field,value", [("user_id", "other-user"), ("tenant_id", "other-tenant")]
)
def test_execution_preserves_original_request_identity(resources, field, value):
    authorize, _, _, _ = resources
    typed = knowledge_request()
    row = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "scope_kind": "knowledge",
        "knowledge_id": typed.knowledge_id,
        "file_id": typed.file_id,
        "file_version": typed.file_version,
        "request_payload": typed.model_dump(mode="json"),
        field: value,
    }
    with pytest.raises(ScopeDenied):
        authorize().authorize_execution(row, typed, context=context())
