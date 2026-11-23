# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Physical cleanup requires its durable owner attempt and ended covered writers."""

import pytest
from contracts.agentos_knowledge import KnowledgeFileDelete
from nexent.storage.errors import Conflict, InvalidInput

from test.backend.services.test_knowledge_jobs import lookup, started
from test.backend.services.test_knowledge_jobs import (
    setup as setup,  # noqa: PLC0414 - Actual record fixture.
)


def deletion(request):
    return KnowledgeFileDelete(**request.model_dump(include={"knowledge_id", "file_id", "file_version"}),
                               idempotency_key="delete")


def test_unended_writer_blocks_begin_and_a_started_delete_never_replays(setup):
    policy, _records, _, request, context, _, _ = setup
    _, writer = started(setup)
    state = policy.submit(deletion(request), context=context)
    assert policy.begin_delete(lookup(state), owner_id="cleaner", context=context) is None
    assert policy.end_attempt(writer, writer_ended=True, context=context)
    handle = policy.begin_delete(lookup(state), owner_id="cleaner", context=context)
    assert handle["write_started"] and handle["reconcile_required"]
    assert policy.begin_delete(lookup(state), owner_id="other", context=context) is None
    assert policy.inspect(lookup(state), context=context).status == "cleanup_pending"
    assert not policy.inspect(lookup(state), context=context).physical_cleanup_complete
    with pytest.raises(Conflict):
        policy.finish_delete(lookup(state), physical_absence_confirmed=True, deleted_count=0, context=context)
    with pytest.raises(Conflict):
        policy.finish_delete({**handle, "attempt_id": "foreign"}, physical_absence_confirmed=True, deleted_count=0, context=context)
    assert policy.finish_delete(handle, physical_absence_confirmed=True, deleted_count=0, context=context).status == "deleted"
    assert policy.begin_delete(lookup(state), owner_id="another", context=context) is None


def test_confirmed_count_survives_inspect_and_cannot_be_replaced(setup):
    policy, _, _, request, context, _, _ = setup
    state = policy.submit(deletion(request), context=context)
    handle = policy.begin_delete(lookup(state), owner_id='cleaner', context=context)
    final = policy.finish_delete(handle, physical_absence_confirmed=True, deleted_count=3, context=context)
    assert final.processed_chunks == final.total_chunks == 3
    assert policy.inspect(lookup(state), context=context) == final
    with pytest.raises(Conflict):
        policy.finish_delete(handle, physical_absence_confirmed=True, deleted_count=4, context=context)
    assert policy.inspect(lookup(state), context=context) == final


def test_owned_delete_resolves_only_native_upload_attempts_through_tombstone(setup):
    policy, records, engine, request, context, now, authorize = setup

    def upload(native, **changes):
        proposal = request.model_copy(update={"native_documents": native, **changes})
        _, writer = started((policy, records, engine, proposal, context, now, authorize))
        assert policy.complete(writer, chunk_count=1, context=context)
        return writer

    old = upload(True)
    upload(False, file_id="b" * 32, idempotency_key="other")
    upload(True, file_id="c" * 32, idempotency_key="other-native")
    upload(True, file_version=request.file_version + 1, idempotency_key="newer")
    state = policy.submit(deletion(request), context=context)
    handle = policy.begin_delete(lookup(state), owner_id="cleaner", context=context)
    assert policy.native_cleanup_generations(handle, context=context) == {old["attempt_id"]: request.file_version}
    with pytest.raises(Conflict):
        policy.native_cleanup_generations({**handle, "attempt_id": "wrong"}, context=context)


@pytest.mark.parametrize('count', [-1, True, 2**31, 1.5, None])
def test_invalid_count_cannot_complete_deletion(setup, count):
    policy, _, _, request, context, _, _ = setup
    state = policy.submit(deletion(request), context=context)
    handle = policy.begin_delete(lookup(state), owner_id='cleaner', context=context)
    with pytest.raises(InvalidInput):
        policy.finish_delete(handle, physical_absence_confirmed=True, deleted_count=count, context=context)
    pending = policy.inspect(lookup(state), context=context)
    assert pending.status == 'cleanup_pending' and pending.processed_chunks is None
