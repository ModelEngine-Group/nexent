"""Run-scoped permanent provider failures with observable request receipts."""
from uuid import UUID
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
attempts: dict[UUID, tuple[int, float]] = {}


@router.post('/runtime-fault/{nonce}/v1/chat/completions')
async def fail_completion(nonce: UUID):
    now = time.monotonic()
    for key, (_, touched) in list(attempts.items()):
        if now - touched > 3600:
            del attempts[key]
    count = attempts.get(nonce, (0, now))[0] + 1
    attempts[nonce] = (count, now)
    return JSONResponse(status_code=503, content={'error': {
        'code': 'controlled_provider_unavailable', 'message': 'Controlled provider is unavailable'}})


@router.get('/runtime-fault/{nonce}/state')
async def state(nonce: UUID):
    return {'calls': attempts.get(nonce, (0, 0))[0], 'status': 503}


@router.delete('/runtime-fault/{nonce}')
async def clear(nonce: UUID):
    attempts.pop(nonce, None)
    return {'cleared': True}
