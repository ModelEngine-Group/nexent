# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from management.db.conversation import projection_receipt, repository

RUN_ID = "a" * 32


def project(**changes):
    values = {
        "message_id": 17, "conversation_id": 4, "message_content": "answer", "terminal_status": "completed",
        "message_units": [{"unit_index": 1, "unit_type": "final_answer", "unit_content": "answer"}],
        "search_records": [], "image_urls": [], "skill_files": [], "automation_proposals": [],
        "user_id": "actor", "tenant_id": "tenant-a", "projection_run_id": RUN_ID,
    }
    return repository.persist_assistant_run_batch(**(values | changes))


@pytest.fixture
def projection_db(mocker):
    session = MagicMock()
    session.scalar.return_value = 4
    parent = SimpleNamespace(status="streaming", minio_files=None)
    parent_query = MagicMock()
    parent_query.scalar_one_or_none.return_value = parent
    inserted_units = MagicMock()
    inserted_units.all.return_value = [SimpleNamespace(unit_index=1, unit_id=101)]
    session.execute.side_effect = [parent_query, inserted_units, MagicMock()]
    mocker.patch.object(repository, "get_db_session", return_value=nullcontext(session))
    membership = mocker.patch("infrastructure.rdb.conversation_state.tenant_membership_matches", return_value=True)
    receipts = mocker.patch.object(projection_receipt, "find_projection_receipts", return_value=[])
    return session, parent, membership, receipts


def test_assistant_projection_replay_returns_original_ids_without_writes(projection_db):
    session, parent, membership, receipts = projection_db
    assert project() == {1: 101}
    membership.assert_called_once_with(session, "actor", "tenant-a")
    assert parent.status == "completed"
    receipt = session.add.call_args.args[0]
    assert (receipt.run_id, receipt.message_id, receipt.tenant_id) == (RUN_ID, 17, "tenant-a")
    assert receipt.unit_ids == {"1": 101}

    receipts.return_value = [receipt]
    session.reset_mock()
    session.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=parent))]
    assert project() == {1: 101}
    session.add.assert_not_called()
    assert session.execute.call_count == 1


def test_native_thinking_groups_at_write_without_changing_receipt_input(projection_db, mocker):
    session, parent, _, receipts = projection_db
    digest = mocker.patch.object(projection_receipt, "projection_payload_digest",
                                 wraps=projection_receipt.projection_payload_digest)

    def native(index, content, *, step="one", block="body", invocation=None, attempt="attempt", kind="model_output"):
        envelope = {"type": kind, "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
                    "turn_id": "turn", "sequence": index, "step_id": step, "block_id": block,
                    "invocation_id": invocation, "attempt_id": attempt, "content": content}
        return {"unit_index": index, "type": kind, "unit_type": kind, "unit_content": json.dumps(envelope),
                "invocation_id": invocation}

    raw = [native(1, "一"), native(2, "deep", kind="model_output_deep_thinking"),
           native(3, ". Child", invocation="child"), native(4, "二"),
           native(5, "deep end", kind="model_output_deep_thinking"), native(6, "do not join", step="two"),
           native(7, "other attempt", attempt="different"),
           {"unit_index": 8, "unit_type": "human_interaction", "unit_content": "form"}]

    assert project(message_units=raw) == {1: 101}
    rows = session.execute.call_args_list[1].args[1]
    assert [(row["unit_index"], row["unit_type"]) for row in rows] == [
        (1, "model_output_thinking"), (2, "model_output_deep_thinking"), (3, "model_output_thinking"),
        (6, "model_output_thinking"), (7, "model_output_thinking"), (8, "human_interaction"),
    ]
    payloads = [json.loads(row["unit_content"]) for row in rows[:-1]]
    assert [payload["content"] for payload in payloads] == ["一二", "deepdeep end", ". Child", "do not join", "other attempt"]
    assert payloads[0] == (json.loads(raw[0]["unit_content"]) | {"type": "model_output_thinking", "content": "一二"})
    assert rows[-1]["unit_content"] == "form"
    assert digest.call_args.args[0]["message_units"] == raw
    assert raw[0]["unit_type"] == "model_output" and raw[3]["unit_type"] == "model_output"

    receipt = session.add.call_args.args[0]
    receipts.return_value = [receipt]
    for unit_ids in ({"1": 101}, {"1": 101, "4": 104}):
        receipt.unit_ids = unit_ids
        session.reset_mock()
        session.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=parent))]
        assert project(message_units=raw) == {int(index): unit_id for index, unit_id in unit_ids.items()}
        session.add.assert_not_called()
        assert session.execute.call_count == 1


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("legacy model text", id="legacy-plain-text"),
        pytest.param('{"type":"model_output","content":"legacy model text"}', id="legacy-envelope"),
        pytest.param({"agent_core": "smolagents"}, id="other-core"),
        pytest.param({"turn_id": None}, id="no-turn"),
        pytest.param({"step_id": None, "block_id": None}, id="no-step-or-block"),
        pytest.param({"attempt_id": 42}, id="invalid-attempt"),
    ],
)
def test_projection_keeps_unmergeable_model_output_units(projection_db, content):
    session, _, _, _ = projection_db
    envelope = {
        "type": "model_output", "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
        "turn_id": "turn", "step_id": "step", "block_id": "body", "content": "fragment",
    }
    original = content if isinstance(content, str) else envelope | content
    units = [
        {"unit_index": index, "unit_type": "model_output", "unit_content": original}
        for index in (1, 2)
    ]
    units.append({"unit_index": 3, "unit_type": "model_output", "unit_content": envelope})

    project(message_units=units)

    rows = session.execute.call_args_list[1].args[1]
    assert [(row["unit_index"], row["unit_type"]) for row in rows] == [
        (1, "model_output"), (2, "model_output"), (3, "model_output_thinking"),
    ]
    for row in rows[:2]:
        persisted = row["unit_content"]
        assert (persisted if isinstance(original, str) else json.loads(persisted)) == original
    assert json.loads(rows[2]["unit_content"]) == (envelope | {"type": "model_output_thinking"})


@pytest.mark.parametrize("change", [{"message_content": "changed"}, {"projection_run_id": "b" * 32}, {"message_id": 18}])
def test_assistant_projection_rejects_conflicting_replay(projection_db, change):
    session, parent, _, receipts = projection_db
    project()
    receipts.return_value = [session.add.call_args.args[0]]
    session.reset_mock()
    session.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=parent))]

    with pytest.raises(ValueError, match="conflicts with a committed run"):
        project(**change)

    session.add.assert_not_called()
    assert session.execute.call_count == 1


def test_assistant_projection_rejects_cross_tenant_before_receipt_read(projection_db):
    session, _, membership, receipts = projection_db
    membership.return_value = False
    with pytest.raises(ValueError, match="not accessible"):
        project()
    receipts.assert_not_called()
    session.add.assert_not_called()


def test_projection_failure_fallback_only_updates_owned_streaming_message(projection_db):
    from sqlalchemy.dialects import postgresql

    session, _, _, _ = projection_db
    repository.fail_unfinished_assistant_projection(17, "failed", "actor", tenant_id="tenant-a")
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    sql = str(compiled)
    assert "conversation_message_t.status = 'streaming'" in sql
    assert "conversation_message_t.created_by = 'actor'" in sql
    assert "conversation_message_t.message_role = 'assistant'" in sql
