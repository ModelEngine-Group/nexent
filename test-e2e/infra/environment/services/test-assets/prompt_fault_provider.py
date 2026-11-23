"""Run-scoped Prompt optimization faults; never record prompts or credentials."""
import asyncio
import ipaddress
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()
scenarios = {}


def host_control(request):
    host = request.client.host if request.client else ''
    try:
        allowed = host == 'testclient' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(403, 'Control is host-local only')


@router.post('/prompt-fault/{nonce}/reset')
async def reset(nonce: UUID, request: Request):
    host_control(request)
    mode = (await request.json()).get('mode')
    if mode not in {'unavailable', 'timeout'}:
        raise HTTPException(400, 'Invalid fault mode')
    if nonce in scenarios:
        raise HTTPException(409, 'Scenario already exists')
    scenarios[nonce] = {'mode': mode, 'calls': 0, 'created': time.monotonic()}
    return {'ready': True}


@router.get('/prompt-fault/{nonce}/state')
async def state(nonce: UUID, request: Request):
    host_control(request)
    item = scenarios.get(nonce)
    if item is None:
        raise HTTPException(404, 'Unknown fault')
    return {'mode': item['mode'], 'calls': item['calls']}


@router.delete('/prompt-fault/{nonce}')
async def delete(nonce: UUID, request: Request):
    host_control(request)
    scenarios.pop(nonce, None)
    return {'cleared': True}


@router.post('/prompt-fault/{nonce}/v1/chat/completions')
async def completion(nonce: UUID):
    item = scenarios.get(nonce)
    if item is None:
        raise HTTPException(404, 'Unknown fault')
    item['calls'] += 1
    if item['mode'] == 'timeout':
        await asyncio.sleep(3)
    return JSONResponse(status_code=503, content={'error': {
        'code': 'controlled_prompt_provider_unavailable', 'message': 'Controlled Prompt fault'}})
