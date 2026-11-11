# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Long-text input fits both the separate cap and the shared output window."""

from copy import deepcopy

import pytest
from nexent.core.gateway.modality.llm.openai import OpenAILongContextLLMAdapter
from nexent.core.gateway.model_context import LongContextLLMContext


def build(openai_profile, window, input_limit, output_limit, requested, key="max_output_tokens"):
    data = openai_profile.model_dump()
    data["capabilities"]["context"].update(
        combined_window=window, input_limit=input_limit, output_limit=output_limit,
    )
    for alias in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
        data["parameter_values"].pop(alias, None)
    if requested is not None:
        if key != "max_output_tokens":
            rule = deepcopy(next(rule for rule in data["parameter_rules"] if rule["key"] == "max_output_tokens"))
            rule["key"] = key
            rule["api_binding"]["path"] = "/" + key
            data["parameter_rules"] = [rule for rule in data["parameter_rules"] if rule["key"] != "max_output_tokens"]
            data["parameter_rules"].append(rule)
        data["parameter_values"][key] = requested
    profile = type(openai_profile).model_validate(data)
    adapter = OpenAILongContextLLMAdapter(LongContextLLMContext(
        model_name=profile.identity.request_model_id, base_url=profile.connection.base_url,
        api_key="controlled-key", modality="llm_long_context", factory="openai",
        tenant_id=profile.identity.tenant_id, resolved_profile=profile,
    ))
    adapter._build_model()
    return adapter


@pytest.mark.parametrize("window,input_limit,output_limit,requested,expected", [
    (8192, 7000, 4096, 4096, 4096),
    (8192, 2000, 4096, 4096, 2000),
    (8192, None, 4096, 4096, 4096),
    (None, 7000, None, 4096, 7000),
    (8192, 7000, 4096, None, 4096),
    (None, 7000, None, None, 7000),
])
def test_long_text_reserves_output_and_intersects_limits(
    openai_profile, window, input_limit, output_limit, requested, expected,
):
    adapter = build(openai_profile, window, input_limit, output_limit, requested)
    assert adapter.max_context_tokens == expected
    assert adapter._model.profile.parameter_values.get("max_output_tokens") == requested


@pytest.mark.parametrize("key", ["max_output_tokens", "max_tokens", "max_completion_tokens"])
def test_long_text_effective_output_alias_and_prompt_buffer(openai_profile, mocker, key):
    adapter = build(openai_profile, 8192, 7000, 4096, 4096, key)
    mocker.patch.object(adapter, "count_tokens", side_effect=lambda text: len(text.split()))
    mocker.patch.object(adapter, "truncate_text", side_effect=lambda text, limit: " ".join(text.split()[:limit]))
    messages, percent = adapter.prepare_long_text_message("token " * 10000, "system", "analyze")
    input_tokens = sum(len(message["content"].split()) for message in messages)
    assert input_tokens == 3996
    assert input_tokens + 4096 <= 8192
    assert percent == "39"


@pytest.mark.parametrize("window,input_limit,output_limit,requested", [
    (4096, None, 4096, 4096),
    (2048, None, 4096, 4096),
    (8192, None, None, None),
])
def test_long_text_rejects_no_safe_shared_window_before_model(
    openai_profile, mocker, window, input_limit, output_limit, requested,
):
    sender = mocker.patch("nexent.core.model_service.compatibility.legacy_chat_model.LegacyChatModel.from_profile")
    with pytest.raises(ValueError):
        build(openai_profile, window, input_limit, output_limit, requested)
    sender.assert_not_called()
