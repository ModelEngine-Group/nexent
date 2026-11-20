# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Media evidence only trusts confirmed publication and the exact image manifest."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos_knowledge import KnowledgeContentGrant, ObjectReference
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import KnowledgeCollectionGrant
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import Page, Revision, VectorKey
from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.media_inspection import inspect_media

from test.backend.services.test_knowledge_search import search  # noqa: F401
from test.backend.services.test_knowledge_worker import setup  # noqa: F401


@pytest.mark.parametrize("mode", ["text", "image", "revoked-image", "foreign-grant", "stale", "standalone", "mutated"])
async def test_media_evidence_uses_visible_ingestion_or_reports_reason(search, mode, mocker):  # noqa: F811
    s, _, _, record, _ = search
    file_id = record.payload["file_id"]
    data = {**record.payload, "chunk_index": 0, "parser_version": "v1"}
    image = ObjectReference(space="files", key="known/image.png", version="pinned", sha256="b" * 64)
    if mode in {"image", "revoked-image"}:
        data["location"] = {"kind": "image", "image_ref": image.model_dump()}
    if mode == "standalone":
        data.update(file_id=None, file_version=None, chunk_index=None)
    if mode == "mutated":
        mocker.patch.object(ChunkReadView, "has_confirmed_mutation", return_value=True)
    row = replace(record, key=VectorKey("kb", f"1/{file_id}/0/0"), payload=data,
                  generation=Revision("stale") if mode == "stale" else record.generation)
    s.vectors.collection_exists.return_value = True
    s.vectors.scan.return_value = Page((row,))
    grant = KnowledgeCollectionGrant(knowledge_id=1, collection="kb", revision="a" * 64,
        resource_tenant_id="foreign" if mode == "foreign-grant" else s.actor.tenant_id)

    def image_grant(request, user, tenant):
        assert (user, tenant) == (s.actor.user_id, s.actor.tenant_id)
        assert request.image_ref == image
        if mode == "revoked-image":
            raise RuntimeUpstreamError(403, b"", {})
        return KnowledgeContentGrant(**request.model_dump(), object_ref=image, filename="source")

    client = SimpleNamespace(authorize_knowledge_collection=AsyncMock(return_value=grant),
                             authorize_knowledge_content=AsyncMock(side_effect=image_grant))

    @contextmanager
    def ports(actor, resource, *, context):
        assert actor == s.actor and resource.collection == "kb"
        yield s.records, s.vectors

    frames = []
    if mode == "foreign-grant":
        with pytest.raises(ScopeDenied):
            await inspect_media(client, s.actor, 1, frames.append, context=s.context, ports=ports)
        s.vectors.scan.assert_not_called()
        return
    result = await inspect_media(client, s.actor, 1, frames.append, context=s.context, ports=ports)
    reason = {"text": "CONFIRMED_INGESTED_TEXT", "image": "CONFIRMED_MANIFEST_IMAGE",
              "revoked-image": "UNPROVEN_IMAGE", "stale": "NO_CURRENT_FILE_PUBLICATION",
              "standalone": "STANDALONE_PROVENANCE_UNAVAILABLE", "mutated": "CHUNK_HAS_MUTATION"}[mode]
    assert result["counts"] == {reason: 1}
    assert frames == [{"kind": "vector", "chunk_id": row.key.key, "file_id": data["file_id"],
                       "file_version": data["file_version"], "generation": row.generation.value, "reason": reason}]
    options = s.vectors.scan.call_args.kwargs
    assert options["vectors_only"] and not options["include_vector"]
    assert client.authorize_knowledge_content.await_count == (1 if mode in {"image", "revoked-image"} else 0)
