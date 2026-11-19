# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Management provisioning and request snapshot guards with external I/O isolated."""

import json
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from management.services.model.runtime_options import compile_model_runtime_profile
from management.services.model.adapter import restore_model_snapshot
from test.backend.services.model_profile_helpers import legacy_record, canonical_record


@pytest.fixture
def saved():
    return canonical_record(legacy_record())


def test_compile_request_values_into_detached_saved_rules(saved):
    profile = restore_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.3,
        enable_thinking=False, extra_body={"enable_thinking": False, "custom_flag": "value"})
    config = AgentConfig(name="test", description="test", model_name="outlet", tools=[])
    config.context_budget_snapshot = SimpleNamespace(requested_output_tokens=128)
    effective = compile_model_runtime_profile(model, config)
    assert effective.parameter_values["temperature"] == .3
    assert effective.parameter_values["max_output_tokens"] == 128
    assert effective.extra_api_parameters == [{"path": "/custom_flag", "value": "value"}]
    assert profile.parameter_values["max_output_tokens"] == 256


def test_compile_rejects_protected_extra_fields_and_missing_profile(saved):
    profile = restore_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, enable_thinking=False,
        extra_body={"authorization": "must-not-leak"})
    config = AgentConfig(name="test", description="test", model_name="outlet", tools=[])
    with pytest.raises(ValueError):
        compile_model_runtime_profile(model, config)

    model.resolved_profile = None
    with pytest.raises(ValueError, match="PROVISIONING_REQUIRED"):
        compile_model_runtime_profile(model, config)


def test_effective_request_budget_takes_precedence_over_saved_agent_output(saved):
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
    from nexent.core.concurrency import RunCancellationScope

    profile = restore_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7,
        top_p=None, enable_thinking=False)
    config = AgentConfig(name="test", description="test", model_name="outlet", tools=[], requested_output_tokens=256)
    budget = SimpleNamespace(requested_output_tokens=128)
    config.context_budget_snapshot = budget
    model.resolved_profile = compile_model_runtime_profile(model, config)
    info = SimpleNamespace(agent_config=config, context_budget_snapshot=budget, model_service=Mock(), model_deadline=None)
    adapter = JiuwenAdapter(info)
    adapter.scope = RunCancellationScope()
    adapter.model_config = model
    assert adapter._create_model().profile.parameter_values["max_output_tokens"] == 128


def test_custom_output_cannot_override_resolved_budget(saved):
    profile = restore_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7, top_p=None,
        extra_body={"max_tokens": 99}, enable_thinking=False)
    config = SimpleNamespace(context_budget_snapshot=SimpleNamespace(requested_output_tokens=128),
                             requested_output_tokens=None)
    with pytest.raises(ValueError, match="LEGACY_PARAMETER_CONFLICT"):
        compile_model_runtime_profile(model, config)


def test_custom_values_use_saved_bindings_and_preserve_empty_objects(saved):
    profile = restore_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7, top_p=None,
        extra_body={"enable_thinking": True, "custom": {}}, enable_thinking=False)
    effective = compile_model_runtime_profile(model, SimpleNamespace(context_budget_snapshot=None,
                                                                     requested_output_tokens=None))
    assert effective.parameter_values["enable_thinking"] is True
    assert effective.extra_api_parameters == [{"path": "/custom", "value": {}}]


def test_record_factory_and_request_overlay_preserve_trusted_outlet(saved, monkeypatch):
    """The refactored record factory must retain the Jiuwen outlet binding."""
    from management.services.model.run_bindings import create_model_config_from_record
    # MCP transport is unrelated to the in-memory root preference overlay.
    monkeypatch.setitem(sys.modules, "management.services.mcp.service",
                        SimpleNamespace(get_remote_mcp_server_list=Mock()))
    from management.services.agent.preparation.run import apply_root_model_preferences
    from management.services.model.runtime_options import compile_bound_model_profile

    canonical_record = saved
    base = create_model_config_from_record(canonical_record)
    original = base.resolved_profile.model_dump()
    models = [base]
    config = AgentConfig(name="root", description="Root", model_name=base.cite_name, tools=[])
    apply_root_model_preferences(models, config, {str(saved["model_id"]): {"temperature": 0.3}})
    overlay = models[-1]
    compiled = compile_bound_model_profile(overlay, config)

    assert len(models) == 2 and overlay.cite_name == config.model_name != base.cite_name
    assert base.resolved_profile.outlet_id == compiled.outlet_id == saved["model_id"]
    assert compiled.identity.tenant_id == "tenant"
    assert compiled.parameter_values["temperature"] == 0.3
    assert base.temperature == 0.7
    assert base.resolved_profile.model_dump() == original
    assert overlay.resolved_profile.parameter_values["temperature"] == 0.3
    assert overlay.resolved_profile.parameter_rules == base.resolved_profile.parameter_rules


@pytest.mark.parametrize("extra", [{}, {"reasoning_effort": "auto"}])
def test_auto_effort_without_saved_rule_uses_shared_omission_semantics(saved, extra):
    """Management's automatic reasoning default must not become an undeclared API field."""
    profile = restore_model_snapshot(saved, "tenant")
    original = profile.model_dump()
    assert "reasoning_effort" not in {rule["key"] for rule in profile.parameter_rules}
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7,
        enable_thinking=True, reasoning_effort="auto", extra_body=extra)
    effective = compile_model_runtime_profile(model, SimpleNamespace(
        context_budget_snapshot=None, requested_output_tokens=None))
    assert "reasoning_effort" not in effective.parameter_values
    assert all(item["path"] != "/reasoning_effort" for item in effective.extra_api_parameters)
    assert effective.parameter_values["enable_thinking"] is True
    assert profile.model_dump() == original
    assert model.reasoning_effort == "auto"


@pytest.mark.parametrize("effort", ["low", "high", "none"])
def test_explicit_effort_without_saved_rule_remains_rejected(saved, effort):
    profile = restore_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7,
        enable_thinking=True, reasoning_effort=effort)
    with pytest.raises(ValueError, match="MODEL_OUTLET_OVERRIDE_UNDECLARED"):
        compile_model_runtime_profile(model, SimpleNamespace(
            context_budget_snapshot=None, requested_output_tokens=None))


@pytest.mark.parametrize("sibling", [False, True])
def test_nested_thinking_binding_preserves_unrelated_empty_and_null_parameters(saved, sibling):
    profile = restore_model_snapshot(saved, "tenant")
    data = profile.model_dump()
    rule = next(rule for rule in data["parameter_rules"] if rule["key"] == "enable_thinking")
    rule["api_binding"].update(path="/thinking/type", transform_ref="thinking_toggle_v1")
    profile = type(profile).model_validate(data)
    extra = {"thinking": {"type": "enabled"}, "custom": {"a/b~x": None}}
    if sibling:
        extra["thinking"]["extra"] = {}
    original = deepcopy(extra)
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7, extra_body=extra)
    result = compile_model_runtime_profile(model, SimpleNamespace(
        context_budget_snapshot=None, requested_output_tokens=None))
    assert result.parameter_values["enable_thinking"] is True
    assert {item["path"]: item["value"] for item in result.extra_api_parameters} == (
        {"/thinking/extra": {}, "/custom/a~1b~0x": None} if sibling else {"/custom/a~1b~0x": None})
    assert extra == original and model.extra_body == original
    assert profile.parameter_values["enable_thinking"] is False
    model.extra_body["thinking"]["type"] = "invalid"
    with pytest.raises(ValueError, match="MODEL_OUTLET_THINKING_FORMAT_INVALID"):
        compile_model_runtime_profile(model, SimpleNamespace(context_budget_snapshot=None, requested_output_tokens=None))


def test_unbound_parameter_cannot_override_saved_value_and_bound_profile_is_required(saved):
    from management.services.model.runtime_options import compile_bound_model_profile

    profile = restore_model_snapshot(saved, "tenant")
    data = profile.model_dump()
    rule = next(rule for rule in data["parameter_rules"] if rule["key"] == "enable_thinking")
    rule.pop("api_binding")
    rule["editable"] = False
    rule["visible"] = False
    profile = type(profile).model_validate(data)
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7, enable_thinking=True)
    config = SimpleNamespace(context_budget_snapshot=None, requested_output_tokens=None)
    with pytest.raises(ValueError, match="MODEL_OUTLET_OVERRIDE_UNBOUND"):
        compile_model_runtime_profile(model, config)
    model.resolved_profile = None
    with pytest.raises(ValueError, match="MODEL_OUTLET_PROVISIONING_REQUIRED"):
        compile_bound_model_profile(model, config)
