# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime ingestion validates artifacts and model results before scoped writes."""

import asyncio
import hashlib
import io
import re
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata, ModelResult
from contracts.agentos_knowledge import KnowledgeFileUpload
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OperationCancelled,
    OutcomeUnknown,
    PartialFailure,
    ScopeDenied,
)
from nexent.storage.models import (
    ObjectMetadata,
    ObjectRef,
    OperationContext,
    Revision,
    StorageScope,
    VectorCollectionInfo,
    WriteOutcome,
    WriteReceipt,
)
from runtime.knowledge_base.ingestion import KnowledgeIngestor

from infrastructure.agentos_identity import ServicePrincipal
from test.backend.services.test_knowledge_chunking import artifact


@pytest.fixture
def setup(mocker):
    async def direct(_name, fn, *args, lane, owner, **kwargs):
        assert lane == "control-io" and owner == "runtime.knowledge_base"
        return fn(*args, **kwargs)

    mocker.patch("runtime.knowledge_base.ingestion.run_blocking", side_effect=direct)
    actor = ServicePrincipal("user", "tenant")
    value = artifact(["first", "second"])
    content = value.model_dump_json().encode()
    reference = value.source.model_copy(
        update={"key": "artifact", "sha256": hashlib.sha256(content).hexdigest()}
    )
    request = KnowledgeFileUpload(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=4,
        artifact=reference,
        parser_version=value.parser_version,
        idempotency_key="upload-1",
        embedding_model={"model_id": 2, "revision": "model-v1"},
        chunking_strategy="none",
    )
    streams = []

    @contextmanager
    def open_read(ref, *, context):
        stream = io.BytesIO(content if ref.key == "artifact" else b"source")
        streams.append(stream)
        try:
            yield stream
        finally:
            stream.close()

    objects = Mock(
        scope=StorageScope("runtime", "tenant", "user", {"files"}),
        stat=Mock(
            return_value=ObjectMetadata(
                ObjectRef(reference.space, reference.key, Revision(reference.version)),
                len(content),
                "application/json",
                sha256=reference.sha256,
            )
        ),
        open_read=Mock(side_effect=open_read),
    )
    vectors = Mock(
        scope=StorageScope("runtime", "tenant", "user", {"kb"}),
        describe_collection=Mock(return_value=VectorCollectionInfo("kb", 2, "cosine")),
        upsert=Mock(
            side_effect=lambda rows, **kw: tuple(
                WriteReceipt(str(index), True) for index, _ in enumerate(rows)
            )
        ),
    )
    models = SimpleNamespace(
        get=AsyncMock(
            return_value=ModelMetadata(
                model_id=2,
                model_type="embedding",
                display_name="model",
                revision="model-v1",
            )
        ),
        invoke=AsyncMock(
            side_effect=lambda payload, actor: ModelResult(
                revision="model-v1", output=[[1.0, 0.5] for _ in payload.input]
            )
        ),
    )
    service = KnowledgeIngestor(
        objects, vectors, models, max_artifact_bytes=10000, max_source_bytes=10000
    )
    arguments = {
        "actor": actor,
        "source": value.source,
        "filename": "source.txt",
        "collection": "kb",
        "generation": Revision("attempt-1"),
        "context": OperationContext("ingest-1", monotonic() + 5),
    }
    return SimpleNamespace(**locals())


async def test_upload_calls_model_invoke_and_writes_stable_scoped_chunks(setup):
    s = setup
    first = await s.service.execute(s.request, **s.arguments)
    second = await s.service.execute(s.request, **s.arguments)
    assert first == second and len(first.chunk_keys) == 1
    assert first.embedding_revision == "model-v1"
    payload, actor = s.models.invoke.call_args.args
    assert (
        payload.input == ["first\n\nsecond"] and payload.expected_revision == "model-v1"
    )
    assert actor == s.actor
    row = s.vectors.upsert.call_args.args[0][0]
    assert row.key.key == first.chunk_keys[0] and row.generation == Revision(
        "attempt-1"
    )
    assert row.payload["file_id"] == s.request.file_id
    assert row.key.key == f"1/{s.request.file_id}/4/0"
    assert row.payload["file_version"] == 4 and row.payload["knowledge_id"] == 1
    assert row.payload["embedding_revision"] == "model-v1"
    assert all(stream.closed for stream in s.streams)
    assert s.objects.stat.call_args.args[0].version == Revision("v1")


@pytest.mark.parametrize(
    "port,field,value",
    [
        ("objects", "tenant_id", "other"),
        ("vectors", "tenant_id", "other"),
        ("objects", "service_role", "management"),
        ("vectors", "actor_id", "other"),
        ("objects", "namespaces", {"other"}),
        ("vectors", "namespaces", {"other"}),
    ],
)
async def test_scope_refusal_precedes_any_io(setup, port, field, value):
    s = setup
    target = getattr(s, port)
    target.scope = replace(target.scope, **{field: value})
    with pytest.raises(ScopeDenied):
        await s.service.execute(s.request, **s.arguments)
    s.models.get.assert_not_awaited()
    s.objects.stat.assert_not_called()
    s.vectors.upsert.assert_not_called()


@pytest.mark.parametrize(
    "updates", [{"revision": "changed"}, {"model_type": "llm"}, {"model_id": 8}]
)
async def test_model_preflight_blocks_artifact_read_and_write(setup, updates):
    s = setup
    s.models.get.return_value = s.models.get.return_value.model_copy(update=updates)
    with pytest.raises(Conflict):
        await s.service.execute(s.request, **s.arguments)
    s.objects.stat.assert_not_called()
    s.models.invoke.assert_not_awaited()
    s.vectors.upsert.assert_not_called()


@pytest.mark.parametrize(
    "change", ["hash", "version", "size", "parser", "source", "image"]
)
async def test_invalid_artifact_never_invokes_model(setup, change):
    s = setup
    if change in {"hash", "parser", "source", "image"}:
        if change == "hash":
            s.request.artifact.sha256 = "0" * 64
        elif change == "parser":
            s.request.parser_version = "different"
        elif change == "source":
            s.arguments["source"] = s.value.source.model_copy(
                update={"version": "different"}
            )
        else:
            from contracts.agentos_knowledge import CleanseArtifact, CleanseBlock

            s.models.get.return_value = s.models.get.return_value.model_copy(update={"model_type": "multi_embedding"})

            value = CleanseArtifact(
                source=s.value.source,
                parser_version=s.value.parser_version,
                blocks=[
                    CleanseBlock(
                        ordinal=0,
                        kind="image",
                        sha256=s.reference.sha256,
                        object_ref=s.reference,
                    )
                ],
            )
            content = value.model_dump_json().encode()
            s.request.artifact.sha256 = hashlib.sha256(content).hexdigest()
            s.objects.stat.return_value = replace(
                s.objects.stat.return_value, size=len(content), sha256=None
            )
            s.objects.open_read.side_effect = lambda *a, **kw: io.BytesIO(content)
    else:
        metadata = s.objects.stat.return_value
        s.objects.stat.return_value = replace(
            metadata,
            **(
                {"ref": ObjectRef("files", "artifact", Revision("other"))}
                if change == "version"
                else {"size": metadata.size + 1}
            ),
        )
    with pytest.raises(CapabilityUnsupported if change == "image" else InvalidInput):
        await s.service.execute(s.request, **s.arguments)
    s.models.invoke.assert_not_awaited()
    s.vectors.upsert.assert_not_called()
    assert all(stream.closed for stream in s.streams)


@pytest.mark.parametrize(
    "output",
    [
        [],
        [[1.0]],
        [[0.0, 0.0]],
        [[True, 1.0]],
        [[1.0, 1.0], [1.0, 1.0]],
        [[10**400, 1.0]],
        [[float("inf"), 1.0]],
    ],
)
async def test_bad_model_output_never_reaches_vector_write(setup, output):
    s = setup
    s.models.invoke.side_effect = None
    s.models.invoke.return_value = ModelResult(revision="model-v1", output=output)
    with pytest.raises(InvalidInput):
        await s.service.execute(s.request, **s.arguments)
    s.vectors.upsert.assert_not_called()


@pytest.mark.parametrize("error", [OutcomeUnknown(), PartialFailure(results=())])
async def test_unconfirmed_write_is_not_retried_or_reported_complete(setup, error):
    s = setup
    s.vectors.upsert.side_effect = error
    with pytest.raises(type(error)):
        await s.service.execute(s.request, **s.arguments)
    assert s.vectors.upsert.call_count == 1 and s.models.invoke.await_count == 1


@pytest.mark.parametrize(
    "receipts",
    [
        (),
        (WriteReceipt("one", False),),
        (WriteReceipt("one", True, outcome=WriteOutcome.UNKNOWN),),
    ],
)
async def test_incomplete_receipts_are_partial_failure(setup, receipts):
    s = setup
    s.vectors.upsert.side_effect = None
    s.vectors.upsert.return_value = receipts
    with pytest.raises(PartialFailure):
        await s.service.execute(s.request, **s.arguments)
    assert s.vectors.upsert.call_count == 1


async def test_hanging_model_obeys_total_deadline_and_is_cancelled(setup, caplog):
    s = setup
    finished = []

    async def hanging(*args):
        try:
            await asyncio.Event().wait()
        finally:
            finished.append(True)

    s.models.invoke.side_effect = hanging
    # Leave preparation time under shared CI load; this asserts cancellation,
    # not a 50 ms performance target for artifact verification.
    s.arguments["context"] = OperationContext("short", monotonic() + 1)
    with pytest.raises(DeadlineExceeded):
        await s.service.execute(s.request, **s.arguments)
    assert finished == [True] and s.models.invoke.await_count == 1
    s.vectors.upsert.assert_not_called()
    assert len(caplog.records) == 1 and caplog.records[0].levelname == "WARNING"
    assert "knowledge_model_timeout" in caplog.text and "short" in caplog.text
    assert not re.search(r"\b(first|second)\b", caplog.text)


async def test_cancelled_context_never_starts_lookup(setup):
    s = setup
    stop = Mock(is_set=Mock(return_value=True))
    s.arguments["context"] = OperationContext(
        "stopped", monotonic() + 5, cancelled=stop
    )
    with pytest.raises(OperationCancelled):
        await s.service.execute(s.request, **s.arguments)
    s.models.get.assert_not_awaited()


async def test_batches_stop_on_failure_without_reembedding_confirmed_batch(setup):
    s = setup
    s.arguments["filename"] = "source.xlsx"
    s.vectors.upsert.side_effect = [(WriteReceipt("0", True),), OutcomeUnknown()]
    with pytest.raises(OutcomeUnknown):
        await s.service.execute(s.request, batch_size=1, **s.arguments)
    assert [call.args[0].input for call in s.models.invoke.call_args_list] == [
        ["first"],
        ["second"],
    ]
    assert s.vectors.upsert.call_count == 2


async def test_model_revision_change_after_preflight_never_writes(setup):
    s = setup
    s.models.invoke.side_effect = None
    s.models.invoke.return_value = ModelResult(revision="changed", output=[[1.0, 0.5]])
    with pytest.raises(Conflict):
        await s.service.execute(s.request, **s.arguments)
    s.vectors.upsert.assert_not_called()


async def test_stream_checksum_is_independent_of_stat_metadata(setup):
    s = setup
    content = b"x" * s.objects.stat.return_value.size
    s.objects.open_read.side_effect = lambda *a, **kw: io.BytesIO(content)
    with pytest.raises(InvalidInput):
        await s.service.execute(s.request, **s.arguments)
    s.models.invoke.assert_not_awaited()
    s.vectors.upsert.assert_not_called()


async def test_task_cancellation_closes_model_call_and_never_writes(setup):
    s = setup
    started, stopped = asyncio.Event(), []

    async def hanging(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(True)

    s.models.invoke.side_effect = hanging
    task = asyncio.create_task(s.service.execute(s.request, **s.arguments))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped == [True]
    s.vectors.upsert.assert_not_called()


async def test_json_reads_pinned_source_before_final_chunking(setup):
    s = setup
    source = b'{"key": "value"}'
    value = artifact([""], source=source, locations=[{"element_type": "JSONSource"}])
    content = value.model_dump_json().encode()
    s.arguments.update(source=value.source, filename="source.json")
    s.request.artifact.sha256 = hashlib.sha256(content).hexdigest()
    references = []

    def stat(ref, *, context):
        references.append(ref)
        data = content if ref.key == "artifact" else source
        return ObjectMetadata(
            ref, len(data), "application/json", sha256=hashlib.sha256(data).hexdigest()
        )

    s.objects.stat.side_effect = stat
    s.objects.open_read.side_effect = lambda ref, **kw: io.BytesIO(
        content if ref.key == "artifact" else source
    )
    result = await s.service.execute(s.request, **s.arguments)
    assert len(result.chunk_keys) == 1
    assert references == [
        ObjectRef("files", "artifact", Revision("v1")),
        ObjectRef("files", "source", Revision("v1")),
    ]
    assert "value" in s.models.invoke.call_args.args[0].input[0]


@pytest.mark.parametrize(
    "arguments",
    [
        {"batch_size": 0},
        {"batch_size": 65},
        {"max_characters": True},
        {"generation": "attempt"},
        {"filename": ""},
    ],
)
async def test_invalid_parameters_do_not_start_io(setup, arguments):
    s = setup
    with pytest.raises(InvalidInput):
        await s.service.execute(s.request, **{**s.arguments, **arguments})
    s.models.get.assert_not_awaited()
    s.objects.stat.assert_not_called()
    s.vectors.upsert.assert_not_called()
