# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Every selected China combination has an executable configuration and wire binding."""

import pytest
from contracts.model import ModelProfilePreviewRequest
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from management.services.model.profiles import build_outlet_draft, get_model_profile_catalog

CATALOG = get_model_profile_catalog()


@pytest.mark.parametrize("key", sorted(CATALOG.provider_models))
def test_selected_combination_resolves_and_renders_declared_reasoning_controls(key):
    provider, model = key.split("/", 1)
    atom = CATALOG.providers[provider]
    request = ModelProfilePreviewRequest(
        provider_profile={"key": provider, "revision": atom.revision},
        provider_info={"base_url": atom.source.connection_suggestions["base_url"]},
        request_model_id=model,
    )
    profile, _ = build_outlet_draft(request, "catalog-test-tenant")
    assert profile.identity.request_model_id == model
    assert profile.provider_key == provider
    parameters = {}
    for control in profile.capabilities.reasoning.controls or []:
        if control.mode == "toggle":
            parameters[control.parameter_key] = True
        elif control.mode == "effort":
            parameters[control.parameter_key] = control.values[-1]
        else:
            parameters[control.parameter_key] = control.min if control.min is not None else 1
    configured = LegacyInvocationOptions(parameters).resolve(profile)
    message = ModelRequest(
        request_id="catalog-wire-check", outlet_id=profile.outlet_id, config_revision=profile.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "test"}])],
    )
    body = OpenAIChatAdapter().prepare_http_request(message, configured).json_body
    assert body["model"] == model
    rules = {rule["key"]: rule for rule in profile.parameter_rules}
    for name, value in parameters.items():
        binding = rules[name]["api_binding"]
        actual = body
        for part in binding["path"].strip("/").split("/"):
            actual = actual[part]
        assert actual == ("enabled" if binding["transform_ref"] == "thinking_toggle_v1" else value)
