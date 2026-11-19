# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Qwen streamed tool identities retain their established call binding."""
import json

import pytest
from nexent.core.model_service.adapters.openai_chat import ModelAdapterError
from nexent.core.model_service.adapters.openai_stream import OpenAIStreamDecoder
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.sse import SSEEvent


@pytest.fixture
def stream_request(openai_profile):
    return ModelRequest(
        request_id="qwen-placeholder-regression",
        outlet_id=openai_profile.outlet_id,
        config_revision=openai_profile.config_revision,
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "hello"}])],
        stream=True,
    )


def chunk(call=None, finish=None):
    return SSEEvent(json.dumps({"id": "response", "model": "model", "choices": [{
        "index": 0, "delta": {"tool_calls": [call]} if call else {}, "finish_reason": finish}]}))


def test_qwen_empty_id_continuation_preserves_bound_call(openai_profile, stream_request):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    decoder.push(chunk({"index": 0, "id": "bound-call", "type": "function",
        "function": {"name": "search", "arguments": ""}}))
    decoder.push(chunk({"index": 0, "id": "", "type": "function", "function": {"arguments": ""}}))
    decoder.push(chunk({"index": 0, "function": {"arguments": '{"query":"owned"}'}}))
    decoder.push(chunk(finish="tool_calls"))
    completed = decoder.push(SSEEvent("[DONE]"))[0].message
    assert len(completed.tool_calls) == 1
    assert completed.tool_calls[0].provider_call_id == "bound-call"
    assert completed.tool_calls[0].name == "search"
    assert completed.tool_calls[0].parsed_arguments == {"query": "owned"}


@pytest.mark.parametrize("identity", ["other-call", " ", 0])
def test_real_identity_conflicts_still_fail(openai_profile, stream_request, identity):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    decoder.push(chunk({"index": 0, "id": "bound-call", "function": {"name": "search", "arguments": ""}}))
    with pytest.raises(ModelAdapterError, match="MODEL_STREAM_IDENTITY_CONFLICT"):
        decoder.push(chunk({"index": 0, "id": identity, "function": {"arguments": "{}"}}))


def test_empty_id_cannot_establish_a_tool_call(openai_profile, stream_request):
    decoder = OpenAIStreamDecoder(stream_request, openai_profile)
    with pytest.raises(ModelAdapterError, match="MODEL_STREAM_IDENTITY_CONFLICT"):
        decoder.push(chunk({"index": 0, "id": "", "function": {"name": "search", "arguments": "{}"}}))
