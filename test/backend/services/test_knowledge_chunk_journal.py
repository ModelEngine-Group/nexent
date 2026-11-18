# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Use real neutral records to prove mutation state, idempotency and count isolation."""

from time import monotonic

import pytest
import sqlalchemy as sa
from contracts.agentos_knowledge import KnowledgeFileReference
from contracts.knowledge_chunk_mutation import ChunkMutationIntent
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import OperationContext, WriteOutcome
from runtime.knowledge_base.chunk_journal import ChunkMutationJournal

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.knowledge_chunk_mutations import bind_chunk_mutations, metadata


def context():
    return OperationContext("chunk-journal-test", monotonic() + 10)


def intent(key="request-one", operation="create", file=True):
    values = {
        "knowledge_id": 1,
        "chunk_id": "arbitrary logical id",
        "request_key": key,
        "operation": operation,
        "resource_revision": "a" * 64,
        "changes": {}
        if operation == "delete"
        else {"content": "sensitive text not stored"},
    }
    if file:
        values.update(
            file_ref=KnowledgeFileReference(
                knowledge_id=1, file_id="b" * 32, file_version=2
            ),
            generation="published",
            chunk_index=3,
        )
    return ChunkMutationIntent(**values)


@pytest.fixture
def journal():
    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    metadata.create_all(engine)
    actor = ServicePrincipal("operator", "tenant-a")
    records = bind_chunk_mutations(actor, engine)
    try:
        yield ChunkMutationJournal(records, 1), records, engine
    finally:
        records.close()
        engine.dispose()


def reserve(value, journal):
    row, fresh = journal.reserve(value, context=context())
    assert fresh
    return row


def complete(value, journal, delta):
    row = reserve(value, journal)
    writing, started = journal.begin(row["mutation_id"], context=context())
    assert started and writing["status"] == "writing"
    return journal.complete(
        row["mutation_id"],
        count_delta=delta,
        outcome=WriteOutcome.CONFIRMED,
        context=context(),
    )


def test_confirmed_change_counts_once_and_does_not_store_text(journal):
    manager, _, _engine = journal
    row = complete(intent(), manager, 1)
    assert (
        row["status"] == "completed"
        and row["writer_ended"]
        and row["commit_epoch"] == 1
    )
    assert "sensitive text" not in repr(row) and row["user_id"] == "operator"
    assert manager.revision(context=context()) == 1
    duplicate, fresh = manager.reserve(intent(), context=context())
    assert not fresh and duplicate["mutation_id"] == row["mutation_id"]
    assert (
        manager.complete(
            row["mutation_id"],
            count_delta=1,
            outcome=WriteOutcome.CONFIRMED,
            context=context(),
        )
        == row
    )
    assert manager.revision(context=context()) == 1
    assert manager.file_delta(intent().file_ref, "published", context=context()) == 1
    assert (
        manager.file_delta(intent().file_ref, "other-generation", context=context())
        == 0
    )


def test_request_key_reuse_with_different_content_is_conflict(journal):
    manager, *_ = journal
    reserve(intent(), manager)
    with pytest.raises(Conflict):
        manager.reserve(
            intent().model_copy(update={"changes": {"content": "changed"}}),
            context=context(),
        )


def test_other_request_cannot_enter_while_active(journal):
    manager, *_ = journal
    row = reserve(intent(), manager)
    with pytest.raises(Conflict):
        manager.reserve(intent("other"), context=context())
    first, started = manager.begin(row["mutation_id"], context=context())
    assert started
    second, started = manager.begin(row["mutation_id"], context=context())
    assert not started and first == second


def test_unknown_write_is_not_counted_or_released(journal):
    manager, *_ = journal
    row = reserve(intent(), manager)
    manager.begin(row["mutation_id"], context=context())
    unknown = manager.mark_unknown(
        row["mutation_id"],
        writer_ended=True,
        error_code="WRITE_TIMEOUT",
        context=context(),
    )
    assert unknown["status"] == "unknown" and unknown["count_delta"] is None
    with pytest.raises(Conflict):
        manager.revision(context=context())
    with pytest.raises(Conflict):
        manager.assert_drained(context=context())
    with pytest.raises(Conflict):
        manager.fail(
            row["mutation_id"],
            known_not_applied=True,
            error_code="FAILED",
            context=context(),
        )
    with pytest.raises(Conflict):
        manager.reserve(intent("another"), context=context())


def test_known_no_effect_failure_releases_without_advancing_epoch(journal):
    manager, *_ = journal
    row = reserve(intent(), manager)
    with pytest.raises(InvalidInput):
        manager.fail(
            row["mutation_id"],
            known_not_applied=False,
            error_code="FAILED",
            context=context(),
        )
    failed = manager.fail(
        row["mutation_id"],
        known_not_applied=True,
        error_code="REJECTED",
        context=context(),
    )
    assert failed["status"] == "failed" and failed["writer_ended"]
    assert manager.revision(context=context()) == 0
    manager.assert_drained(context=context())
    reserve(intent("next"), manager)


@pytest.mark.parametrize("delta", [-1, 2, True])
def test_create_rejects_invalid_count_effect(journal, delta):
    manager, *_ = journal
    row = reserve(intent(), manager)
    manager.begin(row["mutation_id"], context=context())
    with pytest.raises(InvalidInput):
        manager.complete(
            row["mutation_id"],
            count_delta=delta,
            outcome=WriteOutcome.CONFIRMED,
            context=context(),
        )


def test_unknown_receipt_cannot_be_confirmed(journal):
    manager, *_ = journal
    row = reserve(intent(), manager)
    manager.begin(row["mutation_id"], context=context())
    with pytest.raises(InvalidInput):
        manager.complete(
            row["mutation_id"],
            count_delta=1,
            outcome=WriteOutcome.UNKNOWN,
            context=context(),
        )


def test_actual_other_actor_cannot_inspect_or_complete_issuer_change(journal):
    manager, _, engine = journal
    row = reserve(intent(), manager)
    other = bind_chunk_mutations(ServicePrincipal("other", "tenant-a"), engine)
    try:
        with pytest.raises(ScopeDenied):
            ChunkMutationJournal(other, 1).inspect(
                row["mutation_id"], context=context()
            )
    finally:
        other.close()


def test_file_drain_isolated_from_other_file_and_standalone_effects(journal):
    manager, *_ = journal
    complete(intent(file=False), manager, 1)
    assert manager.standalone_count(context=context()) == 1
    row = reserve(intent("file-write"), manager)
    manager.assert_drained(
        file_ref=KnowledgeFileReference(
            knowledge_id=1, file_id="c" * 32, file_version=2
        ),
        context=context(),
    )
    with pytest.raises(Conflict):
        manager.assert_drained(file_ref=intent().file_ref, context=context())
    assert (
        manager.inspect(row["mutation_id"], context=context())["status"] == "reserved"
    )


def test_generation_and_file_versions_have_separate_count_effects(journal):
    manager, *_ = journal
    complete(intent("create"), manager, 1)
    complete(intent("edit", operation="update"), manager, 0)
    complete(intent("delete", operation="delete"), manager, -1)
    assert manager.revision(context=context()) == 3
    assert manager.file_delta(intent().file_ref, "published", context=context()) == 0


@pytest.mark.parametrize(
    "values",
    [
        {"file_ref": None},
        {"generation": None},
        {"chunk_index": None},
        {
            "file_ref": KnowledgeFileReference(
                knowledge_id=2, file_id="b" * 32, file_version=2
            )
        },
    ],
)
def test_contract_rejects_partial_or_foreign_file_binding(values):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChunkMutationIntent.model_validate({**intent().model_dump(), **values})


def test_two_row_completion_rolls_back_on_marker_conflict(journal, monkeypatch):
    from contracts.knowledge_chunk_mutation import STATES

    manager, *_ = journal
    row = reserve(intent(), manager)
    manager.begin(row["mutation_id"], context=context())
    original = manager._patch

    def conflict_on_marker(records, dataset, row, values, ctx, **kwargs):
        if dataset == STATES and isinstance(values, dict) and "epoch" in values:
            raise Conflict()
        return original(records, dataset, row, values, ctx, **kwargs)

    monkeypatch.setattr(manager, "_patch", conflict_on_marker)
    with pytest.raises(Conflict):
        manager.complete(
            row["mutation_id"],
            count_delta=1,
            outcome=WriteOutcome.CONFIRMED,
            context=context(),
        )
    actual = manager.inspect(row["mutation_id"], context=context())
    assert actual["status"] == "writing" and actual["count_delta"] is None


def test_lost_reservation_commit_ack_is_observed_not_replayed(journal, monkeypatch):
    from nexent.storage.errors import OutcomeUnknown
    from sqlalchemy.exc import OperationalError

    manager, _, engine = journal
    connect = engine.connect

    class LostAckTransaction:
        def __init__(self, transaction):
            self.transaction = transaction

        def commit(self):
            self.transaction.commit()
            raise OperationalError("commit", {}, RuntimeError("lost acknowledgement"))

        def __getattr__(self, name):
            return getattr(self.transaction, name)

    class Connection:
        def __init__(self):
            self.wrapped = connect()

        def begin(self):
            return LostAckTransaction(self.wrapped.begin())

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    monkeypatch.setattr(engine, "connect", Connection)
    with pytest.raises(OutcomeUnknown):
        manager.reserve(intent(), context=context())
    monkeypatch.setattr(engine, "connect", connect)
    row, fresh = manager.reserve(intent(), context=context())
    assert not fresh and row["status"] == "reserved"


def test_unknown_writer_end_evidence_cannot_move_backwards(journal):
    manager, *_ = journal
    row = reserve(intent(), manager)
    manager.begin(row["mutation_id"], context=context())
    manager.mark_unknown(
        row["mutation_id"], writer_ended=False, error_code="UNKNOWN", context=context()
    )
    manager.mark_unknown(
        row["mutation_id"], writer_ended=True, error_code="UNKNOWN", context=context()
    )
    with pytest.raises(Conflict):
        manager.mark_unknown(
            row["mutation_id"],
            writer_ended=False,
            error_code="UNKNOWN",
            context=context(),
        )
    with pytest.raises(Conflict):
        manager.assert_drained(context=context())


def test_other_tenant_has_no_access_to_record(journal):
    from nexent.storage.errors import NotFound

    manager, _, engine = journal
    row = reserve(intent(), manager)
    other = bind_chunk_mutations(ServicePrincipal("operator", "tenant-b"), engine)
    try:
        with pytest.raises(NotFound):
            ChunkMutationJournal(other, 1).inspect(
                row["mutation_id"], context=context()
            )
        assert ChunkMutationJournal(other, 1).revision(context=context()) == 0
    finally:
        other.close()


def test_same_tenant_other_kb_does_not_reuse_state(journal):
    manager, records, _ = journal
    reserve(intent(), manager)
    assert ChunkMutationJournal(records, 2).revision(context=context()) == 0
    with pytest.raises(ScopeDenied):
        ChunkMutationJournal(records, 2).reserve(intent(), context=context())


def test_distinct_chunks_can_remain_in_flight_together(journal):
    manager, *_ = journal
    first = reserve(intent(), manager)
    second = reserve(
        intent("second").model_copy(update={"chunk_id": "another", "chunk_index": 4}),
        manager,
    )
    manager.begin(first["mutation_id"], context=context())
    manager.begin(second["mutation_id"], context=context())
    manager.complete(
        first["mutation_id"],
        count_delta=1,
        outcome=WriteOutcome.CONFIRMED,
        context=context(),
    )
    with pytest.raises(Conflict):
        manager.revision(context=context())
    manager.complete(
        second["mutation_id"],
        count_delta=1,
        outcome=WriteOutcome.CONFIRMED,
        context=context(),
    )
    assert manager.revision(context=context()) == 2
    assert manager.file_delta(intent().file_ref, "published", context=context()) == 2


def test_read_only_binding_cannot_mutate(journal):
    manager, _, engine = journal
    row = reserve(intent(), manager)
    readonly = bind_chunk_mutations(
        ServicePrincipal("operator", "tenant-a"), engine, writable=False
    )
    try:
        with pytest.raises(ScopeDenied):
            ChunkMutationJournal(readonly, 1).begin(
                row["mutation_id"], context=context()
            )
    finally:
        readonly.close()


@pytest.mark.parametrize(
    "target,values",
    [
        (
            "change",
            {
                "status": "completed",
                "writer_ended": True,
                "count_delta": 1,
                "commit_epoch": None,
            },
        ),
        ("change", {"file_version": None}),
        ("state", {"active_count": -1}),
    ],
)
def test_database_constraints_reject_partial_effects(journal, target, values):
    from contracts.knowledge_chunk_mutation import CHANGES, STATES
    from nexent.storage.models import FieldPatch, Revision

    manager, records, _ = journal
    row = reserve(intent(), manager)
    dataset, key = (
        (CHANGES, row["mutation_id"])
        if target == "change"
        else (STATES, manager.state_key)
    )
    before = records.get(dataset, key, context=context())
    with pytest.raises(InvalidInput):
        records.patch(
            dataset,
            key,
            FieldPatch(set_values=values),
            expected=Revision(str(before["revision"])),
            context=context(),
        )
    assert records.get(dataset, key, context=context()) == before


@pytest.mark.parametrize(
    "role,system,names",
    [
        (
            "management",
            False,
            {"runtime_knowledge_chunk_changes", "runtime_knowledge_chunk_states"},
        ),
        (
            "runtime",
            True,
            {"runtime_knowledge_chunk_changes", "runtime_knowledge_chunk_states"},
        ),
        ("runtime", False, {"runtime_knowledge_chunk_changes"}),
    ],
)
def test_journal_rejects_untrusted_scope(role, system, names):
    from types import SimpleNamespace

    from nexent.storage.models import StorageScope

    scope = StorageScope(
        role, None if system else "tenant-a", "operator", names, system=system
    )
    with pytest.raises(ScopeDenied):
        ChunkMutationJournal(SimpleNamespace(scope=scope), 1)
