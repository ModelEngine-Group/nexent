# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Branch boundaries must retain the answer version selected by the user."""

from types import SimpleNamespace

import pytest

from contracts.conversation import BranchConversationRequest
from management.db.conversation.repository import _select_branch_turn_rows


def row(message_id, index, role):
    return SimpleNamespace(message_id=message_id, message_index=index, message_role=role)


@pytest.fixture(params=[1, 2])
def regenerated_rows(request):
    return [
        row(11, 0, "user"),
        row(12, 1, "assistant"),
        row(13, request.param, "assistant"),
        row(14, 3, "user"),
        row(15, 4, "assistant"),
    ]


@pytest.mark.parametrize("message_id", [12, 13])
def test_exact_answer_id_selects_either_version(regenerated_rows, message_id):
    selected = _select_branch_turn_rows(regenerated_rows, 1, source_message_id=message_id)
    assert [item.message_id for item in selected] == [11, message_id]


@pytest.mark.parametrize("answer_index,message_id", [(1, 12), (2, 13)])
def test_live_answer_ordinal_selects_either_version(regenerated_rows, answer_index, message_id):
    selected = _select_branch_turn_rows(regenerated_rows, 1, answer_index=answer_index)
    assert [item.message_id for item in selected] == [11, message_id]


def test_exact_id_takes_precedence_over_runtime_ordinal(regenerated_rows):
    selected = _select_branch_turn_rows(regenerated_rows, 1, source_message_id=13, answer_index=1)
    assert [item.message_id for item in selected] == [11, 13]


def test_legacy_request_and_earlier_turns_keep_latest_answer(regenerated_rows):
    assert [item.message_id for item in _select_branch_turn_rows(regenerated_rows, 1)] == [11, 13]
    assert [item.message_id for item in _select_branch_turn_rows(regenerated_rows, 2)] == [11, 13, 14, 15]


@pytest.mark.parametrize("target", [
    {"source_message_id": 999},
    {"source_message_id": 11},
    {"source_message_id": 15},
    {"answer_index": 3},
    {"answer_index": 0},
])
def test_invalid_or_other_turn_answer_is_rejected(regenerated_rows, target):
    with pytest.raises(ValueError):
        _select_branch_turn_rows(regenerated_rows, 1, **target)


@pytest.mark.parametrize("field", ["source_message_id", "answer_index"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_request_rejects_invalid_answer_identifiers(field, value):
    with pytest.raises(ValueError):
        BranchConversationRequest(conversation_id=7, turn_index=1, **{field: value})


def test_refresh_duplicate_user_does_not_create_an_extra_turn():
    rows = [row(11, 0, "user"), row(12, 0, "user"), row(13, 1, "assistant"),
            row(14, 2, "user"), row(15, 3, "assistant")]
    selected = _select_branch_turn_rows(rows, 2, source_message_id=15)
    assert [item.message_id for item in selected] == [12, 13, 14, 15]


def test_unanswered_boundary_cannot_borrow_the_next_turn_answer():
    rows = [row(11, 0, "user"), row(12, 1, "user"), row(13, 2, "assistant")]
    assert [item.message_id for item in _select_branch_turn_rows(rows, 1)] == [11]
    with pytest.raises(ValueError):
        _select_branch_turn_rows(rows, 1, source_message_id=13)


@pytest.mark.parametrize("selected_id", [14, 15])
def test_copy_and_child_queries_use_only_selected_answer(monkeypatch, selected_id):
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from management.db.conversation import repository as db
    from test.backend.database.test_conversation_branch_db import (
        _ExecuteRecorder, _three_turn_rows, _wire, params, sql,
    )

    session = MagicMock()
    session.scalar.return_value = 1

    @contextmanager
    def sessions():
        yield session

    monkeypatch.setattr(db, "get_db_session", sessions)
    _wire(session, _three_turn_rows())
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder
    result = db.branch_conversation(7, 2, user_id="owner", source_message_id=selected_id)
    assert result["branched_message_count"] == 4
    messages = [params(stmt) for stmt in recorder.statements
                if getattr(getattr(stmt, "table", None), "name", None) == "conversation_message_t"]
    assert [item["message_content"] for item in messages] == ["Q1", "A1", "Q2", "A2-old" if selected_id == 14 else "A2-new"]
    for call in session.scalars.call_args_list[3:6]:
        assert f"message_id IN (11, 12, 13, {selected_id})" in sql(call.args[0])


def test_invalid_answer_is_rejected_before_any_insert(monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    from management.db.conversation import repository as db
    from test.backend.database.test_conversation_branch_db import _three_turn_rows, _wire

    session = MagicMock()
    session.scalar.return_value = 1

    @contextmanager
    def sessions():
        yield session

    monkeypatch.setattr(db, "get_db_session", sessions)
    _wire(session, _three_turn_rows())
    with pytest.raises(ValueError):
        db.branch_conversation(7, 2, user_id="owner", source_message_id=999)
    assert not any(getattr(call.args[0], "is_insert", False) for call in session.execute.call_args_list)
