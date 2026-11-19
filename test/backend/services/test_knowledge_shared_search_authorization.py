# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SHARED-SEARCH-01 uses real own/asset SI projections and actual DAC."""

import pytest
from contracts.agentos_knowledge import KnowledgeSearchAuthorization
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.services.knowledge_base.search_authorization import (
    authorize_knowledge_search,
)
from nexent.storage.errors import ScopeDenied

from infrastructure.knowledge_search import knowledge_search_revision
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_file_reader import context
from test.backend.services.test_knowledge_file_reader import (
    reader as reader,  # noqa: PLC0414
)


def test_batch_grant_preserves_resource_tenants_and_requested_order(reader):
    s = reader
    s.update("cleanse_knowledge", embedding_model_id=2)
    grant = authorize_knowledge_search(KnowledgeSearchAuthorization(knowledge_ids=[2, 1]),
                                      s.actor, context=context(), reader=s.service)
    assert [(r.knowledge_id, r.resource_tenant_id) for r in grant.knowledge_bases] == [
        (2, ASSET_OWNER_TENANT_ID), (1, s.actor.tenant_id)]
    assert s.opened == []
    assert s.actor.user_id == "user-a" and s.actor.tenant_id == "tenant-a"


@pytest.mark.parametrize("fault", ["membership", "missing", "private", "closed", "model"])
def test_mixed_batch_never_returns_partial_authority(reader, fault):
    s = reader
    s.update("cleanse_knowledge", embedding_model_id=2)
    if fault == "membership":
        s.update("cleanse_memberships", delete_flag="Y")
    elif fault in {"private", "closed", "model"}:
        with s.actor_engine.begin() as connection:
            fields = {"ingroup_permission": "PRIVATE", "created_by": "other"} if fault == "private" else (
                {"deletion_request": {"scope": "full"}} if fault == "closed" else {"embedding_model_id": None})
            connection.execute(s.tables["cleanse_knowledge"].update().where(
                s.tables["cleanse_knowledge"].c.knowledge_id == 1).values(**fields))
    with pytest.raises(ScopeDenied):
        authorize_knowledge_search(KnowledgeSearchAuthorization(knowledge_ids=[2, 999 if fault == "missing" else 1]),
                                   s.actor, context=context(), reader=s.service)
    assert s.opened == []


def test_display_name_is_normalized_without_changing_existing_grant_digest():
    row = {"knowledge_id": 1, "index_name": "kb", "tenant_id": "tenant-a", "embedding_model_id": 2}
    expected = knowledge_search_revision(row)
    assert knowledge_search_revision({**row, "knowledge_name": "Display name"}) == expected
    assert knowledge_search_revision({**row, "tenant_id": ASSET_OWNER_TENANT_ID}) != expected
