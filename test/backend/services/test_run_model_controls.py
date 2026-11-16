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


def test_partial_fields_do_not_enable_thinking_and_off_clears_active_controls():
    base = model(enable_thinking=False)
    result = run_controls.overlay_root_model(base, {"thinking_effort": "xhigh"}, "root")
    assert result.enable_thinking is False and result.reasoning_effort is None
    result = run_controls.overlay_root_model(model(), {"deep_thinking": False, "thinking_effort": "max"}, "root")
    assert result.enable_thinking is False and result.reasoning_effort is None and result.reasoning_budget_tokens is None
    unchanged = run_controls.overlay_root_model(model(), {}, "root")
    assert unchanged.reasoning_effort == "medium" and unchanged.extra_body == {"custom": "retained"}


@pytest.mark.parametrize("budget,expected", [(0, 2048), (1024, 1024), (8192, 8192)])
def test_budget_range_and_zero_auto_keep_sampling(budget, expected):
    base = model(reasoning_budget_tokens=2048, reasoning_capability={
        "status": "supported", "controls": [{"type": "budget_tokens", "min": 1024, "max": 8192}],
    })
    result = run_controls.overlay_root_model(base, {"reasoning_budget_tokens": budget}, "root")
    assert result.reasoning_budget_tokens == expected and result.reasoning_effort is None
    assert result.temperature == base.temperature and result.top_p == base.top_p
    for invalid in [1, 9000]:
        with pytest.raises(RunModelControlsError):
            run_controls.overlay_root_model(base, {"reasoning_budget_tokens": invalid}, "root")


def test_unknown_capability_conflicts_and_model_errors_fail_closed(mocker):
    for values in [{"deep_thinking": True}, {"deep_thinking": True, "thinking_effort": "xhigh"}]:
        with pytest.raises(RunModelControlsError):
            run_controls.overlay_root_model(model(reasoning_capability=None), values, "root")
    with pytest.raises(RunModelControlsError):
        run_controls.overlay_root_model(model(), {"thinking_effort": "high", "reasoning_budget_tokens": 2000}, "root")
    for record, code in [(None, "model_not_available"), ({"delete_flag": "Y"}, "model_not_available"),
                         ({"model_type": "embedding"}, "model_type_invalid"),
                         ({"connect_status": "Unavailable"}, "model_unavailable")]:
        lookup = mocker.patch.object(run_controls, "get_model_by_model_id", return_value=record)
        with pytest.raises(RunModelControlsError, match=code):
            run_controls.validate_selected_model(9, "current-tenant")
        lookup.assert_called_once_with(9, "current-tenant")


def test_creator_alias_preserves_independent_models_and_real_record(mocker):
    base = model()
    independent = model(cite_name="business", model_name="independent")
    agent = AgentConfig(name="creator", model_name="main_model", tools=[], description="")
    record = {"model_id": 9, "display_name": "selected", "model_type": "llm", "connect_status": "Available",
              "model_repo": "", "model_name": "provider-B", "base_url": base.url,
              "temperature": 0.43, "top_p": 0.78, "max_input_tokens": 7000,
              "extra_params": {"enable_thinking": True, "reasoning_effort": "medium"}}
    mocker.patch("infrastructure.agent_model_config._resolve_reasoning_capability", return_value=base.reasoning_capability)
    mocker.patch.object(run_controls, "get_model_by_model_id", return_value=record)
    models = [base, independent]
    result = run_controls.resolve_creator_model(models, agent, "tenant", 9, {"deep_thinking": True}, {})
    assert result == record and agent.model_name == "creator_root_model"
    assert models[-1].url == base.url and models[-1].model_name == base.model_name
    assert models[-1].max_input_tokens == 7000
    assert independent.model_name == "independent" and base.cite_name == "selected"


@pytest.mark.parametrize("version_no,current,expected", [(3, 7, 3), (None, 7, 7), (None, None, 0)])
def test_native_selection_preserves_agent_version_and_tenant(mocker, version_no, current, expected):
    request = AgentRequest(agent_id=42, query="fixture", model_id=9, version_no=version_no)
    catalog = mocker.patch.object(run_controls, "validate_selected_model")
    published = mocker.patch("management.db.agent.repository.query_current_version_no", return_value=current)
    lookup = Mock(return_value={"model_ids": [9]})
    run_controls.validate_agent_model_selection(request, "tenant", lookup)
    catalog.assert_called_once_with(9, "tenant")
    lookup.assert_called_once_with(agent_id=42, tenant_id="tenant", version_no=expected)
    if version_no is None:
        published.assert_called_once_with(42, "tenant")
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


@pytest.mark.parametrize("debug,explicit,expected", [(True, None, 0), (True, 5, 5), (False, None, 3)])
def test_preflight_matches_runtime_agent_version_and_debug_model_scope(monkeypatch, debug, explicit, expected):
    from management.db.agent import repository
    from management.services.conversation import model_preferences

    monkeypatch.setattr(repository, "query_current_version_no", lambda *_args: 3)
    lookup = Mock(side_effect=lambda **kwargs: {"model_ids": [42] if kwargs["version_no"] in (0, 5) else [41]})
    selected = Mock()
    monkeypatch.setattr(run_controls, "validate_selected_model", selected)
    validate = Mock()
    monkeypatch.setattr(model_preferences, "validate_model_preferences", validate)
    request = AgentRequest(agent_id=7, query="fixture", is_debug=debug, version_no=explicit,
        model_id=42, model_parameter_preferences={"42": {"temperature": 0}})
    run_controls.preflight_agent_turn_controls(request, "tenant", lookup)
    lookup.assert_called_once_with(agent_id=7, tenant_id="tenant", version_no=expected)
    validate.assert_called_once_with(request.model_parameter_preferences, "tenant",
        allowed_model_ids=None if debug else [41])


def test_debug_selected_model_preferences_preserve_selection_exemption(monkeypatch):
    from management.services.conversation import model_preferences

    monkeypatch.setattr(run_controls, "validate_selected_model", Mock())
    def validate(values, _tenant, *, allowed_model_ids):
        if allowed_model_ids and any(int(key) not in allowed_model_ids for key in values):
            raise ForbiddenError("The selected model is not configured for this Agent")
    monkeypatch.setattr(model_preferences, "validate_model_preferences", validate)
    request = AgentRequest(agent_id=7, query="fixture", is_debug=True,
        model_id=42, model_parameter_preferences={"42": {"temperature": 0}})
    run_controls.validate_agent_model_selection(request, "tenant", Mock())
    run_controls.preflight_turn_controls(request, "tenant", {"model_ids": [41]})


@pytest.mark.parametrize("available,chosen", [(True, 42), (False, 41)])
def test_saved_preferences_preflight_uses_the_runtime_available_model_fallback(monkeypatch, available, chosen):
    from contracts.errors.exceptions import ModelOutletValidationError
    from management.services.conversation import model_preferences

    records = {41: {"connect_status": "unavailable"},
        42: {"connect_status": "available" if available else "unavailable"}}
    monkeypatch.setattr(run_controls, "get_model_by_model_id", lambda model_id, **_kwargs: records[model_id])
    monkeypatch.setattr(run_controls, "validate_selected_model", Mock())
    def validate(values, _tenant, *, allowed_model_ids):
        assert allowed_model_ids == [41, 42]
        if str(chosen) not in values:
            raise ModelOutletValidationError("PARAMETER_DEPENDENCY")
    monkeypatch.setattr(model_preferences, "validate_model_preferences", validate)
    request = AgentRequest(agent_id=7, query="fixture")
    request.__dict__["_runtime_model_parameter_preferences"] = {"41": {"temperature": 0}, "42": {"temperature": 0.3}}
    run_controls.preflight_turn_controls(request, "tenant", {"model_ids": [41, 42]})
