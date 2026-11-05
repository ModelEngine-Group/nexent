# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Conversation branching copies configuration and the selected turn range."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from management.db.conversation import repository as db


NEW_CONVERSATION_ROW = SimpleNamespace(
    conversation_id=42,
    conversation_title="Trip planning（分支）",
    agent_id=5,
    chat_mode="execution",
    knowledge_scope={"kb": True},
    runtime_metadata={},
    runtime_metadata_version=1,
    workbench_config=None,
    workbench_config_version=0,
    create_time=1700000000000,
    update_time=1700000000000,
)


def _conversation_row(**overrides):
    row = SimpleNamespace(
        conversation_id=7,
        conversation_title="Trip planning",
        title_version=3,
        last_activity_time=None,
        agent_id=5,
        chat_mode="execution",
        knowledge_scope={"kb": True},
        runtime_metadata={"model": "gpt"},
        runtime_metadata_version=4,
        workbench_config=None,
        workbench_pinned_at=None,
        workbench_config_version=0,
        create_time=None,
        update_time=None,
        created_by="owner",
        updated_by="owner",
        delete_flag="N",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _message(message_id, message_index, role, content, **overrides):
    row = SimpleNamespace(
        message_id=message_id,
        conversation_id=7,
        message_index=message_index,
        message_role=role,
        message_source="CHAT",
        message_content=content,
        minio_files=None,
        opinion_flag=None,
        status="completed",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _unit(unit_id, message_id, **overrides):
    row = SimpleNamespace(
        unit_id=unit_id,
        message_id=message_id,
        conversation_id=7,
        unit_index=0,
        unit_type="answer",
        unit_content="unit body",
        unit_status="completed",
        tool_call_id=None,
        invocation_id=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _search(search_id, message_id, unit_id=None, **overrides):
    row = SimpleNamespace(
        search_id=search_id,
        unit_id=unit_id,
        message_id=message_id,
        conversation_id=7,
        source_type="url",
        source_title="doc",
        source_location="https://example.com",
        source_content="text",
        score_overall=None,
        score_accuracy=None,
        score_semantic=None,
        retrieval_highlight_terms=None,
        aidp_metadata=None,
        aidp_source_reference=None,
        published_date=None,
        cite_index=None,
        search_type="web_search",
        tool_sign=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _image(image_id, message_id, **overrides):
    row = SimpleNamespace(
        image_id=image_id,
        conversation_id=7,
        message_id=message_id,
        unit_id=None,
        image_url="https://example.com/a.png",
        cite_index=None,
        search_type="web_search",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _scalars_result(first=None, all_rows=None):
    result = MagicMock()
    result.first.return_value = first
    result.all.return_value = all_rows or []
    return result


def _three_turn_rows():
    """Two settled turns, a regenerated answer on turn two, and a third turn."""
    return [
        _message(11, 0, "user", "Q1"),
        _message(12, 1, "assistant", "A1"),
        _message(13, 2, "user", "Q2"),
        _message(14, 3, "assistant", "A2-old"),
        _message(15, 3, "assistant", "A2-new", opinion_flag="Y"),
        _message(16, 4, "user", "Q3"),
        _message(17, 5, "assistant", "A3"),
    ]


def sql(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def params(statement):
    return statement.compile().params


class _ExecuteRecorder:
    """Route executed statements by table and return per-table results."""

    def __init__(self, new_conversation_row=NEW_CONVERSATION_ROW):
        self.statements = []
        self.new_conversation_row = new_conversation_row
        self.next_ids = {"message": 1000, "unit": 2000}
        self.results = {
            "conversation_record_t": self._conversation_result,
            "conversation_message_t": self._message_result,
            "conversation_message_unit_t": self._unit_result,
        }

    def _conversation_result(self, _statement):
        result = MagicMock()
        result.fetchone.return_value = self.new_conversation_row
        return result

    def _message_result(self, _statement):
        self.next_ids["message"] += 1
        result = MagicMock()
        result.scalar_one.return_value = self.next_ids["message"]
        return result

    def _unit_result(self, _statement):
        self.next_ids["unit"] += 1
        result = MagicMock()
        result.scalar_one.return_value = self.next_ids["unit"]
        return result

    def __call__(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        text = str(statement.compile(dialect=postgresql.dialect()))
        for table, factory in self.results.items():
            if text.startswith(f"INSERT INTO nexent.{table}"):
                return factory(statement)
        return MagicMock()


@pytest.fixture
def session(monkeypatch):
    value = MagicMock()
    value.scalar.return_value = 1

    @contextmanager
    def sessions():
        yield value

    monkeypatch.setattr(db, "get_db_session", sessions)
    return value


_UNSET = object()


def _wire(session, rows, *, conversation=_UNSET, units=None, searches=None, images=None):
    """Queue the scalars results in the order branch_conversation reads them."""
    if conversation is _UNSET:
        conversation = _conversation_row()
    session.scalars.side_effect = [
        _scalars_result(first=conversation),
        _scalars_result(all_rows=rows),
        _scalars_result(all_rows=units or []),
        _scalars_result(all_rows=searches or []),
        _scalars_result(all_rows=images or []),
    ]


def test_branch_copies_turn_range_and_remaps_children(session):
    rows = _three_turn_rows()
    units = [
        _unit(21, 15, unit_index=1, tool_call_id="t-1"),
    ]
    searches = [
        _search(31, 12),
        _search(33, 15, unit_id=21),
    ]
    images = [
        _image(41, 15),
    ]
    _wire(session, rows, units=units, searches=searches, images=images)
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    result = db.branch_conversation(7, 2, user_id="owner")

    assert result["conversation_id"] == 42
    assert result["conversation_title"] == "Trip planning（分支）"
    assert result["branched_message_count"] == 4

    # Child queries only fetch rows of the copied messages.
    units_filter = sql(session.scalars.call_args_list[2].args[0])
    assert "message_id IN (11, 12, 13, 15)" in units_filter
    searches_filter = sql(session.scalars.call_args_list[3].args[0])
    assert "message_id IN (11, 12, 13, 15)" in searches_filter
    images_filter = sql(session.scalars.call_args_list[4].args[0])
    assert "message_id IN (11, 12, 13, 15)" in images_filter

    inserted = {}
    for statement in recorder.statements:
        text = str(statement.compile(dialect=postgresql.dialect()))
        if text.startswith("INSERT INTO nexent."):
            table = text.split("nexent.")[1].split(" ")[0]
            inserted.setdefault(table, []).append(params(statement))

    # Only the four active rows of turns one and two are copied.
    assert [row["message_content"] for row in inserted["conversation_message_t"]] == [
        "Q1",
        "A1",
        "Q2",
        "A2-new",
    ]
    # User feedback is intentionally not carried over.
    assert all("opinion_flag" not in row for row in inserted["conversation_message_t"])
    assert all(row["delete_flag"] == "N" for row in inserted["conversation_message_t"])
    assert all(row["created_by"] == "owner" for row in inserted["conversation_message_t"])

    # Conversation configuration is cloned with fresh versions.
    conversation_row = inserted["conversation_record_t"][0]
    assert conversation_row["conversation_title"] == "Trip planning（分支）"
    assert conversation_row["agent_id"] == 5
    assert conversation_row["chat_mode"] == "execution"
    assert conversation_row["knowledge_scope"] == {"kb": True}
    assert conversation_row["runtime_metadata"] == {"model": "gpt"}
    assert conversation_row["runtime_metadata_version"] == 1

    # Units, searches and images follow only the copied messages, with
    # unit_id references remapped to the inserted unit rows.
    assert [row["unit_content"] for row in inserted["conversation_message_unit_t"]] == ["unit body"]
    assert len(inserted["conversation_source_search_t"]) == 2
    remapped_unit = inserted["conversation_source_search_t"][1]
    assert remapped_unit["source_title"] == "doc"
    assert remapped_unit["unit_id"] == 2001
    assert len(inserted["conversation_source_image_t"]) == 1
    assert inserted["conversation_source_image_t"][0]["message_id"] == 1004


def _conversation_insert(recorder):
    """Return the single conversation INSERT statement executed by a branch."""
    statements = [
        statement
        for statement in recorder.statements
        if str(statement.compile(dialect=postgresql.dialect())).startswith(
            "INSERT INTO nexent.conversation_record_t"
        )
    ]
    assert len(statements) == 1
    return statements[0]


def test_branch_of_agent_chat_leaves_workbench_columns_unbound(session):
    """An agent-chat branch must not bind JSONB columns with Python None.

    SQLAlchemy serializes a None bound to a JSONB column as the JSON value
    null instead of SQL NULL, and agent-chat history filters on
    "workbench_config IS NULL": binding the absent declaration would hide
    the branched conversation from every agent-chat list as soon as it stops
    being the active thread.
    """
    _wire(
        session,
        _three_turn_rows(),
        conversation=_conversation_row(
            workbench_config=None, knowledge_scope=None
        ),
    )
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    result = db.branch_conversation(7, 1, user_id="owner")

    assert result["workbench_config"] is None
    # The RETURNING clause references workbench_config regardless, so assert
    # on the VALUES binds: an unbound column falls back to SQL NULL while a
    # bound None would be serialized by SQLAlchemy as the JSON value null.
    inserted = params(_conversation_insert(recorder))
    assert "workbench_config" not in inserted
    assert "workbench_config_version" not in inserted
    assert "knowledge_scope" not in inserted
    assert inserted["runtime_metadata"] == {"model": "gpt"}
    assert inserted["runtime_metadata_version"] == 1


def test_branch_copies_workbench_declaration_when_present(session):
    """A Workbench branch keeps its declaration and restarts the version."""
    workbench = {
        "schema_version": 3,
        "mode": "single_agent_chat",
        "agent_mounts": [{"agent_id": 5, "version_no": 3}],
    }
    new_row = SimpleNamespace(
        conversation_id=42,
        conversation_title="Trip planning（分支）",
        agent_id=5,
        chat_mode="execution",
        knowledge_scope={"kb": True},
        runtime_metadata={},
        runtime_metadata_version=1,
        workbench_config=workbench,
        workbench_config_version=1,
        create_time=1700000000000,
        update_time=1700000000000,
    )
    _wire(
        session,
        _three_turn_rows(),
        conversation=_conversation_row(
            workbench_config=workbench, workbench_config_version=5
        ),
    )
    recorder = _ExecuteRecorder(new_conversation_row=new_row)
    session.execute.side_effect = recorder

    result = db.branch_conversation(7, 1, user_id="owner")

    assert result["workbench_config"] == workbench
    inserted = params(_conversation_insert(recorder))
    assert inserted["workbench_config"] == workbench
    # The copy is independent of the source row's declaration.
    assert inserted["workbench_config"] is not workbench
    assert inserted["workbench_config_version"] == 1


def test_branch_last_turn_copies_everything(session):
    _wire(session, _three_turn_rows())
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    result = db.branch_conversation(7, 3, user_id="owner")

    assert result["branched_message_count"] == 6
    inserted_rows = [
        params(statement)
        for statement in recorder.statements
        if str(statement.compile(dialect=postgresql.dialect())).startswith(
            "INSERT INTO nexent.conversation_message_t"
        )
    ]
    assert [row["message_content"] for row in inserted_rows] == [
        "Q1",
        "A1",
        "Q2",
        "A2-new",
        "Q3",
        "A3",
    ]


def test_branch_takes_user_quota_lock_before_row_locks(session):
    _wire(session, _three_turn_rows())
    session.execute.side_effect = _ExecuteRecorder()

    db.branch_conversation(7, 1, user_id="owner")

    quota_lock = sql(session.execute.call_args_list[0].args[0])
    assert "pg_advisory_xact_lock" in quota_lock
    conversation_lock = sql(session.scalars.call_args_list[0].args[0])
    assert "conversation_record_t" in conversation_lock and "FOR UPDATE" in conversation_lock
    assert "conversation_id = 7" in conversation_lock
    assert "created_by = 'owner'" in conversation_lock and "delete_flag = 'N'" in conversation_lock


def test_branch_returns_none_without_inserts_for_missing_conversation(session):
    _wire(session, [], conversation=None)
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    assert db.branch_conversation(7, 1, user_id="owner") is None
    assert all(
        not str(statement.compile(dialect=postgresql.dialect())).startswith("INSERT INTO nexent.")
        for statement in recorder.statements
    )


@pytest.mark.parametrize("turn_index", [0, -1])
def test_branch_rejects_non_positive_turn_index(session, turn_index):
    with pytest.raises(ValueError, match="1-based turn number"):
        db.branch_conversation(7, turn_index, user_id="owner")


def test_branch_rejects_turn_index_beyond_available_turns(session):
    _wire(session, _three_turn_rows())

    with pytest.raises(ValueError, match="exceeds the 3 turns"):
        db.branch_conversation(7, 4, user_id="owner")


def test_branch_title_never_stacks_suffixes_and_respects_length(session):
    # Branching a branch keeps a single suffix.
    assert db._build_branch_title("Trip planning（分支）") == "Trip planning（分支）"
    # Over-long titles are truncated so the result fits the 100-char column.
    long_title = "x" * 120
    assert len(db._build_branch_title(long_title)) == 100
    assert db._build_branch_title(long_title).endswith("（分支）")
    assert db._build_branch_title(None) == "（分支）"


def test_branch_without_answer_stops_at_user_row(session):
    rows = [
        _message(11, 0, "user", "Q1"),
        _message(12, 1, "assistant", "A1"),
        _message(13, 2, "user", "Q2"),
    ]
    _wire(session, rows)
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    result = db.branch_conversation(7, 2, user_id="owner")

    assert result["branched_message_count"] == 3
    inserted_rows = [
        params(statement)
        for statement in recorder.statements
        if str(statement.compile(dialect=postgresql.dialect())).startswith(
            "INSERT INTO nexent.conversation_message_t"
        )
    ]
    assert [row["message_content"] for row in inserted_rows] == ["Q1", "A1", "Q2"]
