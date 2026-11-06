# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Custom-provider thought controls reach the real HTTP boundary unchanged."""
import pytest
from contracts.model import ModelOutletCreateRequest, ModelOutletPatchRequest
from management.services.model.profiles import build_outlet_draft, apply_outlet_patch
from management.services.conversation.model_preferences import merge_model_preferences


@pytest.mark.parametrize("preset,path", [(None,"enable_thinking"), ("thinking_type","thinking"), ("chat_template","chat_template_kwargs")])
@pytest.mark.parametrize("enabled", [False, True])
def test_custom_provider_shutdown_configuration_reaches_peer(peer, request, preset, path, enabled):
    main = request.module
    service, call, _, limiter, journal, _ = main.setup(peer, "normal")
    root, _ = peer
    profile, _ = build_outlet_draft(ModelOutletCreateRequest(
        request_model_id="qwen3.8-flash", provider_info={"base_url": root+"/v1?scenario=normal"},
        api_key="dummy-loopback", thinking_control=preset,
        parameter_values={"enable_thinking": enabled}), "loopback-tenant")
    profile = apply_outlet_patch(profile, ModelOutletPatchRequest(
        expected_revision=1, parameter_values={"enable_thinking": not enabled}))
    profile = merge_model_preferences(profile, {"enable_thinking": enabled})
    original = profile.model_dump()
    result = service.invoke(call, profile)
    assert result.content_parts == [{"type":"text", "text":"answer"}]
    actual = main.records(journal)
    assert len(actual) == 1
    expected = enabled if path == "enable_thinking" else ({"type":"enabled" if enabled else "disabled"} if path == "thinking" else {"enable_thinking":enabled})
    assert actual[0]["body"][path] == expected
    if path != "enable_thinking":
        assert "enable_thinking" not in actual[0]["body"]
    assert profile.model_dump() == original
    assert not limiter._entries
