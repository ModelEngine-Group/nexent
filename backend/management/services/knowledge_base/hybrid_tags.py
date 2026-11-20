# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Retain only already-ranked hits with the selected synchronized tags."""

from time import monotonic
from uuid import uuid4

from management.services.knowledge_base.tag_projection import (
    decode_document_resource_id,
)
from management.services.tag.identity import LOCAL_DOCUMENT_PROVIDER
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import OperationContext, PageRequest, RecordQuery, Sort

from infrastructure.rdb.hybrid_document_tags import (
    TAG_MATCHES,
    hybrid_document_tag_ports,
)


def filter_hybrid_tags(results, index_names, predicates, actor, *, ports=hybrid_document_tag_ports, context=None):
    groups = {}
    for predicate in predicates:
        definition = int(predicate["definition_id"])
        groups.setdefault(definition, set()).update(int(value) for value in predicate.get("value_ids", []))
    groups = {definition: sorted(values) for definition, values in groups.items() if values}
    context = context or OperationContext("hybrid-tags-" + uuid4().hex, monotonic() + 10)
    hits = {hit.get("index") for hit in results}
    paths_by_index = {}
    for index in dict.fromkeys(index_names):
        if index not in hits:
            continue
        paths = paths_by_index.setdefault(index, set())
        with ports(actor, index, groups, context=context) as records:
            cursor, seen = None, set()
            while True:
                page = records.query(TAG_MATCHES, RecordQuery(order_by=(Sort("resource_id"),)),
                                     PageRequest(limit=500, cursor=cursor), context=context)
                for record in page.items:
                    if record["tenant_id"] != actor.tenant_id:
                        raise ScopeDenied()
                    try:
                        provider, kb, path = decode_document_resource_id(record["resource_id"])
                    except ValueError:
                        continue
                    if provider == LOCAL_DOCUMENT_PROVIDER and kb == index:
                        paths.add(path)
                cursor = page.next_cursor
                if cursor is None:
                    break
                if cursor in seen:
                    raise Conflict()
                seen.add(cursor)
    return [hit for hit in results if hit.get("path_or_url") in paths_by_index.get(hit.get("index"), ())]
