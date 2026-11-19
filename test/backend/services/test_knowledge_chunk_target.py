# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Write preparation obtains real bindings and prevents stale metadata replacement."""

from contextlib import contextmanager

import pytest
from contracts.knowledge_chunk_mutation import ChunkMutationLookup
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Revision, VectorKey, VectorRecord

from test.backend.services.test_knowledge_chunk_creation import context, publish
from test.backend.services.test_knowledge_chunk_write_service import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_write_service import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_write_service import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_write_service import (
    write as write,  # noqa: PLC0414
)


@pytest.fixture
def target(write):
    s = write

    @contextmanager
    def ports(actor, grant, *, context):
        assert actor == s.s.s.actor and grant.collection == "collection"
        yield s.s.s.record, s.s.vectors

    s.service.lookup_ports = ports
    s.lookup = ChunkMutationLookup(
        knowledge_id=1,
        chunk_id="manual",
        operation="create",
        resource_revision="a" * 64,
    )
    return s


async def test_missing_target_has_no_invented_file_or_generation(target):
    s = target
    result = await s.service.lookup(s.lookup, s.s.s.actor)
    assert (
        result.chunk is None and result.generation is None and result.change_epoch == 0
    )
    s.s.models.invoke.assert_not_awaited()


async def test_confirmed_standalone_target_returns_actual_generation_and_payload(
    target,
):
    s = target
    receipt = await s.service.mutate(s.s.value, s.s.s.actor)
    result = await s.service.lookup(s.lookup, s.s.s.actor)
    assert result.chunk.chunk_id == "manual" and result.chunk.file_id is None
    assert (
        result.generation == receipt.mutation_id
        and result.change_epoch == receipt.commit_epoch
    )
    assert result.chunk.content == "body" and result.chunk.filename is None


async def test_file_target_returns_real_publication_binding(target):
    s = target
    handle = await s.s.db(publish, s.s.s)
    s.s.stored[0] = VectorRecord(
        VectorKey("collection", "manual"),
        (),
        {
            "knowledge_id": 1,
            "file_id": handle["file_id"],
            "file_version": 1,
            "chunk_index": 2,
            "content": "file body",
            "filename": "file.txt",
            "location": {},
        },
        Revision(handle["attempt_id"]),
    )
    result = await s.service.lookup(s.lookup, s.s.s.actor)
    assert (
        result.chunk.file_id,
        result.chunk.file_version,
        result.chunk.chunk_index,
    ) == (handle["file_id"], 1, 2)
    assert result.generation == handle["attempt_id"]


@pytest.mark.parametrize("fault", ["foreign", "orphan", "stale-file"])
async def test_untrusted_or_retired_native_target_is_refused(target, fault):
    s = target
    handle = await s.s.db(publish, s.s.s) if fault == "stale-file" else None
    data = {
        "knowledge_id": 2 if fault == "foreign" else 1,
        "file_id": None,
        "file_version": None,
        "chunk_index": None,
        "content": "untrusted",
        "filename": None,
        "location": {},
    }
    if handle:
        data.update(file_id=handle["file_id"], file_version=1, chunk_index=0)
    s.s.stored[0] = VectorRecord(
        VectorKey("collection", "manual"), (), data, Revision("unconfirmed")
    )
    with pytest.raises((Conflict, ScopeDenied)):
        await s.service.lookup(s.lookup, s.s.s.actor)


async def test_lookup_epoch_rejects_stale_new_write_but_keeps_repeat_idempotent(target):
    s = target
    before = await s.service.lookup(s.lookup, s.s.s.actor)
    payload = s.s.value.model_copy(
        update={"expected_change_epoch": before.change_epoch}
    )
    receipt = await s.service.mutate(payload, s.s.s.actor)
    assert await s.service.mutate(payload, s.s.s.actor) == receipt
    assert s.s.vectors.put.call_count == 1
    stale = payload.model_copy(update={"request_key": "stale"})
    with pytest.raises(Conflict):
        await s.service.mutate(stale, s.s.s.actor)
    assert s.s.vectors.put.call_count == 1


async def test_target_reauthorization_change_refuses_content(target):
    s = target
    await s.service.mutate(s.s.value, s.s.s.actor)
    s.client.authorize_knowledge_chunk_mutation.side_effect = [
        s.grant,
        s.grant.model_copy(update={"revision": "b" * 64}),
    ]
    with pytest.raises(Conflict):
        await s.service.lookup(s.lookup, s.s.s.actor)


async def test_active_admission_refuses_lookup_before_native_read(target):
    s = target
    pending = s.s.value.model_copy(update={"request_key": "pending"})
    await s.s.db(s.s.s.mutation.reserve, pending, context=context())
    with pytest.raises(Conflict):
        await s.service.lookup(s.lookup, s.s.s.actor)
    s.s.vectors.get.assert_not_called()


async def test_target_rechecks_file_visibility_after_remote_grant(target):
    from contracts.agentos_knowledge import KnowledgeFileDelete

    s = target
    handle = await s.s.db(publish, s.s.s)
    s.s.stored[0] = VectorRecord(
        VectorKey("collection", "manual"),
        (),
        {
            "knowledge_id": 1,
            "file_id": handle["file_id"],
            "file_version": 1,
            "chunk_index": 0,
            "content": "file body",
            "filename": "file.txt",
            "location": {},
        },
        Revision(handle["attempt_id"]),
    )
    calls = []

    async def authorize(*args):
        calls.append(True)
        if len(calls) == 2:
            await s.s.db(
                s.s.s.policy.submit,
                KnowledgeFileDelete(
                    knowledge_id=1,
                    file_id=handle["file_id"],
                    file_version=1,
                    idempotency_key="delete-during-target",
                ),
                context=context(),
            )
        return s.grant

    s.client.authorize_knowledge_chunk_mutation.side_effect = authorize
    with pytest.raises(Conflict):
        await s.service.lookup(s.lookup, s.s.s.actor)


def test_absent_epoch_preserves_existing_intent_digest(target):
    import hashlib
    import json

    payload = target.s.value.model_dump(mode="json", exclude={"expected_change_epoch"})
    expected = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    assert target.s.value.fingerprint() == expected


@pytest.mark.parametrize("alias", ["public", "123", "false"])
async def test_public_alias_returns_real_key_only_when_explicitly_requested(
    target, alias
):
    from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
    from nexent.storage.models import Page

    s = target
    value = s.s.value.model_copy(
        update={
            "changes": {
                **s.s.value.changes,
                "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": ["public", 123, False]}},
            }
        }
    )
    receipt = await s.service.mutate(value, s.s.s.actor)
    s.s.vectors.get.side_effect = lambda key, **kwargs: (
        s.s.stored[0] if key == s.s.stored[0].key else None
    )
    s.s.vectors.scan.return_value = Page((s.s.stored[0],))
    lookup = s.lookup.model_copy(update={"chunk_id": alias, "resolve_public_id": True})
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(
        update={"chunk_id": alias}
    )
    result = await s.service.lookup(lookup, s.s.s.actor)
    assert result.chunk_id == alias and result.chunk.chunk_id == "manual"
    assert result.generation == receipt.mutation_id
    assert s.s.vectors.get.call_args.args[0].key == alias


async def test_default_lookup_does_not_resolve_public_id_and_real_key_has_priority(
    target,
):
    from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY

    s = target
    value = s.s.value.model_copy(
        update={
            "changes": {
                **s.s.value.changes,
                "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": "public"}},
            }
        }
    )
    await s.service.mutate(value, s.s.s.actor)
    s.s.vectors.get.side_effect = lambda key, **kwargs: (
        s.s.stored[0] if key == s.s.stored[0].key else None
    )
    assert (await s.service.lookup(s.lookup, s.s.s.actor)).chunk.chunk_id == "manual"
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(
        update={"chunk_id": "public"}
    )
    assert (
        await s.service.lookup(
            s.lookup.model_copy(update={"chunk_id": "public"}), s.s.s.actor
        )
    ).chunk is None
    s.s.vectors.scan.assert_not_called()


async def test_provider_read_failure_never_starts_alias_scan(target):
    from nexent.storage.errors import Unavailable

    s = target
    s.s.vectors.get.side_effect = Unavailable()
    with pytest.raises(Unavailable):
        await s.service.lookup(
            s.lookup.model_copy(update={"resolve_public_id": True}), s.s.s.actor
        )
    s.s.vectors.scan.assert_not_called()


@pytest.mark.parametrize("fault", ["foreign", "generation"])
async def test_alias_scan_never_returns_foreign_or_unconfirmed_content(target, fault):
    from dataclasses import replace

    from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
    from nexent.storage.models import Page

    s = target
    value = s.s.value.model_copy(
        update={
            "changes": {
                **s.s.value.changes,
                "location": {PUBLIC_CHUNK_SOURCE_KEY: {"id": "public"}},
            }
        }
    )
    await s.service.mutate(value, s.s.s.actor)
    original = s.s.stored[0]
    row = (
        replace(original, payload={**original.payload, "knowledge_id": 2})
        if fault == "foreign"
        else replace(original, generation=Revision("unconfirmed"))
    )
    s.s.vectors.get.return_value = None
    s.s.vectors.get.side_effect = None
    s.s.vectors.scan.return_value = Page((row,))
    s.client.authorize_knowledge_chunk_mutation.return_value = s.grant.model_copy(
        update={"chunk_id": "public"}
    )
    lookup = s.lookup.model_copy(
        update={"chunk_id": "public", "resolve_public_id": True}
    )
    if fault == "foreign":
        with pytest.raises(ScopeDenied):
            await s.service.lookup(lookup, s.s.s.actor)
    else:
        assert (await s.service.lookup(lookup, s.s.s.actor)).chunk is None
