"""Verify one system message and one text block at model request boundaries."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from smolagents.models import ChatMessage

from nexent.core.models.message_utils import merge_system_messages
from nexent.core.models.openai_llm import OpenAIModel


@pytest.mark.parametrize("as_chat_message", [False, True])
def test_merge_system_fragments_into_one_text_block(as_chat_message):
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "identity"}]},
        {"role": "system", "content": [{"type": "text", "text": "duty"}]},
        {"role": "user", "content": "question"},
        {"role": "system", "content": [{"type": "text", "text": "protocol"}]},
    ]
    if as_chat_message:
        messages = [ChatMessage.from_dict(message) for message in messages]
    original = deepcopy(messages)
    result = merge_system_messages(messages)
    assert len(result) == 2
    system = result[0].__dict__ if as_chat_message else result[0]
    assert system["role"] == "system"
    assert system["content"] == [{"type": "text", "text": "identity\n\nduty\n\nprotocol"}]
    assert result[1] == messages[2]
    assert messages == original
    assert merge_system_messages(result) == result


def test_single_system_with_multiple_cached_text_blocks_is_combined():
    result = merge_system_messages([{"role": "system", "content": [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second", "cache_control": {"type": "ephemeral"}},
    ]}])
    assert result == [{"role": "system", "content": [
        {"type": "text", "text": "first\n\nsecond", "cache_control": {"type": "ephemeral"}},
    ]}]


def test_plain_strings_and_non_system_roles():
    user = {"role": "user", "content": "hello"}
    developer = {"role": "developer", "content": "developer"}
    assert merge_system_messages([]) == []
    assert merge_system_messages([user, developer]) == [user, developer]
    assert merge_system_messages([
        user, {"role": "system", "content": "first"}, developer,
        {"role": "system", "content": "second"},
    ]) == [user, {"role": "system", "content": "first\n\nsecond"}, developer]


def test_media_is_preserved_in_single_system_message():
    media = {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}
    result = merge_system_messages([
        {"role": "system", "content": [media]},
        {"role": "system", "content": "policy"},
    ])
    assert result == [{"role": "system", "content": [media, {"type": "text", "text": "policy"}]}]


def make_model():
    model = object.__new__(OpenAIModel)
    model.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock())))
    model.model_id = "test-model"
    return model


def test_provider_dispatch_has_one_system_text_block():
    model = make_model()
    model._dispatch_chat_completion(messages=[
        {"role": "system", "content": [{"type": "text", "text": "first"}]},
        {"role": "system", "content": [{"type": "text", "text": "second"}]},
    ])
    assert model.client.chat.completions.create.call_args.kwargs["messages"] == [
        {"role": "system", "content": [{"type": "text", "text": "first\n\nsecond"}]},
    ]


def test_trace_records_merged_system_input(mocker):
    model = make_model()
    model.temperature = 0.2
    model.top_p = 0.9
    model.display_name = None
    model._context_budget_snapshot = None
    model._monitoring = MagicMock()
    model._context_budget_trace_attributes = Mock(return_value={})
    call = OpenAIModel.__call__
    mocker.patch.object(OpenAIModel, "__call__", return_value="response")
    call(model, messages=[
        {"role": "system", "content": [{"type": "text", "text": "first"}]},
        {"role": "system", "content": [{"type": "text", "text": "second"}]},
    ])
    assert model._monitoring.trace_llm_request.call_args.kwargs["input.value"] == [
        {"role": "system", "content": [{"type": "text", "text": "first\n\nsecond"}]},
    ]
