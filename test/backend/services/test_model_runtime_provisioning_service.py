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
from management.services.model.runtime_provisioning import (
    build_runtime_outlet_snapshot,
    model_source_fingerprint,
)
from management.services.model.runtime_snapshot import restore_runtime_model_snapshot


@pytest.fixture
def record():
    return {"model_id": 7, "tenant_id": "tenant", "model_type": "llm", "model_repo": "",
            "model_name": "qwen3.5-plus", "model_factory": "alibaba-cn", "display_name": "outlet",
            "base_url": "http://127.0.0.1:9999/v1", "api_key": "unit-secret",
            "max_output_tokens": 512, "default_output_reserve_tokens": 256,
            "temperature": .7, "top_p": None, "extra_params": {"enable_thinking": False}}


@pytest.fixture
def saved(record):
    record["runtime_outlet_snapshot"] = build_runtime_outlet_snapshot(record)
    assert "row" in record["runtime_outlet_snapshot"]
    return record


def test_management_snapshot_uses_canonical_codec_without_credentials(saved):
    profile = restore_runtime_model_snapshot(saved, "tenant")
    assert profile.outlet_id == 7 and profile.identity.tenant_id == "tenant"
    assert profile.parameter_values["max_output_tokens"] == 256
    assert profile.parameter_values["temperature"] == .7
    output_rule = next(rule for rule in profile.parameter_rules if rule["key"] == "max_output_tokens")
    assert output_rule["allowed_scopes"] == ["outlet"]
    assert profile.capabilities.tools.status == "supported"
    assert "unit-secret" not in json.dumps(saved["runtime_outlet_snapshot"])


def test_unchanged_management_write_and_runtime_do_not_recompose(saved, mocker):
    mocker.patch("management.services.model.profile.get_model_profile_catalog", side_effect=AssertionError)
    assert build_runtime_outlet_snapshot(saved) == saved["runtime_outlet_snapshot"]
    assert restore_runtime_model_snapshot(saved, "tenant").config_revision == 1


def test_changed_settings_create_next_revision_without_mutating_prior_snapshot(saved, mocker):
    before = deepcopy(saved)
    mocker.patch("management.services.model.profile.get_model_profile_catalog", side_effect=AssertionError)
    changed = {**saved, "temperature": .2}
    changed["runtime_outlet_snapshot"] = build_runtime_outlet_snapshot(changed)
    assert restore_runtime_model_snapshot(changed, "tenant").config_revision == 2
    assert restore_runtime_model_snapshot(saved, "tenant").parameter_values["temperature"] == .7
    assert saved == before
    assert restore_runtime_model_snapshot(changed, "tenant").parameter_rules == restore_runtime_model_snapshot(saved, "tenant").parameter_rules
    assert restore_runtime_model_snapshot(changed, "tenant").capabilities == restore_runtime_model_snapshot(saved, "tenant").capabilities


@pytest.mark.parametrize("field,value", [("base_url", "http://other/v1"), ("temperature", .1), ("api_key", "")])
def test_unsynchronized_writes_fail_closed(saved, field, value):
    saved[field] = value
    with pytest.raises(ValueError, match="STALE_SNAPSHOT"):
        restore_runtime_model_snapshot(saved, "tenant")
    assert restore_runtime_model_snapshot(saved, "tenant", strict=False) is None


def test_connectivity_and_key_rotation_do_not_change_policy_fingerprint(saved):
    assert model_source_fingerprint(saved) == model_source_fingerprint(
        {**saved, "api_key": "rotated-secret", "connect_status": "available"})


def test_cross_tenant_and_identity_tampering_rejected(saved):
    with pytest.raises(ValueError, match="TENANT_MISMATCH"):
        restore_runtime_model_snapshot(saved, "other")
    saved["runtime_outlet_snapshot"]["row"]["model_id"] = 8
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        restore_runtime_model_snapshot(saved, "tenant")


def test_unknown_outlet_uses_text_and_bad_outlet_has_safe_diagnostic(record):
    unknown = build_runtime_outlet_snapshot({**record, "model_name": "operator-custom", "model_factory": "custom"})
    assert unknown["row"]["native_tool_call_supported"] is False
    failed = build_runtime_outlet_snapshot({**record, "base_url": "invalid"})
    assert failed["error"] == "MODEL_OUTLET_PROVISIONING_FAILED"
    assert "unit-secret" not in json.dumps(failed)


def test_non_llm_has_no_runtime_profile(record):
    assert build_runtime_outlet_snapshot({**record, "model_type": "embedding"}) is None


def test_compile_request_values_into_detached_saved_rules(saved):
    profile = restore_runtime_model_snapshot(saved, "tenant")
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
    profile = restore_runtime_model_snapshot(saved, "tenant")
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

    profile = restore_runtime_model_snapshot(saved, "tenant")
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
    profile = restore_runtime_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7, top_p=None,
        extra_body={"max_tokens": 99}, enable_thinking=False)
    config = SimpleNamespace(context_budget_snapshot=SimpleNamespace(requested_output_tokens=128),
                             requested_output_tokens=None)
    with pytest.raises(ValueError, match="LEGACY_PARAMETER_CONFLICT"):
        compile_model_runtime_profile(model, config)


def test_corrupt_or_oversized_envelope_cannot_be_treated_as_ready(saved):
    saved["runtime_outlet_snapshot"]["row"]["protocol_id"] = "unregistered"
    assert restore_runtime_model_snapshot(saved, "tenant", strict=False) is None
    repaired = build_runtime_outlet_snapshot(saved)
    assert "row" in repaired and repaired["revision"] == 2
    saved["runtime_outlet_snapshot"] = repaired
    saved["runtime_outlet_snapshot"]["padding"] = "x" * (1024 * 1024)
    with pytest.raises(ValueError, match="STALE_SNAPSHOT"):
        restore_runtime_model_snapshot(saved, "tenant")


def test_custom_values_use_saved_bindings_and_preserve_empty_objects(saved):
    profile = restore_runtime_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7, top_p=None,
        extra_body={"enable_thinking": True, "custom": {}}, enable_thinking=False)
    effective = compile_model_runtime_profile(model, SimpleNamespace(context_budget_snapshot=None,
                                                                     requested_output_tokens=None))
    assert effective.parameter_values["enable_thinking"] is True
    assert effective.extra_api_parameters == [{"path": "/custom", "value": {}}]


def test_clearing_an_explicit_capacity_column_does_not_restore_a_catalog_default(record):
    record["context_window_tokens"] = 300000
    record["runtime_outlet_snapshot"] = build_runtime_outlet_snapshot(record)
    assert restore_runtime_model_snapshot(record, "tenant").capabilities.context.combined_window == 300000
    record["context_window_tokens"] = None
    record["runtime_outlet_snapshot"] = build_runtime_outlet_snapshot(record)
    assert restore_runtime_model_snapshot(record, "tenant").capabilities.context.combined_window is None


def test_record_factory_and_request_overlay_preserve_trusted_outlet(saved, monkeypatch):
    """The refactored record factory must retain the Jiuwen outlet binding."""
    from management.services.model.run_bindings import create_model_config_from_record
    # MCP transport is unrelated to the in-memory root preference overlay.
    monkeypatch.setitem(sys.modules, "management.services.mcp.service",
                        SimpleNamespace(get_remote_mcp_server_list=Mock()))
    from management.services.agent.preparation.run import apply_root_model_preferences
    from management.services.model.runtime_options import compile_bound_model_profile

    canonical_record = {**saved, **saved["runtime_outlet_snapshot"]["row"]}
    base = create_model_config_from_record(canonical_record, "tenant")
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
    profile = restore_runtime_model_snapshot(saved, "tenant")
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
    profile = restore_runtime_model_snapshot(saved, "tenant")
    model = ModelConfig(cite_name="outlet", model_name=profile.identity.request_model_id,
        url=profile.connection.base_url, resolved_profile=profile, temperature=.7,
        enable_thinking=True, reasoning_effort=effort)
    with pytest.raises(ValueError, match="MODEL_OUTLET_OVERRIDE_UNDECLARED"):
        compile_model_runtime_profile(model, SimpleNamespace(
            context_budget_snapshot=None, requested_output_tokens=None))
