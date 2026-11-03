# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing-conversation views and writes use the same root layers as execution."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from contracts.conversation import ConversationModelPreferencePatch
from contracts.errors.exceptions import ConversationNotFoundError, ModelOutletValidationError
from management.services.conversation import model_preferences as service
from test.backend.services.test_conversation_model_preferences_service import profile, persistence


@pytest.fixture
def routing(monkeypatch, persistence, profile):
    from management.db.agent import repository
    from management.services.conversation import service as conversation_service

    conversation = Mock(return_value={"agent_id": 7, "workbench_config": None})
    lookup = Mock(return_value={"model_params_override": {"42": {"parameter_values": {
        "enable_thinking": True, "reasoning_budget_tokens": 64, "temperature": 0.2}}}})
    version = Mock(return_value=9)
    monkeypatch.setattr(conversation_service, "get_conversation_service", conversation)
    monkeypatch.setattr(repository, "search_agent_info_by_agent_id", lookup)
    monkeypatch.setattr(repository, "query_current_version_no", version)
    store, outlet = persistence
    outlet.return_value = service.merge_model_preferences(profile, {"enable_thinking": False})
    store.return_value = {"model_parameter_preferences": {"42": {"reasoning_budget_tokens": 32}}}
    return conversation, lookup, version


def test_existing_view_applies_agent_defaults_and_validates_inherited_thinking(routing, persistence):
    conversation, lookup, version = routing
    result = service.read_model_preference_view(1, 42, "owner", "tenant")
    assert result["parameter_values"] == {"reasoning_budget_tokens": 32}
    assert result["defaults"]["enable_thinking"] is True
    assert result["defaults"]["temperature"] == 0.2
    assert result["defaults"]["reasoning_budget_tokens"] == 64
    assert result["issues"] == []
    conversation.assert_called_once_with(1, "owner", "tenant")
    lookup.assert_called_once_with(agent_id=7, tenant_id="tenant", version_no=9)
    version.assert_called_once_with(7, "tenant")


def test_existing_patch_keeps_only_explicit_session_values_and_clear_restores_agent(routing, persistence):
    store, outlet = persistence
    before = deepcopy(outlet.return_value.model_dump())
    request = ConversationModelPreferencePatch(parameter_values={"reasoning_budget_tokens": 32})
    service.patch_model_preferences(1, 42, request, "owner", "tenant")
    assert store.call_args.kwargs["resolve_values"]({}) == {"reasoning_budget_tokens": 32}
    service.patch_model_preferences(1, 42,
        ConversationModelPreferencePatch(delete_parameters=["reasoning_budget_tokens"]), "owner", "tenant")
    assert store.call_args.kwargs["resolve_values"]({"reasoning_budget_tokens": 32}) == {}
    assert outlet.return_value.model_dump() == before


@pytest.mark.parametrize("values", [
    {"enable_thinking": False, "reasoning_budget_tokens": 32},
    {"reasoning_budget_tokens": -1},
])
def test_invalid_explicit_session_values_stay_invalid_in_read_and_patch(routing, persistence, values):
    store, _ = persistence
    store.return_value = {"model_parameter_preferences": {"42": values}}
    assert service.read_model_preference_view(1, 42, "owner", "tenant")["issues"]
    service.patch_model_preferences(1, 42, ConversationModelPreferencePatch(parameter_values=values), "owner", "tenant")
    with pytest.raises(ModelOutletValidationError):
        store.call_args.kwargs["resolve_values"]({})


@pytest.mark.parametrize("context", [
    {"agent_id": 7, "workbench_config": {"schema_version": 4, "mode": "generic_chat"}},
    {"agent_id": 7, "target": {"type": "agent", "id": 12}},
    {"agent_id": None},
])
def test_workbench_and_creator_targets_do_not_supply_native_overrides(routing, persistence, context):
    conversation, lookup, _ = routing
    conversation.return_value = context
    result = service.read_model_preference_view(1, 42, "owner", "tenant")
    assert result["defaults"]["enable_thinking"] is False
    assert result["issues"][0]["category"] == "PARAMETER_DEPENDENCY"
    lookup.assert_not_called()


def test_platform_creator_root_does_not_supply_native_overrides(routing):
    _, lookup, _ = routing
    lookup.return_value = {"agent_origin": "SYSTEM", "model_params_override": {"42": {
        "parameter_values": {"enable_thinking": True}}}}
    result = service.read_model_preference_view(1, 42, "owner", "tenant")
    assert result["defaults"]["enable_thinking"] is False
    assert result["issues"]


def test_missing_conversation_is_rejected_before_model_or_agent_lookup(routing, persistence):
    conversation, lookup, _ = routing
    conversation.return_value = None
    _, outlet = persistence
    with pytest.raises(ConversationNotFoundError):
        service.read_model_preference_view(1, 42, "other-owner", "other-tenant")
    outlet.assert_not_called()
    lookup.assert_not_called()


def test_draft_fallback_matches_runtime_only_when_no_version_is_published(routing):
    _, lookup, version = routing
    version.return_value = None
    assert not service.read_model_preference_view(1, 42, "owner", "tenant")["issues"]
    assert lookup.call_args.kwargs["version_no"] == 0
