# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Branching keeps the selected model and independent parameter preferences."""

from copy import deepcopy

import pytest

from management.db.conversation import repository as db
from test.backend.database.test_conversation_branch_db import (
    _ExecuteRecorder,
    _conversation_insert,
    _conversation_row,
    _three_turn_rows,
    _wire,
    params,
    session as session,
)


@pytest.mark.parametrize("with_workbench", [False, True])
def test_branch_retains_model_selection_and_deep_copies_preferences(session, with_workbench):
    preferences = {
        "42": {"temperature": 0.35, "extra_params": {"stop": ["DONE"], "enabled": False}},
        "7": {"temperature": 0},
    }
    original_preferences = deepcopy(preferences)
    source = _conversation_row(
        selected_model_id=42,
        model_parameter_preferences=preferences,
        workbench_config={"mode": "single_agent_chat"} if with_workbench else None,
    )
    _wire(session, _three_turn_rows(), conversation=source)
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    db.branch_conversation(7, 1, user_id="owner")

    inserted = params(_conversation_insert(recorder))
    assert inserted["selected_model_id"] == 42
    assert inserted["model_parameter_preferences"] == original_preferences
    assert source.model_parameter_preferences == original_preferences
    assert inserted["model_parameter_preferences"] is not preferences
    inserted["model_parameter_preferences"]["42"]["extra_params"]["stop"].append("NEW")
    inserted["model_parameter_preferences"]["7"]["temperature"] = 0.9
    assert source.model_parameter_preferences == original_preferences


@pytest.mark.parametrize("preferences", [None, {}])
def test_branch_keeps_default_model_and_empty_preferences_without_json_null(session, preferences):
    _wire(session, _three_turn_rows(), conversation=_conversation_row(
        selected_model_id=None, model_parameter_preferences=preferences
    ))
    recorder = _ExecuteRecorder()
    session.execute.side_effect = recorder

    db.branch_conversation(7, 1, user_id="owner")

    inserted = params(_conversation_insert(recorder))
    assert inserted["selected_model_id"] is None
    assert inserted["model_parameter_preferences"] == {}
    assert inserted["model_parameter_preferences"] is not preferences
