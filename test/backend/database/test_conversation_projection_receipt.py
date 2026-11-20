# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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
