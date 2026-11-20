# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Media evidence only trusts confirmed publication and the exact image manifest."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos_knowledge import KnowledgeContentGrant, ObjectReference
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.knowledge_collections import KnowledgeCollectionGrant
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Page, Revision, VectorKey, VectorRecord, WriteReceipt
from runtime.knowledge_base.chunk_view import ChunkReadView
from runtime.knowledge_base.media_inspection import inspect_media

from test.backend.services.test_knowledge_search import search  # noqa: F401
from test.backend.services.test_knowledge_worker import setup  # noqa: F401


@pytest.mark.parametrize("mode", ["text", "image", "revoked-image", "foreign-grant", "stale", "standalone", "mutated"])
@pytest.mark.parametrize("apply", [False, True])
async def test_media_evidence_uses_visible_ingestion_or_reports_reason(search, mode, mocker, apply):  # noqa: F811
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
    row = VectorRecord(VectorKey("kb", f"1/{file_id}/0/0"), (), data,
                       Revision("stale") if mode == "stale" else record.generation,
                       storage_revision=Revision("10:2") if apply else None)
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
    assert result["applied"] == 0
    assert frames == [{"kind": "vector", "chunk_id": row.key.key, "file_id": data["file_id"],
                       "file_version": data["file_version"], "generation": row.generation.value, "reason": reason}]
    options = s.vectors.scan.call_args.kwargs
    assert options["vectors_only"] and not options["include_vector"]
    assert client.authorize_knowledge_content.await_count == (1 if mode in {"image", "revoked-image"} else 0)
    if apply:
        writer = Mock()
        writer.patch_payload.return_value = WriteReceipt("patch", True)
        factory = Mock(return_value=writer)
        frames.clear()
        with pytest.raises(Conflict):
            await inspect_media(client, s.actor, 1, frames.append, context=s.context, ports=ports,
                                apply_revision="0" * 64, writer_factory=factory)
        factory.assert_not_called()
        result = await inspect_media(client, s.actor, 1, frames.append, context=s.context, ports=ports,
                                     apply_revision=result["data_revision"], writer_factory=factory)
        kind = mode if mode in {"text", "image"} else None
        assert result["applied"] == int(kind is not None)
        if kind is None:
            factory.assert_not_called()
        else:
            assert frames[0]["applied_media_kind"] == kind
            assert writer.patch_payload.call_args.args[1].set_values == {"media_kind": kind}
            assert writer.patch_payload.call_args.kwargs["expected_generation"] == row.generation
            assert writer.patch_payload.call_args.kwargs["expected_storage_revision"] == row.storage_revision
            writer.close.assert_called_once()
