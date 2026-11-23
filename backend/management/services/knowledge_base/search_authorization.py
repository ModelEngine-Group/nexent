# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attest current KB access and the exact sources of explicitly selected files."""

from collections import defaultdict

from contracts.agentos_knowledge import (
    KnowledgeBaseGrant,
    KnowledgeLegacySearchFile,
    KnowledgeSearchAuthorization,
    KnowledgeSearchGrant,
)
from management.services.knowledge_base.file_authorization import (
    KnowledgeFileAuthorization,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from management.services.knowledge_base.legacy_vector_file_links import (
    active_file_aliases,
    conflicting_source_addresses,
    legacy_source_addresses,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, PageRequest, RecordQuery

from infrastructure.knowledge_deletion import knowledge_deletion_ports
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
        if not isinstance(request, KnowledgeSearchAuthorization) or request.selected_files:
            raise ScopeDenied()
        rows = self.resources.resolve_knowledges(request.knowledge_ids, edit=edit, context=context)
        return _search_grant(rows)


def authorize_knowledge_search(request, actor, *, context, reader=None):
    if not isinstance(request, KnowledgeSearchAuthorization):
        raise ScopeDenied()
    rows = (reader or KnowledgeFileReader()).knowledges(request.knowledge_ids, actor, context=context)
    grant = _search_grant(rows)
    if not request.selected_files:
        return grant
    by_knowledge = defaultdict(list)
    for ref in request.selected_files:
        by_knowledge[ref.knowledge_id].append(ref)
    with knowledge_deletion_ports(actor, context=context) as (records, files):
        for row in rows:
            refs = by_knowledge[row["knowledge_id"]]
            if not refs:
                continue
            if row["tenant_id"] != actor.tenant_id:
                raise ScopeDenied()
            grant.legacy_files.extend(_legacy_sources(records, files, row["knowledge_id"], refs, context=context))
    return grant


def _legacy_sources(records, files, knowledge_id, references, *, context):
    selected = {ref.file_id: ref for ref in references}
    page = files.query("cleanse_files", RecordQuery(where=Comparison("file_id", "in", list(selected))),
                       PageRequest(limit=len(selected)), context=context)
    if page.next_cursor or len(page.items) != len(selected):
        raise ScopeDenied()
    candidates, owners = {}, {}
    for row in page.items:
        file_id = row["file_id"]
        ref = selected.get(file_id)
        if (ref is None or row["knowledge_id"] != knowledge_id or row["source_generation"] != ref.file_version
            or row["status"] in {"DELETE_REQUESTED", "DELETED"}):
            raise ScopeDenied()
        if row["status"] != "COMPLETED" or row["deletion_request"] is not None:
            continue
        try:
            addresses = legacy_source_addresses(row, strict=True)
        except Conflict:
            continue
        if addresses:
            candidates[file_id] = addresses
            for address in addresses:
                owners[address] = file_id if address not in owners else None
    if not owners:
        return []
    conflicts = conflicting_source_addresses(files, knowledge_id, owners, context=context)
    candidates = {file_id: addresses - conflicts for file_id, addresses in candidates.items() if addresses - conflicts}
    aliases = active_file_aliases(records, knowledge_id, candidates.keys(), context=context)
    return [KnowledgeLegacySearchFile(**selected[file_id].model_dump(), addresses=sorted(candidates[file_id]),
                                      alias=aliases.get(file_id)) for file_id in sorted(candidates)]
