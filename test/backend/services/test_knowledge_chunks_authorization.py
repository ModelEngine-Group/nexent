# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Chunk browsing authorizes resources without borrowing owners or requiring models."""

import pytest
from contracts.agentos_knowledge import KnowledgeChunksAuthorization
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.services.knowledge_base.chunks_authorization import (
    authorize_chunks_resource,
)
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_file_reader import (
    reader as reader,  # noqa: PLC0414
)


def test_browse_grant_uses_actual_reader_and_shared_resource_namespace(reader):
    s = reader
    grant = authorize_chunks_resource(KnowledgeChunksAuthorization(knowledge_id=2), s.actor,
                                     context=context(), reader=s.service)
    assert grant.resource_tenant_id == ASSET_OWNER_TENANT_ID
    assert grant.knowledge_id == 2 and grant.collection == 'shared'
    assert 'embedding_model' not in grant.model_dump_json()
    assert s.actor.tenant_id == 'tenant-a' and s.actor.user_id != 'asset-user'


def test_browse_refuses_unauthorized_private_knowledge(reader):
    s = reader
    s.update('cleanse_knowledge', created_by='other', ingroup_permission='PRIVATE')
    with pytest.raises(ScopeDenied):
        authorize_chunks_resource(KnowledgeChunksAuthorization(knowledge_id=1), s.actor,
                                  context=context(), reader=s.service)


@pytest.mark.parametrize('updates', [{'deletion_request': {'scope': 'full'}}, {'knowledge_sources': 'datamate'}])
def test_browse_grant_rejects_deleted_or_external_content(reader, updates):
    reader.update('cleanse_knowledge', **updates)
    with pytest.raises(ScopeDenied):
        authorize_chunks_resource(KnowledgeChunksAuthorization(knowledge_id=1), reader.actor,
                                  context=context(), reader=reader.service)
