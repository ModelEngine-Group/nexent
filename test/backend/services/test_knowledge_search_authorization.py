# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB search grants require live DAC without depending on a file or cleanse job."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import (
    KnowledgeFileReference,
    KnowledgeSearchAuthorization,
)
from management.services.knowledge_base import search_authorization
from management.services.knowledge_base.search_authorization import (
    KnowledgeSearchAuthorizationPolicy,
)
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414 - Shared actual catalog fixture.
)
from test.backend.services.test_cleanse_jobs import context


def test_search_grant_is_kb_scoped_even_when_files_are_deleted(resources):
    authorize, update, _, _ = resources
    update("cleanse_knowledge", embedding_model_id=2)
    update("cleanse_files", delete_flag="Y", status="DELETED")
    records = authorize().records
    try:
        grants = KnowledgeSearchAuthorizationPolicy(records, user_id="user-a").authorize(
            KnowledgeSearchAuthorization(knowledge_ids=[1]), context=context())
        assert len(grants.knowledge_bases) == 1
        grant = grants.knowledge_bases[0]
        assert grant.knowledge_id == 1 and grant.collection == "kb-one" and grant.embedding_model_id == 2
        assert len(grant.revision) == 64
    finally:
        records.close()


@pytest.mark.parametrize("dataset,changes", [
    ("cleanse_memberships", {"tenant_id": "other"}),
    ("cleanse_knowledge", {"embedding_model_id": None}),
    ("cleanse_knowledge", {"created_by": "other", "ingroup_permission": "PRIVATE"}),
    ("cleanse_knowledge", {"delete_flag": "Y"}),
    ("cleanse_knowledge", {"knowledge_sources": "datamate"}),
])
def test_search_grant_refuses_missing_permission_or_model(resources, dataset, changes):
    authorize, update, _, _ = resources
    update("cleanse_knowledge", embedding_model_id=2)
    update(dataset, **changes)
    records = authorize().records
    try:
        with pytest.raises(ScopeDenied):
            KnowledgeSearchAuthorizationPolicy(records, user_id="user-a").authorize(
                KnowledgeSearchAuthorization(knowledge_ids=[1]), context=context())
    finally:
        records.close()


def test_search_read_only_permission_is_sufficient_and_no_unknown_kb_is_dropped(resources):
    authorize, update, _, _ = resources
    update("cleanse_knowledge", embedding_model_id=2, created_by="other", ingroup_permission="READ_ONLY")
    records = authorize().records
    try:
        policy = KnowledgeSearchAuthorizationPolicy(records, user_id="user-a")
        assert policy.authorize(KnowledgeSearchAuthorization(knowledge_ids=[1]), context=context())
        with pytest.raises(ScopeDenied):
            policy.authorize(KnowledgeSearchAuthorization(knowledge_ids=[1, 2]), context=context())
    finally:
        records.close()


def test_multiple_grants_preserve_order_and_query_actor_once(resources):
    authorize, update, engine, tables = resources
    update("cleanse_knowledge", embedding_model_id=2)
    with engine.begin() as connection:
        connection.execute(tables["cleanse_knowledge"].insert().values(
            knowledge_id=2, tenant_id="tenant-a", index_name="kb-two", embedding_model_id=2,
            created_by="user-a", group_ids="[10]", ingroup_permission="EDIT",
            knowledge_sources="elasticsearch", delete_flag="N"))
    records = authorize().records
    original = records.query
    records.query = Mock(wraps=original)
    try:
        result = KnowledgeSearchAuthorizationPolicy(records, user_id="user-a").authorize(
            KnowledgeSearchAuthorization(knowledge_ids=[2, 1]), context=context())
        assert [g.knowledge_id for g in result.knowledge_bases] == [2, 1]
        assert sum(c.args[0] == "cleanse_memberships" for c in records.query.call_args_list) == 1
    finally:
        records.close()


@pytest.mark.parametrize("scenario", ["current", "stale", "retired", "reused"])
def test_selected_historical_files_require_current_scope_and_unique_exact_source(resources, monkeypatch, scenario):
    authorize, update, engine, tables = resources
    update("cleanse_knowledge", embedding_model_id=2)
    update("cleanse_files", status="COMPLETED", source_generation=0, bucket_name="attested", object_name="history/old.txt",
           source_key="history/old.txt", local_source_path=None, delete_flag="Y" if scenario == "retired" else "N")
    with engine.begin() as conn:
        file_id = conn.execute(tables["cleanse_files"].select()).mappings().one()["file_id"]
        if scenario == "reused":
            conn.execute(tables["cleanse_files"].insert().values(file_id="d" * 32, tenant_id="tenant-a",
                knowledge_id=1, bucket_name="attested", object_name="/attested/history/old.txt", original_filename="old.txt",
                status="DELETED", delete_flag="Y", source_generation=0))
    actor = SimpleNamespace(user_id="user-a", tenant_id="tenant-a")
    knowledge = {"knowledge_id": 1, "tenant_id": "tenant-a", "index_name": "kb-one", "embedding_model_id": 2,
                 "knowledge_sources": "elasticsearch", "deletion_request": None}
    reader = SimpleNamespace(knowledges=Mock(return_value=[knowledge]))

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        records = authorize().records
        try:
            yield None, records
        finally:
            records.close()

    monkeypatch.setattr(search_authorization, "knowledge_deletion_ports", ports)
    monkeypatch.setattr(search_authorization, "active_file_aliases",
                        lambda *a, **kw: {file_id: "legacy-id"})
    scope = KnowledgeFileReference(knowledge_id=1, file_id=file_id, file_version=int(scenario == "stale"))
    request = KnowledgeSearchAuthorization(knowledge_ids=[1], selected_files=[scope])
    if scenario in {"stale", "retired"}:
        with pytest.raises(ScopeDenied):
            search_authorization.authorize_knowledge_search(request, actor, context=context(), reader=reader)
    else:
        grant = search_authorization.authorize_knowledge_search(request, actor, context=context(), reader=reader)
        if scenario == "current":
            assert grant.legacy_files[0].file_id == file_id
            assert grant.legacy_files[0].alias == "legacy-id"
            assert set(grant.legacy_files[0].addresses) == {"history/old.txt", "/attested/history/old.txt",
                                                           "s3://attested/history/old.txt"}
        else:
            assert not grant.legacy_files
