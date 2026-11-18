# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute existing chunk mutations with a real SI journal and an isolated vector boundary."""

from unittest.mock import Mock

import pytest
from nexent.storage.errors import (
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    DeleteReceipt,
    Revision,
    StorageScope,
    VectorKey,
    VectorRecord,
    WriteReceipt,
)
from runtime.knowledge_base.chunk_executor import ChunkMutationExecutor

from test.backend.services.test_knowledge_chunk_fencing import (
    context,
    intent,
    publish,
)
from test.backend.services.test_knowledge_chunk_fencing import (
    lifecycle as lifecycle,  # noqa: PLC0414
)


@pytest.fixture
def executor(lifecycle):
    s = lifecycle
    handle = publish(s)
    value = intent(s, handle)
    vectors = Mock()
    vectors.scope = StorageScope(
        "runtime", s.actor.tenant_id, s.actor.user_id, {"collection"}
    )
    vectors.get.return_value = VectorRecord(
        VectorKey("collection", value.chunk_id),
        (),
        {
            "knowledge_id": 1,
            "file_id": handle["file_id"],
            "file_version": 1,
            "chunk_index": 1,
            "content": "old",
            "filename": "file.txt",
            "location": {},
        },
        Revision(handle["attempt_id"]),
    )
    vectors.patch_payload.return_value = WriteReceipt("patch", True)
    vectors.delete_key.return_value = DeleteReceipt("delete", True)
    service = ChunkMutationExecutor(s.mutation, vectors, "collection")
    return s, service, vectors, value


def test_update_keeps_vector_and_only_commits_zero_count_once(executor):
    s, service, vectors, value = executor
    row = service.execute(value, context=context())
    assert row["status"] == "completed" and row["count_delta"] == 0
    assert vectors.get.call_args.kwargs["include_vector"] is False
    assert vectors.patch_payload.call_args.args[1].set_values == {"content": "new"}
    assert (
        service.execute(value, context=context())["mutation_id"] == row["mutation_id"]
    )
    assert vectors.patch_payload.call_count == 1
    vectors.delete_key.assert_not_called()
    assert (
        s.mutation.file_delta(value.file_ref, value.generation, context=context()) == 0
    )


def test_delete_uses_one_exact_key_and_commits_negative_effect(executor):
    s, service, vectors, value = executor
    value = value.model_copy(update={"operation": "delete", "changes": {}})
    row = service.execute(value, context=context())
    assert row["status"] == "completed" and row["count_delta"] == -1
    assert vectors.delete_key.call_args.args[0] == VectorKey(
        "collection", value.chunk_id
    )
    assert vectors.delete_key.call_args.kwargs["expected_generation"] == Revision(
        value.generation
    )
    assert (
        s.mutation.file_delta(value.file_ref, value.generation, context=context()) == -1
    )
    vectors.delete.assert_not_called()


@pytest.mark.parametrize("changes", [{"file_id": "other"}, {"embedding": [1.0]}, {}])
def test_update_rejects_protected_or_empty_fields_without_storage(executor, changes):
    s, service, vectors, value = executor
    with pytest.raises(InvalidInput):
        service.execute(
            value.model_copy(update={"changes": changes}), context=context()
        )
    vectors.get.assert_not_called()
    assert s.mutation.revision(context=context()) == 0


def test_missing_record_releases_admission_without_count_effect(executor):
    s, service, vectors, value = executor
    vectors.get.return_value = None
    with pytest.raises(NotFound):
        service.execute(value, context=context())
    s.mutation.assert_drained(context=context())
    assert s.mutation.revision(context=context()) == 0
    vectors.patch_payload.assert_not_called()


@pytest.mark.parametrize(
    "field,changed",
    [
        ("knowledge_id", 2),
        ("file_id", "b" * 32),
        ("file_version", 2),
        ("chunk_index", 2),
    ],
)
def test_record_file_identity_must_match_admitted_cleanup_scope(
    executor, field, changed
):
    s, service, vectors, value = executor
    vectors.get.return_value.payload[field] = changed
    with pytest.raises(ScopeDenied):
        service.execute(value, context=context())
    vectors.patch_payload.assert_not_called()
    s.mutation.assert_drained(context=context())


def test_unknown_write_is_not_counted_or_replayed(executor):
    s, service, vectors, value = executor
    vectors.patch_payload.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        service.execute(value, context=context())
    row = service.execute(value, context=context())
    assert row["status"] == "unknown" and row["count_delta"] is None
    assert vectors.patch_payload.call_count == 1
    with pytest.raises(Conflict):
        s.mutation.assert_drained(context=context())


def test_known_provider_cas_conflict_releases_admission(executor):
    s, service, vectors, value = executor
    vectors.patch_payload.side_effect = Conflict()
    with pytest.raises(Conflict):
        service.execute(value, context=context())
    s.mutation.assert_drained(context=context())
    assert service.execute(value, context=context())["status"] == "failed"
    assert vectors.patch_payload.call_count == 1


def test_confirmed_write_with_failed_ledger_ack_never_reexecutes(executor, monkeypatch):
    s, service, vectors, value = executor
    monkeypatch.setattr(s.mutation, "complete", Mock(side_effect=OutcomeUnknown()))
    with pytest.raises(OutcomeUnknown):
        service.execute(value, context=context())
    assert service.execute(value, context=context())["status"] == "writing"
    assert vectors.patch_payload.call_count == 1
    with pytest.raises(Conflict):
        s.mutation.assert_drained(context=context())


@pytest.mark.parametrize(
    "receipt",
    [
        WriteReceipt("write", True, outcome="invalid"),
        WriteReceipt("write", True, outcome="failed"),
        WriteReceipt("write", True, outcome="confirmed"),
        None,
    ],
)
def test_malformed_provider_receipt_is_unknown_and_not_counted(executor, receipt):
    _s, service, vectors, value = executor
    vectors.patch_payload.return_value = receipt
    with pytest.raises(OutcomeUnknown):
        service.execute(value, context=context())
    assert service.execute(value, context=context())["status"] == "unknown"
    assert vectors.patch_payload.call_count == 1


def test_budget_expiry_retains_active_writer_without_new_bookkeeping_budget(executor):
    from time import monotonic

    s, service, vectors, value = executor
    budget = context()

    def expire(*args, **kwargs):
        object.__setattr__(budget, "deadline", monotonic() - 1)
        raise OutcomeUnknown()

    vectors.patch_payload.side_effect = expire
    with pytest.raises(OutcomeUnknown):
        service.execute(value, context=budget)
    assert service.execute(value, context=context())["status"] == "writing"
    assert vectors.patch_payload.call_count == 1
    with pytest.raises(Conflict):
        s.mutation.assert_drained(context=context())


def test_omitted_file_binding_cannot_hide_file_cleanup_obligations(executor):
    s, service, vectors, value = executor
    value = value.model_copy(
        update={"file_ref": None, "generation": None, "chunk_index": None}
    )
    with pytest.raises(ScopeDenied):
        service.execute(value, context=context())
    vectors.patch_payload.assert_not_called()
    s.mutation.assert_drained(context=context())
