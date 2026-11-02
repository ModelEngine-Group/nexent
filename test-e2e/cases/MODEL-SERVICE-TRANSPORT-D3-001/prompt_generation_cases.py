# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Backend auxiliary prompt flow over the actual saved-outlet gateway and HTTP sender."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from contracts.errors.exceptions import AppException
from nexent.core.gateway.modality.llm.openai import OpenAILLMAdapter
from nexent.core.gateway.model_context import LLMContext
from nexent.core.model_service.profiles.outlet_storage import (
    encode_resolved_model_profile,
)
from nexent.core.model_service.registry import model_service_references


@pytest.mark.parametrize("scenario,expected", [("stream", "中间正文"), ("auth", ""), ("visible_disconnect", "partial")])
def test_auxiliary_prompt_uses_saved_outlet_http_without_outer_retry(peer, request, monkeypatch, scenario, expected):
    main = request.module
    _, _, profile, _, journal, _ = main.setup(peer, scenario)
    row = encode_resolved_model_profile(profile, registered_references=model_service_references())
    gateway = OpenAILLMAdapter(LLMContext(
        model_name=profile.identity.request_model_id, base_url=profile.connection.base_url,
        api_key="dummy-loopback", modality="llm", factory="openai",
        tenant_id=profile.identity.tenant_id, resolved_profile=profile,
    ))

    def read(model_id, tenant_id):
        assert model_id == 42 and tenant_id == profile.identity.tenant_id
        return row

    def resolve(record, tenant_id, **kwargs):
        assert record is row and tenant_id == profile.identity.tenant_id
        assert "temperature" not in kwargs and "top_p" not in kwargs
        return gateway

    for name, values in {
        "consts.const": {"MESSAGE_ROLE": {"SYSTEM": "system", "USER": "user"},
                         "THINK_START_PATTERN": "<think>", "THINK_END_PATTERN": "</think>"},
        "management.db.model.repository": {"get_model_by_model_id": read},
        "management.services.model.adapter": {"get_llm_adapter_from_config": resolve},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[3] / "backend/management/services/model/invocation.py"
    spec = importlib.util.spec_from_file_location("_prompt_flow_d3", path)
    prompt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prompt)
    callbacks = []
    if scenario == "stream":
        assert prompt.call_llm_for_system_prompt(42, "hello", "system", callbacks.append,
                                               profile.identity.tenant_id) == expected
    else:
        with pytest.raises(AppException):
            prompt.call_llm_for_system_prompt(42, "hello", "system", callbacks.append, profile.identity.tenant_id)
    assert (callbacks[-1] if callbacks else "") == expected
    actual = main.records(journal, scenario=scenario)
    assert len(actual) == 1
    assert actual[0]["body"]["messages"] == [
        {"role": "system", "content": "system"}, {"role": "user", "content": "hello"},
    ]
    assert actual[0]["body"]["enable_thinking"] is False
    assert gateway._model.last_attempt_number == 1


def test_long_text_preparation_uses_saved_outlet_real_http(peer, request, monkeypatch):
    from nexent.core.gateway.model_context import LongContextLLMContext
    from nexent.core.gateway.modality.llm.openai import OpenAILongContextLLMAdapter

    main = request.module
    scenario = "long_text"
    _, _, profile, _, journal, _ = main.setup(peer, scenario)
    adapter = OpenAILongContextLLMAdapter(LongContextLLMContext(
        model_name=profile.identity.request_model_id, base_url=profile.connection.base_url,
        api_key="dummy-loopback", modality="llm_long_context", factory="openai",
        tenant_id=profile.identity.tenant_id, resolved_profile=profile,
    ))
    monkeypatch.setattr(adapter, "_get_tokenizer", lambda: None)
    response, percentage = adapter.analyze_long_text("selected text", "instructions", "analyze")
    assert response.content == "中间正文" and percentage == "100"
    actual = main.records(journal, scenario=scenario)
    assert len(actual) == 1
    assert actual[0]["body"]["messages"] == [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "analyze\n\nselected text"},
    ]
    assert actual[0]["body"]["enable_thinking"] is False
    assert "max_tokens" not in actual[0]["body"]
    assert adapter._model.profile == profile


@pytest.mark.parametrize("enabled,expected", [(True, "enabled"), (False, "disabled")])
def test_saved_parameter_transform_reaches_actual_http_body(peer, request, enabled, expected):
    from nexent.core.model_service.profiles.outlet_storage import decode_resolved_model_profile

    main = request.module
    scenario = "parameter-transform"
    service, call, profile, limiter, journal, _ = main.setup(peer, scenario)
    data = profile.model_dump()
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = 42
    data["parameter_values"]["enable_thinking"] = enabled
    rule = next(item for item in data["parameter_rules"] if item["key"] == "enable_thinking")
    rule["api_binding"] = {"path": "/thinking/type", "transform_ref": "thinking_toggle_v1", "transform_version": 1}
    profile = profile.__class__.model_validate(data)
    refs = model_service_references()
    row = encode_resolved_model_profile(profile, registered_references=refs)
    restored = decode_resolved_model_profile(row, registered_references=refs)
    service.invoke(call.model_copy(update={"outlet_id": 42}), restored)
    actual = main.records(journal, scenario=scenario)
    assert len(actual) == 1
    assert actual[0]["body"]["thinking"] == {"type": expected}
    assert "enable_thinking" not in actual[0]["body"]
    assert restored.parameter_values["enable_thinking"] is enabled
    assert not limiter._entries


@pytest.mark.parametrize("enabled", [True, False])
def test_migrated_legacy_configuration_reaches_shared_http_without_extra_defaults(peer, request, enabled):
    from management.services.model.outlet_migration import build_legacy_outlet_snapshot

    main = request.module
    scenario = "legacy-migration"
    service, call, _, limiter, journal, _ = main.setup(peer, scenario)
    root, _ = peer
    record = {"model_id": 42, "tenant_id": "loopback-tenant", "model_type": "llm",
        "model_name": "unlisted-legacy-model", "model_factory": "custom", "api_key": "dummy-loopback",
        "base_url": f"{root}/v1?scenario={scenario}", "temperature": 0, "top_p": None,
        "extra_params": {"enable_thinking": enabled, "__custom__": {"custom_options": {"flag": False, "count": 0}}}}
    profile = build_legacy_outlet_snapshot(record, legacy_capability=None, migrated_at="2026-10-14T12:00:00Z")
    service.invoke(call.model_copy(update={"outlet_id": 42}), profile)
    actual = main.records(journal, scenario=scenario)
    assert len(actual) == 1
    body = actual[0]["body"]
    assert body["model"] == "unlisted-legacy-model" and body["temperature"] == 0 and body["top_p"] is None
    assert body["enable_thinking"] is enabled
    assert body["custom_options"] == {"flag": False, "count": 0}
    assert "thinking_budget" not in body and "max_tokens" not in body
    assert profile.capabilities.context.combined_window == 200000
    assert profile.provenance.provider_metadata["migration"]["reviewed_revision"] is None
    assert not limiter._entries
