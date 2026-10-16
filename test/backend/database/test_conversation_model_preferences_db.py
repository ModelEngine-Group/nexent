# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Preference persistence uses conversation ownership, an independent revision and no commits."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from consts.exceptions import ConversationNotFoundError, ModelOutletConflictError

from test.backend.database.test_model_outlet_db import database, load  # noqa: F401


@pytest.fixture
def preferences_db(database, monkeypatch):
    module = load("_outlet_unit_db.conversation_model_preferences_db",
        "backend/database/conversation_model_preferences_db.py", monkeypatch)
    return module, database[1]


@pytest.fixture
def record():
    return SimpleNamespace(model_parameter_preferences={"42": {"temperature": 0}, "43": {"enable_thinking": False}},
        model_parameter_preferences_version=2)


def test_patch_preserves_other_outlets_and_configurations_and_has_no_commit(preferences_db, record):
    db, client = preferences_db
    session = MagicMock()
    session.scalars.return_value.first.return_value = record
    db.get_db_session = lambda: __import__("contextlib").nullcontext(session)
    original = deepcopy(record.model_parameter_preferences)
    result = db.model_preferences(1, "owner", expected_version=2, outlet_id=42, resolve_values=lambda saved: {})
    assert result == {"model_parameter_preferences": {"43": {"enable_thinking": False}}, "version": 3}
    assert original["42"] == {"temperature": 0}
    query = str(session.scalars.call_args.args[0])
    assert "FOR UPDATE" in query and "created_by" in query and "delete_flag" in query
    assert not hasattr(record, "runtime_metadata") and not hasattr(record, "workbench_config")
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def test_conflict_does_not_change_values(preferences_db, record):
    db, client = preferences_db
    session = MagicMock()
    session.scalars.return_value.first.return_value = record
    db.get_db_session = lambda: __import__("contextlib").nullcontext(session)
    before = deepcopy(record.model_parameter_preferences)
    with pytest.raises(db.ModelOutletConflictError):
        db.model_preferences(1, "owner", expected_version=1, outlet_id=42, resolve_values=lambda saved: {})
    assert record.model_parameter_preferences == before and record.model_parameter_preferences_version == 2
    session.flush.assert_not_called()


def test_missing_or_other_owner_has_no_preferences(preferences_db):
    db, client = preferences_db
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    db.get_db_session = lambda: __import__("contextlib").nullcontext(session)
    with pytest.raises(db.ConversationNotFoundError):
        db.model_preferences(1, "other-owner")
    session.flush.assert_not_called()


@pytest.mark.parametrize("invalid", [[], False, 0, ""])
def test_invalid_stored_configuration_is_not_silently_reset(preferences_db, record, invalid):
    db, _ = preferences_db
    session = MagicMock()
    record.model_parameter_preferences = invalid
    session.scalars.return_value.first.return_value = record
    db.get_db_session = lambda: __import__("contextlib").nullcontext(session)
    with pytest.raises(db.ModelOutletValidationError):
        db.model_preferences(1, "owner", expected_version=2, outlet_id=42, resolve_values=lambda saved: {})
    assert record.model_parameter_preferences == invalid
    assert record.model_parameter_preferences_version == 2
    session.flush.assert_not_called()
