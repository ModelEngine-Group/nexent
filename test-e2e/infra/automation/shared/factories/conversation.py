"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
from contextlib import asynccontextmanager
import os
from shared.asset_registry import register_asset, mark_asset_state


async def _create_conversation(identity, title: str = "D2 contract") -> int:
    async with client("runtime", token=identity.access_token) as api:
        response = await api.put("/conversation/create", json={"title": title})
    assert_status(response, 200)
    conversation_id = int(response.json()["data"]["conversation_id"])
    if os.getenv('RESULT_DIR'):
        # Journal immediately, before the caller's first assertion. A failed
        # rename/history assertion must not leak the newly created conversation.
        register_asset('owned_conversations', str(conversation_id), conversation_id,
            owner_case_id='CONVERSATION-FACTORY', cleanup={
                'service':'runtime', 'identity':identity.id, 'method':'DELETE',
                'path':f'/conversation/{conversation_id}', 'allowed_statuses':[200,404],
            })
    return conversation_id


async def delete_owned_conversation(identity, conversation_id: int) -> None:
    """Delete one owned ID; failed DELETE is not proof of absence."""
    path = f'/conversation/{int(conversation_id)}'
    async with client('runtime', token=identity.access_token) as api:
        deleted = await api.delete(path)
        if deleted.status_code not in (200, 404):
            verified = await api.get(path)
            body = verified.json() if verified.status_code == 200 else None
            if not (isinstance(body, dict) and body.get('code') == 0 and body.get('data') == []):
                raise RuntimeError(f'Owned conversation cleanup failed: HTTP {deleted.status_code}')


@asynccontextmanager
async def owned_conversation(identity, title: str = 'Isolated conversation'):
    """Journal before yielding; record cleanup failure without hiding assertions."""
    conversation_id = await _create_conversation(identity, title)
    primary_error = None
    try:
        yield conversation_id
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            await delete_owned_conversation(identity, conversation_id)
            mark_asset_state('owned_conversations', str(conversation_id), 'DELETED')
        except Exception as exc:
            # Exception text from HTTP clients can contain credentials. Persist
            # only the type and the owned resource, never request headers/body.
            mark_asset_state('owned_conversations', str(conversation_id), 'ORPHANED',
                             detail=f'conversation cleanup failed: {type(exc).__name__}')
            if primary_error is None:
                raise
            note = 'Owned conversation cleanup failed; see asset-journal.jsonl.'
            if hasattr(primary_error, 'add_note'):
                primary_error.add_note(note)
            else:  # Developer machines may still use Python 3.10.
                primary_error.__notes__ = [*getattr(primary_error, '__notes__', []), note]
