# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management attests current local KB read scope without accessing files or jobs."""

from contracts.agentos_knowledge import (
    KnowledgeBaseGrant,
    KnowledgeSearchAuthorization,
    KnowledgeSearchGrant,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import ScopeDenied

from infrastructure.knowledge_search import knowledge_search_revision


def _search_grant(rows):
    grants = []
    for row in rows:
        if (row.get("deletion_request") is not None or row.get("knowledge_sources") != "elasticsearch"
            or type(row.get("embedding_model_id")) is not int or row["embedding_model_id"] <= 0):
            raise ScopeDenied()
        grants.append(KnowledgeBaseGrant(knowledge_id=row["knowledge_id"], collection=row["index_name"],
            resource_tenant_id=row["tenant_id"], embedding_model_id=row["embedding_model_id"], revision=knowledge_search_revision(row)))
    if len({g.collection for g in grants}) != len(grants):
        raise ScopeDenied()
    return KnowledgeSearchGrant(knowledge_bases=grants)


class KnowledgeSearchAuthorizationPolicy:
    def __init__(self, records, *, user_id):
        self.resources = KnowledgeFileAuthorization(records, user_id=user_id)

    def authorize(self, request, *, context, edit=False):
        if not isinstance(request, KnowledgeSearchAuthorization):
            raise ScopeDenied()
        rows = self.resources.resolve_knowledges(request.knowledge_ids, edit=edit, context=context)
        return _search_grant(rows)


def authorize_knowledge_search(request, actor, *, context, reader=None):
    if not isinstance(request, KnowledgeSearchAuthorization):
        raise ScopeDenied()
    rows = (reader or KnowledgeFileReader()).knowledges(request.knowledge_ids, actor, context=context)
    return _search_grant(rows)
