# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation selection checks ownership before validating and saving a CAS update."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.errors.exceptions import ConversationNotFoundError, ForbiddenError, ModelOutletValidationError
from management.services.conversation import model_preferences as service
from test.backend.services.test_conversation_model_preferences_service import persistence, profile


@pytest.fixture
def boundaries(monkeypatch, persistence):
    store, getter = persistence
    conversation = ModuleType("management.services.conversation.service")
    conversation.get_conversation_service = Mock(return_value={"agent_id": 7})
    agents = ModuleType("management.db.agent.repository")
    agents.search_agent_info_by_agent_id = Mock()
    controls = ModuleType("management.services.model.run_controls")
    controls.validate_agent_model_selection = Mock()
    controls.validate_selected_model = Mock()
    for module in [conversation, agents, controls]:
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return store, getter, conversation.get_conversation_service, controls


@pytest.mark.parametrize("workbench", [False, True])
def test_selection_preserves_owner_and_version_in_both_chat_modes(boundaries, workbench):
    store, _, lookup, controls = boundaries
    lookup.return_value = {"agent_id": 7, **({"workbench_config": {}} if workbench else {})}
    body = SimpleNamespace(selected_model_id=42, expected_version=4)
    assert service.patch_model_selection(8, body, "owner", "tenant") == store.return_value
    lookup.assert_called_once_with(8, "owner", "tenant")
    selected, tenant, _ = controls.validate_agent_model_selection.call_args.args
    assert selected.model_id == 42 and selected.agent_id == 7 and tenant == "tenant"
    assert selected.entrypoint == ("workbench" if workbench else None)
    store.assert_called_once_with(8, "owner", expected_version=4, selected_model_id=42)


def test_missing_conversation_cannot_validate_or_write_selection(boundaries):
    store, getter, lookup, controls = boundaries
    lookup.return_value = None
    with pytest.raises(ConversationNotFoundError):
        service.patch_model_selection(8, SimpleNamespace(selected_model_id=42, expected_version=4), "owner", "tenant")
    store.assert_not_called()
    getter.assert_not_called()
    controls.validate_agent_model_selection.assert_not_called()


@pytest.mark.parametrize("key", [42, "01", "0", "-1", "model"])
def test_noncanonical_model_ids_are_rejected_without_model_access(boundaries, key):
    _, getter, _, controls = boundaries
    with pytest.raises(ModelOutletValidationError) as error:
        service.validate_model_preferences({key: {}}, "tenant")
    assert error.value.category == "CONVERSATION_PREFERENCES_INVALID"
    controls.validate_selected_model.assert_not_called()
    getter.assert_not_called()


def test_model_not_configured_for_agent_is_rejected_before_outlet_read(boundaries):
    _, getter, _, controls = boundaries
    with pytest.raises(ForbiddenError):
        service.validate_model_preferences({"42": {}}, "tenant", allowed_model_ids=[43])
    controls.validate_selected_model.assert_not_called()
    getter.assert_not_called()


@pytest.mark.parametrize("values", [None, []])
def test_preferences_require_objects(boundaries, values):
    with pytest.raises(ModelOutletValidationError) as error:
        service.validate_model_preferences(values, "tenant")
    assert error.value.category == "CONVERSATION_PREFERENCES_INVALID"


@pytest.mark.parametrize("values,category", [([], "CONVERSATION_PREFERENCES_INVALID"),
    ({"max_output_tokens": 100}, "FIXED_PARAMETER")])
def test_draft_rejects_nonobjects_and_outlet_only_limits(boundaries, values, category):
    with pytest.raises(ModelOutletValidationError) as error:
        service.validate_model_preferences({"42": values}, "tenant")
    assert error.value.category == category


def test_missing_outlet_is_not_treated_as_an_empty_preference(boundaries):
    _, getter, _, _ = boundaries
    getter.return_value = None
    with pytest.raises(ModelOutletValidationError) as error:
        service.validate_model_preferences({"42": {}}, "tenant")
    assert error.value.category == "MODEL_OUTLET_NOT_AVAILABLE"
