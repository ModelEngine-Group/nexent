# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Historical output settings cannot reintroduce a completion length limit."""

import pytest
from nexent.core.model_service.adapters.openai_chat import OpenAIChatAdapter
from nexent.core.model_service.compatibility.invocation_options import LegacyInvocationOptions
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


@pytest.mark.parametrize("stream", [False, True])
def test_ac001_saved_and_extra_limits_are_omitted_from_wire(protocol_profile, stream):
    data = protocol_profile.model_dump(mode="json")
    data["parameter_values"]["max_output_tokens"] = 4096
    data["extra_api_parameters"].append({"path": "/max_completion_tokens", "value": 2048})
    profile = ResolvedModelProfile.model_validate(data)
    request = ModelRequest(request_id="omit-limits", outlet_id=profile.outlet_id,
        config_revision=profile.config_revision, stream=stream,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "hello"}])])
    body = OpenAIChatAdapter().prepare_http_request(request, profile).json_body
    assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(body)
    assert body["messages"]


def test_ac002_legacy_output_override_is_ignored_without_changing_sampling(protocol_profile):
    result = LegacyInvocationOptions({"max_tokens": 4096}).resolve(protocol_profile)
    assert result.parameter_values.get("max_output_tokens") != 4096
    assert "max_tokens" not in result.parameter_values
