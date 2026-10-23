# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated presence, capability and root identity policy tests."""

from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import AgentConfig, ModelConfig
from pydantic import ValidationError

from contracts.errors.exceptions import ForbiddenError, RunModelControlsError
from contracts.agent import AgentRequest, NL2AgentRunRequest, NL2SkillRunRequest, RuntimeGenerationOverrides
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
    from management.services.model import run_bindings as create_agent_info
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
    published = mocker.patch("management.db.agent.repository.query_current_version_no", return_value=current)
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


@pytest.fixture
def preflight_models(mocker):
    """Keep catalog/conversion external while executing the actual overlay policy."""
    from management.services.model import run_bindings as create_agent_info

    catalog = mocker.patch.object(run_controls, "get_model_by_model_id", return_value={"model_id": 9})
    converted = []
    roots = []

    def convert(_record):
        base = model()
        converted.append(base)
        return base

    factory = mocker.patch.object(create_agent_info, "create_model_config_from_record", side_effect=convert)
    overlay = run_controls.overlay_root_model

    def capture(base, values, alias):
        root = overlay(base, values, alias)
        roots.append(root)
        return root

    mocker.patch.object(run_controls, "overlay_root_model", side_effect=capture)
    return catalog, factory, converted, roots


def test_preflight_uses_agent_default_and_overrides_without_mutating_catalog(preflight_models):
    catalog, factory, bases, roots = preflight_models
    request = AgentRequest(agent_id=42, query="fixture", generation_config={"thinking_effort": "auto"})
    record = {"model_ids": [9, 10], "model_params_override": {"9": {"extra_params": {
        "enable_thinking": True, "reasoning_effort": "high", "reasoning_budget_tokens": None,
    }}}}
    run_controls.preflight_turn_controls(request, "tenant", record)
    catalog.assert_called_once_with(9, "tenant")
    factory.assert_called_once_with({"model_id": 9})
    assert roots[0].reasoning_effort == "high"
    assert roots[0].cite_name == "preflight_root"
    assert roots[0].temperature == 0.43 and roots[0].top_p == 0.78
    assert bases[0].cite_name == "selected"
    assert record["model_ids"] == [9, 10]
    assert request.model_id is None


@pytest.mark.parametrize("default", [{"model_id": 9}, {}, None])
def test_preflight_resolves_tenant_default_or_rejects_missing_default(mocker, preflight_models, default):
    from contracts.constants.constants import MODEL_CONFIG_MAPPING
    from management.services.configuration.tenant.settings import tenant_config_manager

    catalog, _factory, _bases, roots = preflight_models
    get_default = mocker.patch.object(tenant_config_manager, "get_model_config", return_value=default)
    request = AgentRequest(agent_id=42, query="fixture", reasoning_effort="xhigh")
    if default:
        run_controls.preflight_turn_controls(request, "tenant")
        assert roots[0].reasoning_effort == "xhigh"
        catalog.assert_called_once_with(9, "tenant")
    else:
        with pytest.raises(RunModelControlsError, match="model_not_available"):
            run_controls.preflight_turn_controls(request, "tenant")
        catalog.assert_not_called()
    get_default.assert_called_once_with(MODEL_CONFIG_MAPPING["llm"], "tenant")


def test_preflight_without_intent_skips_catalog(preflight_models):
    catalog, factory, _bases, roots = preflight_models
    run_controls.preflight_turn_controls(AgentRequest(agent_id=42, query="fixture"), "tenant")
    catalog.assert_not_called()
    factory.assert_not_called()
    assert roots == []


def test_runtime_snapshot_is_authoritative_and_legacy_conflicts_are_rejected(preflight_models):
    catalog, _factory, _bases, roots = preflight_models
    request = AgentRequest(agent_id=42, query="fixture", model_id=9,
                           generation_config={"thinking_effort": "low"}, reasoning_effort="xhigh")
    snapshot = {"deep_thinking": True, "thinking_effort": "xhigh"}
    request.__dict__["_runtime_generation_config"] = snapshot
    run_controls.preflight_turn_controls(request, "tenant", {"model_params_override": {}})
    assert roots[0].reasoning_effort == "xhigh"
    assert snapshot == {"deep_thinking": True, "thinking_effort": "xhigh"}
    request.__dict__["_runtime_generation_config"] = {"thinking_effort": "high"}
    with pytest.raises(RunModelControlsError, match="model_controls_invalid"):
        run_controls.preflight_turn_controls(request, "tenant")
    assert len(roots) == 1
    assert catalog.call_count == 2


def test_preflight_legacy_budget_reaches_real_overlay(mocker, preflight_models):
    _catalog, factory, _bases, roots = preflight_models
    base = model(reasoning_budget_tokens=2048, reasoning_capability={
        "status": "supported", "controls": [{"type": "budget_tokens", "min": 1024, "max": 8192}],
    })
    factory.side_effect = None
    factory.return_value = base
    request = AgentRequest(agent_id=42, query="fixture", model_id=9, reasoning_budget_tokens=4096)
    run_controls.preflight_turn_controls(request, "tenant")
    assert roots[0].reasoning_budget_tokens == 4096 and roots[0].reasoning_effort is None
    assert base.reasoning_budget_tokens == 2048


def test_sampling_overlays_preserve_base_and_budget_auto_without_explicit_budget():
    base = model()
    for intent in ({"temperature": 0.2, "top_p": 0.8},
                   {"deep_thinking": False, "temperature": 0.2, "top_p": 0.8}):
        root = run_controls.overlay_root_model(base, intent, "root")
        assert root.temperature == 0.2 and root.top_p == 0.8
        assert base.temperature == 0.43 and base.top_p == 0.78
    budget = model(reasoning_budget_tokens=2048, reasoning_capability={
        "status": "supported", "controls": [{"type": "budget_tokens", "min": 1024, "max": 8192}],
    })
    root = run_controls.overlay_root_model(budget, {"thinking_effort": "auto"}, "root")
    assert root.reasoning_budget_tokens == 2048 and root.reasoning_effort is None


@pytest.mark.parametrize("capability", [
    {"status": "supported", "controls": [{"type": "budget_tokens", "min": 1024, "max": 8192}]},
    {"status": "supported", "controls": [{"type": "effort", "values": ["low"]}]},
])
def test_concrete_effort_is_rejected_when_model_does_not_offer_it(capability):
    with pytest.raises(RunModelControlsError, match="model_controls_invalid"):
        run_controls.overlay_root_model(model(reasoning_capability=capability), {"thinking_effort": "xhigh"}, "root")


@pytest.mark.parametrize("intent", [None, {}, {"thinking_effort": "xhigh"}])
def test_creator_without_explicit_model_uses_configured_root_or_fails(intent):
    base = model(cite_name="main_model")
    agent = AgentConfig(name="creator", model_name="main_model", tools=[], description="")
    models = [base]
    assert run_controls.resolve_creator_model(models, agent, "tenant", None, intent, None) == {}
    if intent:
        assert agent.model_name == "creator_root_model"
        assert models[-1].reasoning_effort == "xhigh"
    else:
        assert models == [base] and agent.model_name == "main_model"
    with pytest.raises(RunModelControlsError, match="model_not_available"):
        run_controls.resolve_creator_model([], agent, "tenant", None, intent, None)


def test_creator_explicit_model_never_falls_back_on_failed_conversion(mocker, preflight_models):
    _catalog, factory, _bases, _roots = preflight_models
    factory.side_effect = None
    factory.return_value = None
    agent = AgentConfig(name="creator", model_name="main_model", tools=[], description="")
    models = [model(cite_name="main_model")]
    with pytest.raises(RunModelControlsError, match="model_not_available"):
        run_controls.resolve_creator_model(models, agent, "tenant", 9, {}, None)
    assert len(models) == 1 and agent.model_name == "main_model"


def test_creator_default_record_keeps_alias_when_no_override(preflight_models):
    _catalog, factory, _bases, _roots = preflight_models
    agent = AgentConfig(name="creator", model_name="main_model", tools=[], description="")
    models = [model(cite_name="main_model")]
    record = {"model_id": 9}
    assert run_controls.resolve_creator_model(models, agent, "tenant", None, None, record) == record
    factory.assert_called_once_with(record)
    assert len(models) == 1 and agent.model_name == "main_model"


@pytest.mark.parametrize("value", ["invalid payload", {"query": "create", "generation_config": "invalid"}])
def test_creator_dto_rejects_invalid_payload_and_overlay_shapes(value):
    with pytest.raises(ValidationError):
        NL2SkillRunRequest.model_validate(value)


def test_creator_dto_preserves_typed_overlay_presence_and_ignores_empty_snapshot():
    overlay = RuntimeGenerationOverrides(thinking_effort="xhigh")
    request = NL2SkillRunRequest(query="create", generation_config=overlay, workbench_config={"model_id": 9})
    assert request.generation_config.model_dump(exclude_unset=True) == {"thinking_effort": "xhigh"}
    assert overlay.model_fields_set == {"thinking_effort"}
