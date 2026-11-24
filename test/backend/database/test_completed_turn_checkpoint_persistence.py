# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""WT-003/004: project, save and reload whole-turn checkpoints atomically."""

import json
from contextlib import nullcontext

import pytest
from contracts.agentos import PreparedAgentRun
from management.db.conversation import repository
from management.db.conversation.projection_receipt import ConversationProjectionReceipt
from management.services.agent.preparation.evaluation_snapshot import _prepare_conversation_history
from management.services.agent.prepared_projection import _collect_checkpoint
from sqlalchemy import MetaData, select

from infrastructure.rdb.conversation_record import ConversationMessage, ConversationMessageUnit
from test.backend.database.test_prepared_saved_user import database as database
from test.backend.database.test_prepared_turn_resume import receipt_table as receipt_table


def proposal(**changes):
    return {"coverage_scope": "current_completed_turn", "summary": {"markdown": "WHOLE_TURN"},
            "history_tail_message_id": 61, "previous_summary_unit_id": 1,
            "trigger": "completed_turn", **changes}


@pytest.fixture
def history_db(database, receipt_table, mocker):
    with database.sessions() as session:
        metadata = MetaData()
        ConversationMessageUnit.__table__.to_metadata(metadata, schema=None)
        metadata.create_all(session.get_bind())
        session.get(ConversationMessage, 23).minio_files = None
        session.add_all([
            ConversationMessage(message_id=61, conversation_id=42, message_index=1,
                message_role="assistant", message_content="HISTORY_RAW" * 10000, status="completed",
                created_by="actor", updated_by="actor", delete_flag="N"),
            ConversationMessage(message_id=62, conversation_id=42, message_index=2,
                message_role="user", message_content="CURRENT_TASK", status="completed",
                created_by="actor", updated_by="actor", delete_flag="N"),
            ConversationMessage(message_id=63, conversation_id=42, message_index=3,
                message_role="assistant", message_content="", status="streaming", streaming_owner="management",
                created_by="actor", updated_by="actor", delete_flag="N"),
            ConversationMessageUnit(unit_id=1, message_id=61, conversation_id=42, unit_index=0,
                unit_type="history_summary", unit_status="completed", delete_flag="N", created_by="actor",
                unit_content=json.dumps({"summary": {"markdown": "OLD_SUMMARY"}, "covered_through_message_id": 61})),
        ])
    mocker.patch.object(repository, "get_db_session",
        side_effect=lambda session=None: nullcontext(session) if session is not None else database.sessions())
    mocker.patch.object(repository, "_get_user_tenant", return_value={"tenant_id": "tenant"})
    mocker.patch("infrastructure.rdb.conversation_state.tenant_membership_matches",
        side_effect=lambda session, user, tenant: (user, tenant) == ("actor", "tenant"))
    mocker.patch.object(repository, "_touch_conversation_activity")
    return database.sessions


def project(checkpoint=None, **changes):
    return repository.persist_assistant_run_batch(**{
        "message_id": 63, "conversation_id": 42, "message_content": "CURRENT_RAW" * 10000,
        "terminal_status": "completed", "message_units": [], "search_records": [], "image_urls": [],
        "skill_files": [], "automation_proposals": [], "user_id": "actor", "tenant_id": "tenant",
        "projection_run_id": "a" * 32, "history_checkpoints": [checkpoint or proposal()], **changes})


def checkpoints(sessions):
    with sessions() as session:
        return list(session.execute(select(ConversationMessageUnit.message_id, ConversationMessageUnit.unit_content)
            .where(ConversationMessageUnit.unit_type == "history_summary")
            .order_by(ConversationMessageUnit.unit_id)))


def prepared_bytes(history):
    prepared = PreparedAgentRun.model_validate({
        "mode": "nexent", "conversation_id": 42, "run_id": "b" * 32,
        "resource": {"agent_id": 7, "version_no": 3, "name": "test", "description": "", "prompt_templates": {}},
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
        "input": {"query": "NEXT_TASK"},
        "historical_context": _prepare_conversation_history(history, "actor", "tenant"),
    })
    return prepared.model_dump_json().encode()


def test_completed_projection_saves_current_boundary_and_replay_is_idempotent(history_db, mocker):
    real_save = repository.save_history_summary

    def save(*args, **kwargs):
        parent = kwargs["db_session"].get(ConversationMessage, 63)
        assert parent.status == "completed"
        return real_save(*args, **kwargs)

    save_spy = mocker.patch.object(repository, "save_history_summary", side_effect=save)
    assert project() == {}
    rows = checkpoints(history_db)
    assert len(rows) == 2 and rows[-1].message_id == 63
    assert json.loads(rows[-1].unit_content)["covered_through_message_id"] == 63
    assert project() == {}
    assert save_spy.call_count == 1
    assert len(checkpoints(history_db)) == 2
    with pytest.raises(ValueError):
        project(message_content="late conflicting result")
    assert len(checkpoints(history_db)) == 2


def test_next_prepared_contains_summary_suffix_and_preserves_originals(history_db):
    # Baseline represents the same completed round without its checkpoint.
    with history_db() as session:
        parent = session.get(ConversationMessage, 63)
        parent.status, parent.message_content = "completed", "CURRENT_RAW" * 10000
    before = repository.get_historical_context(42, None, "actor", "tenant", before_message_index=4)
    before_wire = prepared_bytes(before)
    with history_db() as session:
        session.get(ConversationMessage, 63).status = "streaming"
    project()
    with history_db() as session:
        session.add_all([
            ConversationMessage(message_id=64, conversation_id=42, message_index=4,
                message_role="user", message_content="UNCOVERED_USER", status="completed",
                created_by="actor", updated_by="actor", delete_flag="N"),
            ConversationMessage(message_id=65, conversation_id=42, message_index=5,
                message_role="assistant", message_content="UNCOVERED_ANSWER", status="completed",
                created_by="actor", updated_by="actor", delete_flag="N"),
        ])
    after = repository.get_historical_context(42, None, "actor", "tenant", before_message_index=6)
    after_wire = prepared_bytes(after)
    assert after["history_summary"]["covered_through_message_id"] == 63
    assert [turn["assistant_message_id"] for turn in after["conversation_turns"]] == [65]
    assert len(after_wire) < len(before_wire) // 10
    assert b"WHOLE_TURN" in after_wire and b"UNCOVERED_ANSWER" in after_wire and b"CURRENT_RAW" not in after_wire
    with history_db() as session:
        assert session.get(ConversationMessage, 63).message_content == "CURRENT_RAW" * 10000
        assert session.get(ConversationMessage, 61).message_content == "HISTORY_RAW" * 10000
    assert repository.get_historical_context(42, None, "actor", "foreign", before_message_index=6) is None


@pytest.mark.parametrize("change", [
    {"terminal_status": "failed"}, {"terminal_status": "stopped"},
    {"message_units": [{"unit_index": 0, "unit_type": "human_interaction", "unit_content": "waiting"}]},
])
def test_non_completed_turn_never_advances_checkpoint(history_db, change):
    project(**change)
    assert len(checkpoints(history_db)) == 1


@pytest.mark.parametrize("change", [
    {"history_tail_message_id": 60}, {"history_tail_message_id": None},
    {"previous_summary_unit_id": None}, {"previous_summary_unit_id": 999},
])
def test_stale_fork_or_checkpoint_cannot_claim_current_turn(history_db, change):
    project(proposal(**change))
    assert len(checkpoints(history_db)) == 1


def test_transaction_failure_rolls_back_status_checkpoint_and_receipt(history_db, mocker):
    mocker.patch.object(repository, "_touch_conversation_activity", side_effect=ValueError("commit rejected"))
    with pytest.raises(ValueError, match="commit rejected"):
        project()
    assert len(checkpoints(history_db)) == 1
    with history_db() as session:
        assert session.get(ConversationMessage, 63).status == "streaming"
        assert list(session.scalars(select(ConversationProjectionReceipt))) == []


def test_projection_preserves_old_and_current_candidate_contracts():
    collected = []
    _collect_checkpoint(collected, {"status": "accepted", "persist_status": "not_configured", **proposal()})
    _collect_checkpoint(collected, {"status": "accepted", "persist_status": "not_configured",
        "summary": {"markdown": "old"}, "covered_through_message_id": 61})
    assert collected == [proposal(), {"summary": {"markdown": "old"}, "covered_through_message_id": 61}]


def test_legacy_current_boundary_is_saved_only_after_parent_completion(history_db):
    project({"summary": {"markdown": "LEGACY_CURRENT"}, "covered_through_message_id": 63,
             "previous_summary_unit_id": 1})
    assert len(checkpoints(history_db)) == 2
