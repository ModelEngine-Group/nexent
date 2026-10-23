# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run-owned TPC response sequences on the existing controlled HTTP service."""
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from cmsr_provider import controlled

router = APIRouter()
scenarios = {}


@router.post('/tpc/{nonce}/__control')
async def configure(nonce: str, request: Request):
    controlled(request)
    body = await request.json()
    responses = body.get('responses')
    if not re.fullmatch('[a-f0-9]{32}', nonce) or not isinstance(responses, list) or not responses:
        raise HTTPException(400, 'Invalid sequence')
    if not all(isinstance(item, str) for item in responses):
        raise HTTPException(400, 'Responses must be strings')
    scenarios[nonce] = {'responses': responses, 'request_count': 0,
                        'finish_reason': body.get('finish_reason', 'stop'),
                        'auxiliary_title': body.get('auxiliary_title', 'TPC verification')}
    return {'ready': True}


@router.get('/tpc/{nonce}/__stats')
async def stats(nonce: str, request: Request):
    controlled(request)
    if nonce not in scenarios:
        raise HTTPException(404, 'Unknown sequence')
    return {'request_count': scenarios[nonce]['request_count']}


@router.delete('/tpc/{nonce}')
async def delete(nonce: str, request: Request):
    controlled(request)
    scenarios.pop(nonce, None)
    return {'deleted': True}


@router.post('/tpc/{nonce}/v1/chat/completions')
async def complete(nonce: str, request: Request):
    if nonce not in scenarios:
        raise HTTPException(404, 'Unknown sequence')
    body = await request.json()
    state = scenarios[nonce]
    if body.get('max_tokens') == 4096:
        index = state['request_count']
        state['request_count'] += 1
        text = state['responses'][min(index, len(state['responses']) - 1)]
        finish = state['finish_reason']
    else:
        # Health checks and title generation do not consume an Agent response.
        text, finish = state['auxiliary_title'], 'stop'
    model = body.get('model', 'tpc')
    base = {'id': 'chatcmpl-tpc-' + nonce, 'model': model, 'created': 1}
    usage = {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}
    if not body.get('stream'):
        return {**base, 'object': 'chat.completion', 'usage': usage,
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text}, 'finish_reason': finish}]}

    async def fragments():
        for index in range(0, len(text), 8):
            event = {**base, 'object': 'chat.completion.chunk',
                     'choices': [{'index': 0, 'delta': {'content': text[index:index + 8]}, 'finish_reason': None}]}
            yield 'data: ' + json.dumps(event) + '\n\n'
        yield 'data: ' + json.dumps({**base, 'object': 'chat.completion.chunk', 'usage': usage,
                                    'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}) + '\n\n'
        yield 'data: [DONE]\n\n'
    return StreamingResponse(fragments(), media_type='text/event-stream')
