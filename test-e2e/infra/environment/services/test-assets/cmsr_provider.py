"""Batch-local OpenAI stream faults with explicit, bounded release gates."""
import asyncio
import ipaddress
import json
import re
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


@dataclass
class Scenario:
    mode: str
    calls: int = 0
    paused: str = ''
    completed: bool = False
    expired: bool = False
    fail_release: asyncio.Event = field(default_factory=asyncio.Event)
    success_release: asyncio.Event = field(default_factory=asyncio.Event)


scenarios: dict[str, Scenario] = {}


def controlled(request):
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = request.client.host == 'testclient'
    if not local:
        raise HTTPException(403, 'Control is host-local only')


def lookup(nonce):
    if not re.fullmatch(r'[a-f0-9]{32}', nonce) or nonce not in scenarios:
        raise HTTPException(404, 'Unknown scenario')
    return scenarios[nonce]


@router.post('/cmsr/{nonce}/reset')
async def reset(nonce: str, request: Request):
    controlled(request)
    if not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise HTTPException(400, 'Invalid nonce')
    mode = (await request.json()).get('mode')
    if mode not in {'transport', 'semantic'}:
        raise HTTPException(400, 'Invalid mode')
    if nonce in scenarios:
        raise HTTPException(409, 'Scenario already exists')
    scenarios[nonce] = Scenario(mode)
    return {'ready': True}


@router.get('/cmsr/{nonce}/state')
async def state(nonce: str, request: Request):
    controlled(request)
    item = lookup(nonce)
    return {'calls': item.calls, 'paused': item.paused, 'completed': item.completed,
            'expired': item.expired}


@router.post('/cmsr/{nonce}/release/{phase}')
async def release(nonce: str, phase: str, request: Request):
    controlled(request)
    item = lookup(nonce)
    if phase not in {'failed', 'success'}:
        raise HTTPException(400, 'Invalid phase')
    (item.fail_release if phase == 'failed' else item.success_release).set()
    return {'released': phase}


@router.delete('/cmsr/{nonce}')
async def delete(nonce: str, request: Request):
    controlled(request)
    item = lookup(nonce)
    item.fail_release.set()
    item.success_release.set()
    del scenarios[nonce]
    return {'deleted': True}


async def chunks(item, nonce):
    item.calls += 1
    attempt = item.calls
    if attempt > 2:
        raise RuntimeError('Unexpected third provider request')

    def chunk(content=None, finish=None):
        delta = {'content': content} if content is not None else {}
        return 'data: ' + json.dumps({'id': 'chatcmpl-' + nonce,
            'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'cmsr',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n'

    if attempt == 1:
        yield chunk('CMSR_FAILED_' + nonce if item.mode == 'transport' else '<code></code>')
        item.paused = 'failed'
        try:
            await asyncio.wait_for(item.fail_release.wait(), 90)
        except TimeoutError:
            item.expired = True
            raise
        item.paused = ''
        if item.mode == 'transport':
            # Missing terminal chunk is an actual broken provider transport.
            raise ConnectionResetError('Controlled incomplete provider stream')
    else:
        yield chunk("<code>print('CMSR_OK_" + nonce + "');\n")
        item.paused = 'success'
        try:
            await asyncio.wait_for(item.success_release.wait(), 90)
        except TimeoutError:
            item.expired = True
            raise
        item.paused = ''
        yield chunk("final_answer('CMSR_FINAL_" + nonce + "')</code>")
        item.completed = True
    yield chunk(finish='stop')
    yield 'data: [DONE]\n\n'


@router.post('/cmsr/{nonce}/v1/chat/completions')
async def completions(nonce: str, request: Request):
    body = await request.json()
    if not body.get('stream'):
        if not re.fullmatch(r'[a-f0-9]{32}', nonce):
            raise HTTPException(404, 'Unknown fixture')
        # Product model health checks are non-streaming and must not consume
        # a retry attempt or open a gate belonging to the actual conversation.
        return {'id': 'chatcmpl-health', 'object': 'chat.completion',
                'created': int(time.time()), 'model': 'cmsr',
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'},
                             'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
    item = lookup(nonce)
    return StreamingResponse(chunks(item, nonce), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store'})
