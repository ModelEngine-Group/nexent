# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated presence, capability and root identity policy tests."""

from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import AgentConfig, ModelConfig
from pydantic import ValidationError

from consts.exceptions import ForbiddenError, RunModelControlsError
from consts.model import (
    AgentRequest,
    NL2AgentRunRequest,
    NL2SkillRunRequest,
    RuntimeGenerationOverrides,
)
from management.services.model import run_controls

EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def model(**overrides):
    return ModelConfig(
        cite_name="selected", model_name="provider-B", url="http://fixture.invalid/B",
        enable_thinking=True, reasoning_effort="medium", temperature=0.43,
        top_p=0.78, max_input_tokens=7000, extra_body={"custom": "retained"},
        reasoning_capability={"status": "supported", "control": "effort", "levels": EFFORTS},
    ).model_copy(update=overrides)


@pytest.mark.parametrize("request_type", [NL2AgentRunRequest, NL2SkillRunRequest])
def test_omitted_empty_and_null_overlay_preserve_presence(request_type):
    args = {"query": "create", **({"agent_id": 7} if request_type is NL2AgentRunRequest else {})}
    assert request_type(**args).generation_config is None
    assert request_type(**args, generation_config={}).generation_config.model_dump(exclude_unset=True) == {}
    assert request_type(**args, generation_config=None, model_id=None).model_id is None
    assert RuntimeGenerationOverrides(thinking_effort="xhigh").model_fields_set == {"thinking_effort"}


@pytest.mark.parametrize("field,value", [
    ("deep_thinking", None), ("deep_thinking", "false"),
    ("thinking_effort", None), ("thinking_effort", "invalid"),
    ("reasoning_budget_tokens", None), ("reasoning_budget_tokens", True),
    ("reasoning_budget_tokens", -1), ("reasoning_budget_tokens", 1.1),
    ("temperature", 50), ("top_p", 90),
])
def test_invalid_partial_controls_are_rejected(field, value):
    with pytest.raises(ValidationError):
        RuntimeGenerationOverrides(**{field: value})


def test_snapshot_and_legacy_fields_have_one_authority():
    request = NL2SkillRunRequest(query="create", workbench_config={
        "model_id": 8, "generation_config": {"deep_thinking": True, "thinking_effort": "xhigh"},
    }, reasoning_effort="xhigh")
    assert request.model_id == 8
    assert request.generation_config.model_dump(exclude_unset=True) == {
        "deep_thinking": True, "thinking_effort": "xhigh",
    }
    for conflicting in [{"model_id": 9}, {"generation_config": {"thinking_effort": "high"}},
                        {"reasoning_effort": "high"}]:
        with pytest.raises(ValidationError, match="conflicting"):
            NL2SkillRunRequest(query="create", workbench_config=request.workbench_config, **conflicting)


@pytest.mark.parametrize("effort", EFFORTS + ["auto"])
def test_exact_effort_or_auto_inherits_immutable_base(effort):
    base = model()
    result = run_controls.overlay_root_model(base, {"deep_thinking": True, "thinking_effort": effort}, "root")
    assert result.reasoning_effort == ("medium" if effort == "auto" else effort)
    assert (result.temperature, result.top_p, result.max_input_tokens) == (0.43, 0.78, 7000)
    assert base.reasoning_effort == "medium" and base.cite_name == "selected"
    assert result.extra_body == {"custom": "retained", "enable_thinking": True}


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
    from agents import create_agent_info
    mocker.patch.object(create_agent_info, "_resolve_reasoning_capability", return_value=base.reasoning_capability)
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
    published = mocker.patch("database.agent_db.query_current_version_no", return_value=current)
    lookup = Mock(return_value={"model_ids": [9]})
    run_controls.validate_agent_model_selection(request, "tenant", lookup)
    catalog.assert_called_once_with(9, "tenant")
    lookup.assert_called_once_with(agent_id=42, tenant_id="tenant", version_no=expected)
    if version_no is None:
        published.assert_called_once_with(42, "tenant")
    else:
        published.assert_not_called()
    lookup.return_value = {"model_ids": [1]}
    with pytest.raises(ForbiddenError, match="not configured"):
        run_controls.validate_agent_model_selection(request, "tenant", lookup)


def test_workbench_and_debug_selection_validate_catalog_without_native_agent_allowlist(mocker):
    catalog = mocker.patch.object(run_controls, "validate_selected_model")
    lookup = Mock()
    for request in (
        AgentRequest(agent_id=42, query="fixture", model_id=9, is_debug=True),
        AgentRequest(query="fixture", model_id=1, entrypoint="workbench", workbench={"mode": "generic_chat", "model_id": 9}),
    ):
        run_controls.validate_agent_model_selection(request, "tenant", lookup)
        catalog.assert_called_with(9, "tenant")
    lookup.assert_not_called()
    catalog.side_effect = RunModelControlsError("model_unavailable")
    with pytest.raises(RunModelControlsError, match="model_unavailable"):
        run_controls.validate_agent_model_selection(request, "tenant", lookup)
    lookup.assert_not_called()


def test_default_run_does_not_lookup_or_preflight_missing_control_intent(mocker):
    request = AgentRequest(agent_id=42, query="fixture")
    lookup = Mock()
    catalog = mocker.patch.object(run_controls, "validate_selected_model")
    preflight = mocker.patch.object(run_controls, "preflight_turn_controls")
    run_controls.validate_agent_model_selection(request, "tenant", lookup)
    run_controls.preflight_agent_turn_controls(request, "tenant", lookup)
    lookup.assert_not_called()
    catalog.assert_not_called()
    preflight.assert_not_called()


@pytest.mark.parametrize("intent", [
    {"model_id": 9}, {"generation_config": {}}, {"reasoning_effort": "auto"},
    {"reasoning_budget_tokens": 1024}, {"generation_config": {"reasoning_budget_tokens": 0}},
])
def test_preflight_preserves_each_explicit_intent_and_entrypoint_defaults(mocker, intent):
    native = AgentRequest(agent_id=42, query="fixture", version_no=3, **intent)
    record = {"model_ids": [9], "model_params_override": {"9": {"temperature": 0.43}}}
    lookup = Mock(return_value=record)
    preflight = mocker.patch.object(run_controls, "preflight_turn_controls")
    run_controls.preflight_agent_turn_controls(native, "tenant", lookup)
    lookup.assert_called_once_with(agent_id=42, tenant_id="tenant", version_no=3)
    preflight.assert_called_once_with(native, "tenant", record)
    lookup.reset_mock()
    workbench = AgentRequest(query="fixture", entrypoint="workbench", workbench={"mode": "generic_chat", "model_id": 9}, **intent)
    run_controls.preflight_agent_turn_controls(workbench, "tenant", lookup)
    preflight.assert_called_with(workbench, "tenant", None)
    lookup.assert_not_called()
