# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy LLM snapshots retain effective values without changing non-LLM records."""

from copy import deepcopy

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references
from management.services.model.outlet_migration import build_legacy_outlet_snapshot


def row(**changes):
    result = {"model_id": 42, "tenant_id": "tenant", "model_type": "llm", "model_name": "custom-model",
              "model_factory": "custom", "base_url": "https://custom.invalid/v1", "display_name": "chosen",
              "temperature": None, "top_p": None, "api_key": "controlled-key", "extra_params": None}
    result.update(changes)
    return result


def build(record, capability=None):
    return build_legacy_outlet_snapshot(record, legacy_capability=capability, migrated_at="2026-10-14T12:00:00Z")


def wire(profile):
    request = ModelRequest(request_id="migration", outlet_id=profile.outlet_id, config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "Hello"}])])
    return OpenAIChatAdapter().prepare_http_request(request, profile).json_body


def test_unmatched_model_automatically_uses_agreed_defaults_and_retains_identity():
    original = row()
    before = deepcopy(original)
    profile = build(original)
    assert profile.outlet_id == 42 and profile.identity.request_model_id == "custom-model"
    assert profile.capabilities.context.combined_window == 200000
    assert profile.capabilities.context.input_limit is profile.capabilities.context.output_limit is None
    assert profile.capabilities.tools.status == profile.capabilities.reasoning.status == "unsupported"
    metadata = profile.provenance.provider_metadata["migration"]
    assert metadata["unmatched_atoms"] == ["model", "provider"] and metadata["reviewed_revision"] is None
    assert "controlled-key" not in repr(profile.model_dump()) and original == before


def test_old_explicit_window_and_sampling_values_override_atom_suggestions():
    profile = build(row(model_name="qwen3.5-plus", model_factory="alibaba-cn",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", context_window_tokens=65536,
        max_input_tokens=32000, max_output_tokens=4096, default_output_reserve_tokens=2048,
        temperature=0, top_p=0, ssl_verify=False, timeout_seconds=23))
    assert profile.provider_key == "alibaba-cn" and profile.model_profile_key == "alibaba/qwen3.5-plus"
    assert profile.capabilities.context.combined_window == 65536
    assert profile.capabilities.context.input_limit == 32000 and profile.capabilities.context.output_limit == 4096
    assert profile.context_configuration.output_reserve_tokens == 2048
    assert profile.connection.ssl_verify is False and profile.connection.timeout_seconds == 23
    assert wire(profile)["temperature"] == wire(profile)["top_p"] == 0
    from nexent.core.models.capacity_resolver import resolve_capacity

    legacy_capacity = resolve_capacity(model_id="qwen3.5-plus", provider="alibaba-cn", capability_profiles={},
        operator_overrides={"context_window_tokens": 65536, "max_input_tokens": 32000,
            "max_output_tokens": 4096, "default_output_reserve_tokens": 2048})
    assert legacy_capacity.requested_output_tokens == 2048
    assert wire(profile)["max_tokens"] == legacy_capacity.requested_output_tokens


def test_old_deepseek_toggle_and_custom_nested_body_survive_actual_adapter():
    capability = {"source": "models_dev", "status": "supported", "provider_id": "deepseek"}
    profile = build(row(model_name="deepseek-chat", model_factory="deepseek", base_url="https://api.deepseek.com/v1",
        extra_params={"enable_thinking": True, "__custom__": {"custom_options": {"flag": False, "retries": 0}}}), capability)
    assert profile.parameter_values["enable_thinking"] is True
    body = wire(profile)
    assert body["thinking"] == {"type": "enabled"} and "enable_thinking" not in body
    assert body["custom_options"] == {"flag": False, "retries": 0}
    assert profile.capabilities.reasoning.status == "supported"


def test_disabled_unknown_thinking_remains_conservative_and_keeps_saved_false():
    profile = build(row(extra_params={"enable_thinking": False}))
    assert profile.parameter_values["enable_thinking"] is False
    assert profile.capabilities.reasoning.status == "unsupported"
    assert wire(profile)["enable_thinking"] is False


def test_auto_effort_is_preserved_without_sending_an_auto_wire_field():
    profile = build(row(extra_params={"reasoning_effort": "auto"}))
    assert profile.parameter_values["reasoning_effort"] == "auto"
    assert "reasoning_effort" not in wire(profile)
    assert profile.provenance.provider_metadata["migration"]["unbound_legacy_parameters"] == ["reasoning_effort"]


def test_repo_model_identity_and_legacy_large_output_alias_use_current_rules():
    profile = build(row(model_repo="repo", model_name="exact", max_tokens=65536))
    assert profile.identity.request_model_id == "repo/exact"
    assert wire(profile)["max_tokens"] == 4096


def test_already_saved_row_is_not_recombined_with_current_toml(monkeypatch):
    profile = build(row())
    saved = encode_resolved_model_profile(profile, registered_references=model_service_references())
    import management.services.model.outlet_migration as service
    monkeypatch.setattr(service, "build_outlet_draft", lambda *args, **kwargs: pytest.fail("Saved rows must not recompose"))
    assert build(saved) == profile


@pytest.mark.parametrize("changes", [{"model_type": "vlm"}, {"model_type": "embedding"},
    {"base_url": "file:///private/secret"}, {"extra_params": {"__custom__": {"messages": []}}},
    {"context_window_tokens": 0}])
def test_invalid_or_out_of_scope_record_is_rejected_without_echoing_values(changes):
    with pytest.raises(ModelOutletValidationError) as error:
        build(row(**changes))
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("extra", [{"enable_thinking": True, "reasoning_budget_tokens": None},
                                {"enable_thinking": True, "reasoning_budget_tokens": -1}])
def test_legacy_unused_budget_values_are_preserved_without_new_wire_fields(extra):
    profile = build(row(extra_params=extra))
    assert profile.parameter_values["reasoning_budget_tokens"] == extra["reasoning_budget_tokens"]
    assert "thinking_budget" not in wire(profile) and "reasoning_budget_tokens" not in wire(profile)


def test_unmatched_snapshot_declares_legacy_runtime_options_without_setting_defaults():
    from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions

    profile = build(row())
    configured = LegacyInvocationOptions({"max_output_tokens": 512}, stop_sequences=["Observation:"]).resolve(profile)
    assert wire(configured)["max_tokens"] == 512
    assert wire(configured)["stop"] == ["Observation:"]
    assert "max_output_tokens" not in profile.parameter_values


@pytest.mark.parametrize("dry_run", [False, True])
def test_runner_advances_past_failures_and_does_not_repeat_a_batch(monkeypatch, dry_run):
    import sys
    from types import ModuleType
    from unittest.mock import Mock
    import management.services.model.outlet_migration as service

    database = ModuleType("management.db.model.outlets")
    database.migrate_legacy_model_records = Mock(side_effect=[
        [{"model_id": 2, "tenant_id": "tenant", "status": "failed", "category": "LEGACY_OUTLET_INVALID"}],
        [{"model_id": 3, "tenant_id": "tenant", "status": "ready" if dry_run else "migrated", "category": None}], [],
    ])
    catalog = ModuleType("configs.model_catalog_loader")
    catalog.resolve_reasoning_capability = Mock(return_value=None)
    monkeypatch.setitem(sys.modules, "management.db.model.outlets", database)
    monkeypatch.setitem(sys.modules, "configs.model_catalog_loader", catalog)
    result = service.migrate_legacy_outlets(dry_run=dry_run, batch_size=1)
    assert result["failed"] == 1
    assert result["ready" if dry_run else "migrated"] == 1
    calls = database.migrate_legacy_model_records.call_args_list
    assert [call.kwargs["after_model_id"] for call in calls] == [0, 2, 3]
    assert all(call.kwargs["dry_run"] is dry_run for call in calls)
    constructor = calls[0].args[0]
    profile = constructor(row())
    assert profile.outlet_id == 42 and profile.capabilities.context.combined_window == 200000
    catalog.resolve_reasoning_capability.assert_called_once_with(
        "custom-model", "https://custom.invalid/v1", "custom", allow_gateway_fallback=False)
