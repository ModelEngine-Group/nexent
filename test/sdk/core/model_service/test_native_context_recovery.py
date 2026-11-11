# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native bridge observes the request actually completed after service rebuild."""

from contextlib import contextmanager

import pytest
from nexent.core.agents.native_model_service import NativeServiceModel
from nexent.core.context_runtime.usage import request_characters
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.contracts import AssistantMessage, ModelEvent, TokenUsage
from test_native_service_model import native_profile as native_profile  # noqa: PLC0414


def test_native_service_rebuild_and_usage_are_bound_to_replacement(native_profile):
    initial = [{"role": "user", "content": "ORIGINAL " * 50}]
    rebuilt = [{"role": "user", "content": "PROTECTED fact"}]
    seen = []

    class Service:
        @contextmanager
        def stream(self, request, profile, **kwargs):
            replacement = kwargs["request_rebuild"](None)
            seen.append(replacement)
            assert replacement.request_id == request.request_id
            message = AssistantMessage(content_parts=[{"type": "text", "text": "Done"}],
                finish_reason="stop", usage=TokenUsage(input_tokens=17, output_tokens=2, origin="provider"))
            yield iter([ModelEvent(request_id=request.request_id, message_id=message.message_id,
                sequence=1, attempt=2, type="message_completed", message=message, finish_reason="stop")])

    delegate = LegacyChatModel(native_profile, Service())
    answer = NativeServiceModel(delegate).generate(initial, context_rebuild=lambda: rebuilt)
    assert answer.content == "Done"
    assert seen[0].messages[-1].content_parts[0]["text"] == "PROTECTED fact"
    observation = delegate.last_context_observation
    assert observation.input_tokens == 17 and observation.attempt == 2
    assert observation.input_characters == request_characters(rebuilt, [])


@pytest.mark.parametrize("callback", [42, "invalid"])
def test_native_rebuild_callback_is_runtime_control_not_provider_parameter(native_profile, callback):
    class NoInference:
        def stream(self, *args, **kwargs):
            raise AssertionError("Invalid control must be rejected before inference")

    model = NativeServiceModel(LegacyChatModel(native_profile, NoInference()))
    with pytest.raises(TypeError, match="synchronous callback"):
        model.generate([{"role": "user", "content": "Task"}], context_rebuild=callback)


def test_native_rebuild_rejects_async_callback(native_profile):
    async def rebuild():
        return []

    model = NativeServiceModel(LegacyChatModel(native_profile, object()))
    with pytest.raises(TypeError, match="synchronous callback"):
        model.generate([{"role": "user", "content": "Task"}], context_rebuild=rebuild)
