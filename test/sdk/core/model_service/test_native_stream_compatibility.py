# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Gateway continuation fragments must preserve a genuine complete call identity."""

import json

import pytest
from nexent.core.model_service.adapters.openai_chat import ModelAdapterError
from nexent.core.model_service.adapters.openai_stream import OpenAIStreamDecoder
from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.sse import SSEEvent


def packet(delta=None, finish=None):
    return SSEEvent(json.dumps({'choices':[{'index':0,'delta':delta or {},'finish_reason':finish}]}))


def decoder(profile):
    return OpenAIStreamDecoder(ModelRequest(request_id='native-regression',outlet_id=profile.outlet_id,
        config_revision=profile.config_revision, stream=True,
        messages=[ModelMessage(semantic_role='user',content_parts=[{'type':'text','text':'Task'}])]),profile)


def test_empty_continuation_id_preserves_initial_id(protocol_profile):
    stream = decoder(protocol_profile)
    stream.push(packet({'tool_calls':[{'index':0,'id':'original','type':'function',
        'function':{'name':'echo','arguments':'{'}}]}))
    stream.push(packet({'tool_calls':[{'index':0,'id':'','function':{'name':'','arguments':'}'}}]}))
    stream.push(packet(finish='tool_calls'))
    complete = stream.push(SSEEvent('[DONE]'))[-1].message
    assert len(complete.tool_calls) == 1
    assert complete.tool_calls[0].provider_call_id == 'original'
    assert complete.tool_calls[0].name == 'echo'
    assert complete.tool_calls[0].parsed_arguments == {}


@pytest.mark.parametrize('identifier',['','   ','changed'])
def test_empty_missing_or_changed_identity_cannot_become_another_call(protocol_profile,identifier):
    stream = decoder(protocol_profile)
    if identifier != '':
        stream.push(packet({'tool_calls':[{'index':0,'id':'original','type':'function',
            'function':{'name':'echo','arguments':''}}]}))
    with pytest.raises(ModelAdapterError):
        stream.push(packet({'tool_calls':[{'index':0,'id':identifier,'type':'function',
            'function':{'name':'','arguments':'{}'}}]}))
        stream.push(packet(finish='tool_calls'))
        stream.push(SSEEvent('[DONE]'))
