# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy FinalContext callbacks retain evidence, identity and attempt correlation."""

import json
from types import SimpleNamespace

import pytest
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.sse import SSEEvent
from test_context_recovery import overflow
from test_model_service import Sender, complete, frame
from test_model_service import setup as setup  # noqa: PLC0414 - Shared pytest fixture.


def completion(text):
    return [frame({'content': text}), frame(finish='stop'), SSEEvent('[DONE]')]


@pytest.mark.parametrize('final_context', [False, True])
def test_legacy_context_rebuild_uses_same_outlet_and_retains_evidence(setup, final_context):
    profile, _request, limiter, factory = setup
    sender = Sender([overflow(), completion('answer')])
    model = LegacyChatModel(profile, factory(sender))
    evidence = object()
    messages = [{'role': 'user', 'content': 'short'}]
    rebuilds = []

    def rebuild():
        assert not limiter._entries
        rebuilds.append(True)
        return SimpleNamespace(messages=messages, evidence=evidence) if final_context else messages

    result = model.generate([{'role': 'user', 'content': 'long'}], context_rebuild=rebuild)
    assert result.content == 'answer' and result.model_attempt_number == 2
    assert model.last_context_evidence is (evidence if final_context else None)
    assert len(rebuilds) == 1 and sender.frozen == 1 and len(sender.calls) == 2
    assert sender.calls[0].request_id == sender.calls[1].request_id == result.model_attempt_id
    assert json.loads(sender.calls[1].body_bytes)['messages'] == messages
    assert all('context_rebuild' not in json.loads(call.body_bytes) for call in sender.calls)
    assert not limiter._entries


def test_nested_compression_call_does_not_change_outer_attempt_confirmation(setup):
    profile, _request, limiter, factory = setup
    sender = Sender([overflow(), completion('summary'), completion('answer')])
    model = LegacyChatModel(profile, factory(sender))
    nested = []

    def rebuild():
        nested.append(model.generate([{'role': 'user', 'content': 'compress'}]))
        return [{'role': 'user', 'content': nested[-1].content}]

    result = model.generate([{'role': 'user', 'content': 'long'}], context_rebuild=rebuild)
    assert result.content == 'answer' and result.model_attempt_number == 2
    assert result.model_attempt_id != nested[0].model_attempt_id
    events = [json.loads(value) for value in model.observer.message_query]
    phases = [(event['attempt_id'], event['phase'], event['attempt']) for event in events if 'phase' in event]
    assert phases == [
        (nested[0].model_attempt_id, 'begin', 1), (nested[0].model_attempt_id, 'commit', 1),
        (result.model_attempt_id, 'begin', 2), (result.model_attempt_id, 'commit', 2),
    ]
    assert not limiter._entries


@pytest.mark.asyncio
@pytest.mark.parametrize('asynchronous', [False, True])
async def test_nonstream_context_recovery_uses_matching_callback_api(setup, asynchronous):
    profile, request, limiter, factory = setup
    sender = Sender([overflow(), complete()])
    model = factory(sender)

    def rebuild(_error):
        assert not limiter._entries
        return request

    async def arebuild(error):
        return rebuild(error)

    response = (await model.ainvoke(request, profile, request_rebuild=arebuild) if asynchronous
                else model.invoke(request, profile, request_rebuild=rebuild))
    assert response.content_parts == [{'type': 'text', 'text': 'answer'}]
    assert len(sender.calls) == 2 and sender.frozen == 1 and not limiter._entries
