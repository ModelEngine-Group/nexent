# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real SQLite transactions prove confirmation ownership, atomicity and retries."""

import json
from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import text

from contracts.clarification import ClarificationResponse
from contracts.errors.exceptions import AppException, ConversationNotFoundError
from management.db.conversation import creation_mode, repository
from test.backend.services.test_clarification_response import storage  # noqa: F401

FORM = {"schema_version": 1, "questions": [{
    "id": "workbench_creation_mode", "type": "single_choice", "title": "进入创建？",
    "creation_request": "整理文章并保留出处", "options": [
        {"id": "agent_create", "label": "智能体创建"}, {"id": "continue_chat", "label": "继续对话"}],
}]}


@pytest.fixture
def confirmation_store(storage, monkeypatch):
    storage.execute(text("ALTER TABLE nexent.conversation_record_t ADD COLUMN workbench_config TEXT"))
    storage.execute(text("UPDATE nexent.conversation_record_t SET workbench_config=:config"),
                    {"config": json.dumps({"mode": "generic_chat"})})
    storage.execute(text("UPDATE nexent.conversation_message_unit_t SET unit_content=:form"),
                    {"form": json.dumps(FORM)})
    storage.commit()
    previous = repository.get_db_session

    @contextmanager
    def sessions(supplied=None):
        if supplied is not None:
            yield supplied
        else:
            with previous() as session:
                yield session

    monkeypatch.setattr(repository, "get_db_session", sessions)
    monkeypatch.setattr(creation_mode, "get_db_session", sessions)
    return storage


def response(**overrides):
    return ClarificationResponse.model_validate({"schema_version": 1, "form": deepcopy(FORM), "unit_index": 7,
        "answers": [{"questionId": "workbench_creation_mode", "value": "agent_create", "otherText": None}],
        **overrides})


def test_confirmation_commits_one_response_and_exact_retry_is_idempotent(confirmation_store):
    first = creation_mode.save_creation_response(1, response(), "Confirmed", "owner")
    retry = creation_mode.save_creation_response(1, response(unit_index=None), "Confirmed", "owner")
    assert first == retry
    assert first["clarification_response"]["source_message_id"] == 10
    assert first["clarification_response"]["form"]["questions"][0]["creation_request"] == "整理文章并保留出处"
    assert confirmation_store.execute(text("SELECT count(*) FROM nexent.conversation_message_t")).scalar() == 2


@pytest.mark.parametrize("variant", ["foreign", "stopped", "wrong_form", "wrong_unit", "creation_mode"])
def test_ineligible_confirmation_never_writes(confirmation_store, variant):
    raw = response().model_dump()
    owner = "owner"
    if variant == "foreign":
        owner = "another"
    elif variant == "stopped":
        confirmation_store.execute(text("UPDATE nexent.conversation_message_t SET status='stopped'"))
    elif variant == "wrong_form":
        raw["form"]["questions"][0]["creation_request"] = "Forged request"
    elif variant == "wrong_unit":
        raw["unit_index"] = 8
    else:
        confirmation_store.execute(text("UPDATE nexent.conversation_record_t SET workbench_config=:config"),
                                   {"config": json.dumps({"mode": "agent_create"})})
    confirmation_store.commit()
    with pytest.raises((AppException, ConversationNotFoundError)):
        creation_mode.save_creation_response(1, ClarificationResponse.model_validate(raw), "Confirmed", owner)
    assert confirmation_store.execute(text("SELECT count(*) FROM nexent.conversation_message_t")).scalar() == 1


def test_different_retry_is_rejected(confirmation_store):
    creation_mode.save_creation_response(1, response(), "Confirmed", "owner")
    raw = response().model_dump()
    raw["answers"][0]["value"] = "continue_chat"
    with pytest.raises(AppException):
        creation_mode.save_creation_response(1, ClarificationResponse.model_validate(raw), "Changed", "owner")
    assert confirmation_store.execute(text("SELECT count(*) FROM nexent.conversation_message_t")).scalar() == 2


def test_confirmation_unit_failure_rolls_back_the_readable_message(confirmation_store):
    confirmation_store.execute(text("CREATE TRIGGER nexent.fail_creation_response BEFORE INSERT ON conversation_message_unit_t "
        "WHEN NEW.unit_type='clarification_response' BEGIN SELECT RAISE(ABORT,'unit failed'); END"))
    confirmation_store.commit()
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        creation_mode.save_creation_response(1, response(), "Confirmed", "owner")
    assert confirmation_store.execute(text("SELECT count(*) FROM nexent.conversation_message_t")).scalar() == 1


@pytest.mark.parametrize("config", [None, "[]", '"ordinary text"'])
def test_missing_or_non_object_workbench_config_cannot_write_confirmation(confirmation_store, config):
    confirmation_store.execute(text("UPDATE nexent.conversation_record_t SET workbench_config=:config"),
                               {"config": config})
    confirmation_store.commit()

    with pytest.raises(ConversationNotFoundError, match="Workbench conversation not found"):
        creation_mode.save_creation_response(1, response(), "Confirmed", "owner")

    assert confirmation_store.execute(text("SELECT count(*) FROM nexent.conversation_message_t")).scalar() == 1


def test_missing_latest_message_rejects_confirmation_without_inserting_one(confirmation_store):
    confirmation_store.execute(text("DELETE FROM nexent.conversation_message_unit_t"))
    confirmation_store.execute(text("DELETE FROM nexent.conversation_message_t"))
    confirmation_store.commit()

    with pytest.raises(AppException, match="Clarification is no longer available"):
        creation_mode.save_creation_response(1, response(), "Confirmed", "owner")

    assert confirmation_store.execute(text("SELECT count(*) FROM nexent.conversation_message_t")).scalar() == 0
