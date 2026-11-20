# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Frozen outlet parameter layers cross AgentOS without credentials or shared mutations."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from contracts.agentos import AgentResource, RunModelBinding
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import model_bindings
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.runtime_parameters import merge_runtime_parameters
from nexent.core.model_service.registry import model_service_references
from runtime.agentos import prepared_evaluation
from runtime.model import parameters
from test.backend.services.test_conversation_model_preferences_service import profile


ACTOR = ServicePrincipal("owner", "tenant")


@pytest.fixture
def outlet(profile):
    data = profile.model_dump(mode="json")
    data["outlet_id"] = 42
    data["connection"]["credential_ref"]["model_id"] = 42
    saved = profile.__class__.model_validate(data)
    row = encode_resolved_model_profile(saved, registered_references=model_service_references())
    row.update(model_id=42, tenant_id="tenant", delete_flag="N", update_time="revision-1",
               api_key="runtime-only-secret", display_name="shared")
    return row, create_model_config_from_record(row)


def resource(alias="root-private", *, child=False):
    node = AgentResource(agent_id=8 if child else 7, version_no=2, name="agent", description="",
                         prompt_templates={}, model_alias=alias)
    if child:
        return AgentResource(agent_id=7, version_no=1, name="root", description="",
                             prompt_templates={}, model_alias="root", subagents=[node])
    return node


@pytest.mark.parametrize("values", [{}, {"temperature": 0}, {"enable_thinking": False}, {"temperature": None}])
@pytest.mark.parametrize("child", [False, True])
def test_profile_parameters_round_trip_without_changing_shared_model(monkeypatch, outlet, values, child):
    row, base = outlet
    entry = {"parameter_values": {"temperature": 0.2}}
    before = deepcopy(base.model_dump())
    resolved = merge_runtime_parameters(base.resolved_profile, entry, values)
    selected = base.model_copy(deep=True, update={"cite_name": "root-private", "resolved_profile": resolved})
    tree = resource(child=child)
    lookups = []

    def entries(agent_id, version, tenant):
        lookups.append((agent_id, version, tenant))
        return {"42": entry}

    monkeypatch.setattr(model_bindings, "get_model_by_model_id", Mock(return_value=row))
    monkeypatch.setattr(model_bindings, "read_agent_model_overrides", entries)
    monkeypatch.setattr(parameters, "read_agent_model_overrides", entries)
    monkeypatch.setattr(prepared_evaluation, "get_model_by_model_id", Mock(return_value=row))
    binding = model_bindings.export_resolved_model("root-private", selected, "tenant", tree, {"42": values},
                                                   {"shared": (42, "revision-1")})
    assert row["api_key"] not in binding.model_dump_json()
    restored = prepared_evaluation._materialize_model(
        RunModelBinding.model_validate_json(binding.model_dump_json()), ACTOR, tree,
    )
    assert restored == selected
    assert base.model_dump() == before
    assert lookups == [(8 if child else 7, 2, "tenant")] * 2


def test_outlet_revision_change_is_rejected_before_export(monkeypatch, outlet):
    row, base = outlet
    monkeypatch.setattr(model_bindings, "get_model_by_model_id", Mock(return_value={**row, "update_time": "changed"}))
    with pytest.raises(HTTPException) as error:
        model_bindings.export_resolved_model("shared", base, "tenant", resource("shared"), {},
                                             {"shared": (42, "revision-1")})
    assert error.value.status_code == 409


def test_agent_parameter_change_is_rejected_by_runtime(monkeypatch, outlet):
    _, base = outlet
    monkeypatch.setattr(parameters, "read_agent_model_overrides", Mock(return_value={"42": {
        "parameter_values": {"temperature": 0.9}}}))
    binding = RunModelBinding(model_id=42, alias="root-private", revision="revision-1",
                              agent_parameters={"parameter_values": {"temperature": 0.2}})
    with pytest.raises(HTTPException) as error:
        parameters.materialize_profile_parameters(base, binding, ACTOR, resource())
    assert error.value.status_code == 409


def test_creator_preferences_use_the_same_rules_without_an_agent_owner(outlet):
    _, base = outlet
    binding = RunModelBinding(model_id=42, alias="creator", revision="revision-1",
                              conversation_parameters={"enable_thinking": False})
    resolved = parameters.materialize_profile_parameters(base, binding, ACTOR, None)
    assert resolved.resolved_profile.parameter_values["enable_thinking"] is False
    assert "reasoning_budget_tokens" not in resolved.resolved_profile.parameter_values
    assert base.resolved_profile.parameter_values["enable_thinking"] is True
    invalid = binding.model_copy(update={"conversation_parameters": {
        "enable_thinking": False, "reasoning_budget_tokens": 32}})
    with pytest.raises(ParameterValidationError):
        parameters.materialize_profile_parameters(base, invalid, ACTOR, None)
