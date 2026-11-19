# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-COL-USAGE-01 authorize quota scalars without borrowing body rights."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from contracts.knowledge_collections import KnowledgeCollectionsAuthorization
from management.services.knowledge_base.collection_metadata_authorization import (
    authorize_collection_metadata,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure import knowledge_collection_metadata as metadata
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def quota_metadata(resources, mocker):  # noqa: F811
    _, update, engine, tables = resources
    mocker.patch.object(
        metadata,
        "KnowledgeRecord",
        SimpleNamespace(__table__=tables["cleanse_knowledge"]),
    )
    actor = ServicePrincipal("user-a", "tenant-a")
    opened, closed = [], []
    with engine.begin() as conn:
        conn.execute(
            tables["cleanse_knowledge"]
            .update()
            .values(
                created_by="other", ingroup_permission="PRIVATE", embedding_model_id=3
            )
        )
        conn.execute(
            tables["cleanse_knowledge"].insert(),
            {
                "knowledge_id": 2,
                "tenant_id": "tenant-b",
                "index_name": "foreign",
                "created_by": "other",
                "ingroup_permission": "PRIVATE",
                "knowledge_sources": "elasticsearch",
                "delete_flag": "N",
                "embedding_model_id": 4,
            },
        )

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        identity = bind_cleanse_resources(
            StorageScope(
                "management",
                actor.tenant_id,
                actor.user_id,
                {"cleanse_accounts", "cleanse_memberships"},
            ),
            engine,
        )
        owned = [identity]

        def records(*, cross_tenant):
            opened.append((principal, cross_tenant))
            port = metadata.bind_collection_metadata(
                principal, engine, cross_tenant=cross_tenant
            )
            owned.append(port)
            return port

        try:
            yield identity, SimpleNamespace(scope=identity.scope), records
        finally:
            for port in owned:
                port.close()
            closed.append(True)

    def invoke(ids):
        return authorize_collection_metadata(
            KnowledgeCollectionsAuthorization(knowledge_ids=ids, view="usage"),
            actor,
            context=context(),
            ports=ports,
        )

    return SimpleNamespace(**locals())


def test_own_private_quota_metadata_has_no_model_binding_or_body_permission(
    quota_metadata,
):
    s = quota_metadata
    grant = s.invoke([1]).knowledge_bases[0]
    assert (
        grant.knowledge_id == 1
        and grant.embedding_model_id is None
        and grant.resource_tenant_id == "tenant-a"
    )
    body = bind_cleanse_resources(
        StorageScope("management", s.actor.tenant_id, s.actor.user_id, set(s.tables)),
        s.engine,
    )
    try:
        with pytest.raises(ScopeDenied):
            KnowledgeFileAuthorization(body, user_id=s.actor.user_id).resolve_knowledge(
                1, edit=False, context=context()
            )
    finally:
        body.close()
    assert s.opened == [(s.actor, False)] and s.closed == [True]


def test_foreign_ordinary_quota_metadata_is_refused(quota_metadata):
    s = quota_metadata
    with pytest.raises(ScopeDenied):
        s.invoke([2])
    assert s.opened == [(s.actor, False)]


@pytest.mark.parametrize("role", ["SU", "ASSET_OWNER"])
def test_foreign_privileged_quota_metadata_preserves_actual_actor(quota_metadata, role):
    s = quota_metadata
    s.update("cleanse_accounts", user_roles=[role])
    grant = s.invoke([2]).knowledge_bases[0]
    assert grant.resource_tenant_id == "tenant-b" and grant.embedding_model_id is None
    assert s.opened == [(s.actor, True)]


@pytest.mark.parametrize("dataset", ["cleanse_accounts", "cleanse_memberships"])
def test_revoked_identity_cannot_open_quota_metadata_namespace(quota_metadata, dataset):
    s = quota_metadata
    s.update(dataset, delete_flag="Y")
    with pytest.raises(ScopeDenied):
        s.invoke([1])
    assert not s.opened and s.closed == [True]


def test_datamate_local_collection_usage_only_has_no_model_binding(quota_metadata):
    s = quota_metadata
    s.update('cleanse_knowledge', knowledge_sources='datamate')
    grant = s.invoke([1]).knowledge_bases[0]
    assert grant.collection == 'kb-one' and grant.embedding_model_id is None
    assert grant.resource_tenant_id == s.actor.tenant_id


def test_unknown_provider_is_not_authorized_as_local_collection(quota_metadata):
    s = quota_metadata
    s.update('cleanse_knowledge', knowledge_sources='unknown')
    with pytest.raises(ScopeDenied):
        s.invoke([1])
