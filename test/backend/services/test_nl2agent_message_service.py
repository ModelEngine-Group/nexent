"""Tests for atomic structured NL2AGENT message finalization."""

from contextlib import contextmanager

import pytest

from consts.exceptions import Nl2AgentValidationError, Nl2AgentWorkflowConflictError
from services import nl2agent_message_service as service


@contextmanager
def _transaction():
    yield object()


def _snapshot(revision: int = 18):
    return {
        "workflow_revision": revision,
        "workflow_state": {
            "schema_version": 2,
            "revision": revision,
            "conversation_id": 77,
        },
    }


def test_finalize_message_persists_envelope_display_text_and_revision(monkeypatch):
    persisted = {}
    monkeypatch.setattr(service, "get_db_session", _transaction)
    monkeypatch.setattr(
        service,
        "get_nl2agent_session_snapshot_by_identity",
        lambda identity, db_session: _snapshot(),
    )

    def update_workflow(**kwargs):
        persisted["workflow_state"] = kwargs["workflow_state"]
        return True

    def create_message(**kwargs):
        persisted["message"] = kwargs
        return {"message_id": 901, "unit_ids": [902]}

    monkeypatch.setattr(
        service, "update_nl2agent_workflow_state_by_identity", update_workflow
    )
    monkeypatch.setattr(service, "create_nl2agent_assistant_message", create_message)

    result = service.finalize_nl2agent_message(
        tenant_id="tenant-a",
        user_id="user-a",
        runner_agent_id=9,
        draft_agent_id=54,
        conversation_id=77,
        message_index=3,
        expected_revision=18,
        assistant_answer=(
            'Choose a model.\n\n```nl2agent-model-selection\n{"agent_id":54}\n```'
        ),
    )

    assert persisted["workflow_state"]["revision"] == 19
    assert persisted["message"]["display_text"] == "Choose a model."
    assert persisted["message"]["envelope"] == {
        "schema_version": 1,
        "draft_agent_id": 54,
        "workflow_revision": 19,
        "cards": [
            {
                "card_type": "model_selection",
                "card_key": "model_selection",
                "payload": {"agent_id": 54},
            }
        ],
    }
    assert result["workflow_revision"] == 19


def test_finalize_message_rejects_stale_revision_before_writes(monkeypatch):
    monkeypatch.setattr(service, "get_db_session", _transaction)
    monkeypatch.setattr(
        service,
        "get_nl2agent_session_snapshot_by_identity",
        lambda identity, db_session: _snapshot(revision=19),
    )
    monkeypatch.setattr(
        service,
        "create_nl2agent_assistant_message",
        lambda **kwargs: pytest.fail("message must not be written"),
    )

    with pytest.raises(Nl2AgentWorkflowConflictError):
        service.finalize_nl2agent_message(
            tenant_id="tenant-a",
            user_id="user-a",
            runner_agent_id=9,
            draft_agent_id=54,
            conversation_id=77,
            message_index=3,
            expected_revision=18,
            assistant_answer="No cards yet.",
        )


def test_finalize_message_rejects_invalid_card_before_cas(monkeypatch):
    monkeypatch.setattr(service, "get_db_session", _transaction)
    monkeypatch.setattr(
        service,
        "get_nl2agent_session_snapshot_by_identity",
        lambda identity, db_session: _snapshot(),
    )
    monkeypatch.setattr(
        service,
        "update_nl2agent_workflow_state_by_identity",
        lambda **kwargs: pytest.fail("workflow must not be updated"),
    )

    with pytest.raises(Nl2AgentValidationError):
        service.finalize_nl2agent_message(
            tenant_id="tenant-a",
            user_id="user-a",
            runner_agent_id=9,
            draft_agent_id=54,
            conversation_id=77,
            message_index=3,
            expected_revision=18,
            assistant_answer="```nl2agent-model-selection\n{broken}\n```",
        )
