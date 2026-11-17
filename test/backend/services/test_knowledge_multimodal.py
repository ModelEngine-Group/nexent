# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Mixed ingestion checks image pins before inference and keeps bytes out of ES."""

import base64
import hashlib
import io
import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import CleanseBlock, KnowledgeFileGrant
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import (
    ObjectMetadata,
    ObjectRef,
    Revision,
    SearchHit,
    StorageScope,
)
from runtime.knowledge_base.search import KnowledgeSearchService

from infrastructure import knowledge_objects
from test.backend.services.test_knowledge_ingestion import (
    setup as setup,  # noqa: PLC0414
)


def add_image(s, count=1):
    raw = b"verified-image-bytes"
    digest = hashlib.sha256(raw).hexdigest()
    ref = s.value.source.model_copy(update={"key": f"images/{s.value.source.sha256}/{digest}.png",
                                           "sha256": digest, "version": "image-v1"})
    value = s.value.model_copy(update={"blocks": [*s.value.blocks, *[CleanseBlock(
        ordinal=len(s.value.blocks) + index, kind="image", sha256=digest, object_ref=ref,
        location={"page_number": 2}) for index in range(count)]]})
    content = value.model_dump_json().encode()
    s.request.artifact.sha256 = hashlib.sha256(content).hexdigest()
    s.objects.stat.return_value = replace(s.objects.stat.return_value, size=len(content), sha256=s.request.artifact.sha256)
    s.objects.open_read.side_effect = lambda *args, **kwargs: io.BytesIO(content)
    streams, closed = [], []

    def open_image(*args, **kwargs):
        stream = io.BytesIO(raw)
        streams.append(stream)
        return stream

    images = Mock(scope=StorageScope("runtime", "tenant", "user", {"files"}))
    images.stat.return_value = ObjectMetadata(ObjectRef("files", ref.key, Revision(ref.version)), len(raw), "image/png", sha256=digest)
    images.open_read.side_effect = open_image

    @contextmanager
    def factory(artifact, *, context):
        assert artifact == value
        try:
            yield images
        finally:
            closed.append(True)

    s.service.image_objects = factory
    return SimpleNamespace(**locals())


async def test_mixed_embedding_preserves_order_refs_and_not_bytes(setup):
    s = setup
    image = add_image(s)
    s.models.get.return_value = s.models.get.return_value.model_copy(update={"model_type": "multi_embedding"})
    result = await s.service.execute(s.request, **s.arguments)
    assert result.chunk_keys == (f"1/{s.request.file_id}/4/0", f"1/{s.request.file_id}/4/1")
    payloads = [call.args[0] for call in s.models.invoke.await_args_list]
    assert [payload.input_type for payload in payloads] == ["text", "image"]
    assert base64.b64decode(payloads[1].input[0].partition(",")[2]) == image.raw
    rows = s.vectors.upsert.call_args.args[0]
    assert rows[1].payload["location"] == {"page_number": 2, "kind": "image", "image_ref": image.ref.model_dump()}
    assert base64.b64encode(image.raw).decode() not in json.dumps([row.payload for row in rows])
    hit = KnowledgeSearchService._dto(SearchHit(rows[1].key, 1, "test.cosine", rows[1].payload, rows[1].generation))
    assert hit.image_ref == image.ref and hit.location["page_number"] == 2
    assert image.closed == [True] and all(stream.closed for stream in image.streams)


async def test_text_model_ignores_image_blocks_without_object_reads(setup):
    s = setup
    image = add_image(s)
    result = await s.service.execute(s.request, **s.arguments)
    assert len(result.chunk_keys) == 1
    assert s.models.invoke.await_args.args[0].input_type == "text"
    image.images.stat.assert_not_called()
    assert not image.closed


async def test_multimodal_provider_batches_keep_legacy_ten_input_limit(setup):
    s = setup
    add_image(s, count=23)
    s.service.max_artifact_bytes = 100000
    s.models.get.return_value = s.models.get.return_value.model_copy(update={"model_type": "multi_embedding"})
    result = await s.service.execute(s.request, **s.arguments)
    assert len(result.chunk_keys) == 24
    payloads = [call.args[0] for call in s.models.invoke.await_args_list]
    assert [(payload.input_type, len(payload.input)) for payload in payloads] == [
        ("text", 1), ("image", 10), ("image", 10), ("image", 3)]
    rows = s.vectors.upsert.call_args.args[0]
    assert [row.payload["chunk_index"] for row in rows] == list(range(24))


@pytest.mark.parametrize("failure", ["revision", "hash", "scope"])
async def test_image_failure_prevents_all_inference_and_writes(setup, failure):
    s = setup
    image = add_image(s)
    s.models.get.return_value = s.models.get.return_value.model_copy(update={"model_type": "multi_embedding"})
    metadata = image.images.stat.return_value
    if failure == "revision":
        image.images.stat.return_value = replace(metadata, ref=ObjectRef("files", image.ref.key, Revision("other")))
    elif failure == "hash":
        image.images.open_read.side_effect = lambda *args, **kwargs: io.BytesIO(b"x" * len(image.raw))
        image.images.stat.return_value = replace(metadata, sha256=None)
    else:
        image.images.scope = StorageScope("runtime", "foreign", "user", {"files"})
    with pytest.raises(ScopeDenied if failure == "scope" else InvalidInput):
        await s.service.execute(s.request, **s.arguments)
    s.models.invoke.assert_not_awaited()
    s.vectors.upsert.assert_not_called()
    assert image.closed == [True]


def test_image_subgrant_rejects_other_versions_and_sources(setup, mocker):
    s = setup
    image = add_image(s)
    grant = KnowledgeFileGrant(**s.request.model_dump(include={"knowledge_id", "file_id", "file_version", "artifact", "parser_version"}),
                               action="execute", source=s.value.source, filename="file.pdf", collection="kb")
    mocker.patch.object(knowledge_objects, "_configured_environment", return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="files"))
    client = mocker.patch.object(knowledge_objects, "_configured_client")
    with knowledge_objects.bind_knowledge_image_objects(s.actor, grant, image.value, context=s.arguments["context"]) as objects:
        with pytest.raises(ScopeDenied):
            objects.stat(ObjectRef("files", image.ref.key, Revision("different")), context=s.arguments["context"])
        with pytest.raises(ScopeDenied):
            objects.stat(ObjectRef("files", "images/foreign.png", Revision(image.ref.version)), context=s.arguments["context"])
    bad = image.value.model_copy(update={"blocks": [image.value.blocks[-1].model_copy(update={
        "object_ref": image.ref.model_copy(update={"key": "images/other/" + image.ref.sha256 + ".png"})})]})
    with pytest.raises(ScopeDenied), knowledge_objects.bind_knowledge_image_objects(s.actor, grant, bad, context=s.arguments["context"]):
        pass
    client.assert_not_called()
