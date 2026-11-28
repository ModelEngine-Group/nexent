# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from contracts.errors.exceptions import AutomationNotFoundError
from management.db.automation import repository
from management.db.automation.models import AgentAutomationProposal


@pytest.fixture
def confirmation_transaction(mocker):
    now = datetime.now(timezone.utc)
    proposal = AgentAutomationProposal(
        status="PENDING", expires_at=now + timedelta(hours=1),
        proposed_task={"title": "Daily report", "_conversation_unit_id": 17},
    )
    session = mocker.Mock()
    session.scalar.return_value = proposal
    mocker.patch.object(repository, "get_db_session", return_value=nullcontext(session))
    mocker.patch.object(repository, "_utcnow", return_value=now)
    return session, proposal, now


TASK = {"tenant_id": "tenant", "conversation_id": 42}
DRAFT = {"proposal_id": 7, "proposed_task": {"title": "Daily report"}}


def test_confirmation_claims_the_owned_proposal_and_writes_receipt_in_the_task_session(
    confirmation_transaction, mocker,
):
    session, proposal, now = confirmation_transaction
    task = {"task_id": 19}

    def create(*args, **kwargs):
        assert proposal.status == "PENDING" and proposal.confirmed_task_id is None
        return task

    create_task = mocker.patch.object(repository, "create_task", side_effect=create)

    assert repository.create_task_from_proposal(TASK, DRAFT, "user") == task

    query = session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert str(query).endswith("FOR UPDATE")
    assert query.params == {
        "proposal_id_1": 7, "conversation_id_1": 42, "tenant_id_1": "tenant",
        "user_id_1": "user", "delete_flag_1": "N",
    }
    create_task.assert_called_once_with(TASK, "user", db_session=session)
    assert (proposal.status, proposal.confirmed_task_id) == ("ACCEPTED", 19)
    assert (proposal.updated_by, proposal.update_time) == ("user", now)


def test_duplicate_confirmation_reuses_the_existing_owned_task(confirmation_transaction, mocker):
    session, proposal, _ = confirmation_transaction
    proposal.status, proposal.confirmed_task_id = "ACCEPTED", 19
    task = {"task_id": 19}
    get_task = mocker.patch.object(repository, "get_task", return_value=task)
    create_task = mocker.patch.object(repository, "create_task")

    assert repository.create_task_from_proposal(TASK, DRAFT, "user") == task

    get_task.assert_called_once_with(19, "tenant", "user", db_session=session)
    create_task.assert_not_called()


@pytest.mark.parametrize("invalid_draft", ["missing", "expired", "deleted_receipt", "edited"])
def test_confirmation_rejects_unavailable_or_edited_drafts(confirmation_transaction, mocker, invalid_draft):
    session, proposal, now = confirmation_transaction
    if invalid_draft == "missing":
        session.scalar.return_value = None
    if invalid_draft == "expired":
        proposal.expires_at = now
    if invalid_draft == "deleted_receipt":
        proposal.status, proposal.confirmed_task_id = "ACCEPTED", 19
    if invalid_draft == "edited":
        proposal.proposed_task = {"title": "Edited after review"}
    original_status, original_receipt = proposal.status, proposal.confirmed_task_id
    get_task = mocker.patch.object(repository, "get_task", return_value=None)
    create_task = mocker.patch.object(repository, "create_task")

    message = "proposal changed" if invalid_draft == "edited" else "no longer pending"
    with pytest.raises(AutomationNotFoundError, match=message):
        repository.create_task_from_proposal(TASK, DRAFT, "user")

    if invalid_draft == "deleted_receipt":
        get_task.assert_called_once_with(19, "tenant", "user", db_session=session)
    else:
        get_task.assert_not_called()
    create_task.assert_not_called()
    assert (proposal.status, proposal.confirmed_task_id) == (original_status, original_receipt)


def test_task_insert_failure_leaves_the_proposal_pending(confirmation_transaction, mocker):
    _, proposal, _ = confirmation_transaction
    mocker.patch.object(repository, "create_task", side_effect=RuntimeError("task write failed"))

    with pytest.raises(RuntimeError, match="task write failed"):
        repository.create_task_from_proposal(TASK, DRAFT, "user")

    assert (proposal.status, proposal.confirmed_task_id) == ("PENDING", None)
