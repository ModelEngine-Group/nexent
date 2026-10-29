# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""SU-AC-01/05/07: one preference DTO, preserved selection policy and preflight."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from contracts.errors.exceptions import ForbiddenError, RunModelControlsError
from contracts.agent import AgentRequest, NL2AgentRunRequest, NL2SkillRunRequest, WorkbenchSessionConfig
from management.services.model import run_controls


@pytest.mark.parametrize("dto,required", [
    (AgentRequest, {"query": "fixture"}),
    (NL2AgentRunRequest, {"query": "fixture", "agent_id": 7}),
    (NL2SkillRunRequest, {"query": "fixture"}),
])
def test_su_ac_01_same_preferences_for_all_agent_entrypoints(dto, required):
    values = {"42": {"temperature": 0, "top_p": 1, "enable_thinking": False}}
    request = dto(**required, model_id=42, model_parameter_preferences=values)
    assert request.model_parameter_preferences == values
    assert not hasattr(request, "generation_config")
    assert not hasattr(request, "reasoning_effort")
    assert dto(**required).model_parameter_preferences == {}


@pytest.mark.parametrize("dto,required", [(AgentRequest, {"query": "fixture"}),
    (NL2AgentRunRequest, {"query": "fixture", "agent_id": 7}), (NL2SkillRunRequest, {"query": "fixture"})])
@pytest.mark.parametrize("old", ["generation_config", "reasoning_effort", "reasoning_budget_tokens"])
def test_su_ac_07_removed_request_contract_is_rejected_not_silently_ignored(dto, required, old):
    with pytest.raises(ValidationError, match="model_parameter_preferences"):
        dto(**required, **{old: {} if old == "generation_config" else 1})


def test_su_ac_01_workbench_only_owns_selection_and_resources():
    config = WorkbenchSessionConfig(mode="generic_chat", requested_output_tokens=100)
    assert config.schema_version == 4
    assert config.requested_output_tokens == 100
    assert "generation_config" not in config.model_dump()
    with pytest.raises(ValidationError):
        WorkbenchSessionConfig(mode="generic_chat", generation_config={"temperature": 1})


@pytest.mark.parametrize("record,code", [(None, "model_not_available"),
    ({"delete_flag": "Y"}, "model_not_available"),
    ({"model_type": "embedding"}, "model_type_invalid")])
def test_su_ac_05_rejects_unavailable_model(record, code):
    with pytest.raises(RunModelControlsError) as raised:
        run_controls.validate_selected_record(record)
    assert raised.value.code == code


def test_su_ac_05_selected_model_is_resolved_with_tenant(monkeypatch):
    lookup = Mock(return_value={"model_id": 42, "model_type": "llm", "connect_status": "available"})
    monkeypatch.setattr(run_controls, "get_model_by_model_id", lookup)
    assert run_controls.validate_selected_model(42, "tenant")["model_id"] == 42
    lookup.assert_called_once_with(42, "tenant")


@pytest.mark.parametrize("is_debug,entrypoint,allowed", [(False, None, False), (True, None, True), (False, "workbench", True)])
def test_su_ac_05_preserves_agent_model_scope(monkeypatch, is_debug, entrypoint, allowed):
    monkeypatch.setattr(run_controls, "validate_selected_model", Mock())
    monkeypatch.setattr(run_controls, "_agent_record_for_run", Mock(return_value={"model_ids": [41]}))
    request = SimpleNamespace(model_id=42, workbench=None, entrypoint=entrypoint, is_debug=is_debug, agent_id=7)
    if allowed:
        run_controls.validate_agent_model_selection(request, "tenant", Mock())
    else:
        with pytest.raises(ForbiddenError):
            run_controls.validate_agent_model_selection(request, "tenant", Mock())


def test_su_ac_05_preflight_uses_shared_profile_validation(monkeypatch):
    from management.services.conversation import model_preferences as service
    validate = Mock()
    monkeypatch.setattr(service, "validate_model_preferences", validate)
    selected = Mock()
    monkeypatch.setattr(run_controls, "validate_selected_model", selected)
    request = AgentRequest(query="fixture", model_id=42, model_parameter_preferences={"42": {"temperature": 0}})
    run_controls.preflight_turn_controls(request, "tenant", {"model_ids": [42]})
    selected.assert_called_once_with(42, "tenant")
    validate.assert_called_once_with(request.model_parameter_preferences, "tenant", allowed_model_ids=[42])
    validate.side_effect = ValueError("invalid preference")
    with pytest.raises(ValueError, match="invalid preference"):
        run_controls.preflight_turn_controls(request, "tenant")


@pytest.mark.parametrize("status", ["available", "unavailable", "not_detected"])
def test_ac_fix_03_explicit_model_selection_preserves_probe_state(status):
    record = {"model_id": 42, "model_type": "llm", "connect_status": status}
    assert run_controls.validate_selected_record(record) is record
    assert record["connect_status"] == status


@pytest.mark.parametrize("status", ["unavailable", "not_detected"])
def test_ac_fix_03_agent_projection_and_availability_keep_explicit_model(monkeypatch, status):
    from management.services.agent import read
    record = {"model_type": "llm", "display_name": "Explicit model", "connect_status": status}
    monkeypatch.setattr(read, "get_valid_model_ids", lambda ids, tenant: ids)
    monkeypatch.setattr(read, "resolve_model_record", lambda *args: record)
    monkeypatch.setattr(read, "search_tools_for_sub_agent", lambda **kwargs: [])
    agent = {"model_ids": [42]}
    projection = read.project_agent_models(agent, "tenant")
    assert projection.fields["model_ids"] == [42]
    assert projection.fields["model_names"] == ["Explicit model"]
    assert read.check_agent_availability(7, "tenant", agent) == (True, [])
    assert record["connect_status"] == status


@pytest.mark.parametrize("record", [None, {"delete_flag": "Y"}, {"model_type": "embedding"}])
def test_ac_fix_03_configured_model_rejects_missing_deleted_or_wrong_type(record):
    from management.services.model.resolver import is_model_configured
    assert not is_model_configured(record)


@pytest.mark.parametrize("status", ["unavailable", "not_detected"])
def test_ac_fix_03_automatic_health_check_stays_strict(status):
    from management.services.model.resolver import is_model_available
    assert not is_model_available({"model_type": "llm", "connect_status": status})
