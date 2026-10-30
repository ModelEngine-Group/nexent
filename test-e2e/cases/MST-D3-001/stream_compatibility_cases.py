# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual HTTP compatibility and diagnostic boundaries."""

import pytest
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("scenario", ["compatible_duplicate", "compatible_eof", "vllm_023_tail"])
@pytest.mark.asyncio
async def test_compatible_stream_tails_complete_once_through_actual_http(peer, asynchronous, scenario):
    from .test import setup, records
    service, request, profile, limiter, journal, _ = setup(peer, scenario)
    request = request.model_copy(update={"stream": True})
    if asynchronous:
        async with service.astream(request, profile) as stream:
            events = [event async for event in stream]
    else:
        with service.stream(request, profile) as stream:
            events = list(stream)
    assert [event.type for event in events].count("usage") == 1
    completed = [event for event in events if event.type == "message_completed"]
    assert len(completed) == 1 and completed[0].message.usage.total_tokens == (244 if scenario == "vllm_023_tail" else 15)
    assert not any(event.type == "error" for event in events)
    assert len(records(journal, kind="request", scenario=scenario)) == 1 and not limiter._entries


@pytest.mark.parametrize("scenario", ["error_json", "error_text"])
def test_http_detail_reaches_agent_bridge_without_credentials_or_extra_retry(peer, scenario):
    from nexent.core.model_errors import ModelInvocationTerminalError
    from nexent.core.model_service.service import ModelRequestRetryPolicy

    from .test import setup, records
    service, _, profile, limiter, journal, _ = setup(
        peer, scenario, retry_policy=ModelRequestRetryPolicy(max_attempts=1))
    model = LegacyChatModel(profile, service)
    with pytest.raises(ModelInvocationTerminalError) as caught:
        model.generate([{"role": "user", "content": "hello"}])
    message = caught.value.safe_message("zh")
    assert "top_p must be 0.95" in message and "dummy-loopback" not in message
    assert ("(400)" if scenario == "error_json" else "(500)") in message
    assert len(records(journal, kind="request", scenario=scenario)) == 1 and not limiter._entries


@pytest.mark.parametrize("scenario", ["vllm_023_tail", "late_content"])
def test_agent_bridge_uses_vllm_tail_and_shared_localized_errors(peer, scenario):
    from nexent.core.model_errors import ModelInvocationTerminalError
    from .test import setup

    service, _, profile, limiter, _, _ = setup(peer, scenario)
    model = LegacyChatModel(profile, service)
    if scenario == "vllm_023_tail":
        result = model.generate([{"role": "user", "content": "Hello"}])
        assert "提供帮助。" in result.content
        assert model.last_output_token_count == 231
    else:
        with pytest.raises(ModelInvocationTerminalError) as caught:
            model.generate([{"role": "user", "content": "Hello"}])
        assert "新增正文" in caught.value.safe_message("zh")
        assert "additional content" in caught.value.safe_message("en")
        assert "continued generating" not in caught.value.safe_message("zh")
    assert not limiter._entries
