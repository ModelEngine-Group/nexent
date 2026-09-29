"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
from uuid import uuid4
from shared.http import MODEL_TIMEOUT
from d3.assets import get_test_asset
import os
from shared.asset_registry import register_asset, mark_asset_state


async def delete_owned_memory(identity, memory_id: int) -> None:
    """Delete only an ID created by this batch, checking ambiguous responses."""
    path = f'/memory/records/{int(memory_id)}'
    async with client('config', token=identity.access_token) as api:
        deleted = await api.delete(path)
        if deleted.status_code == 200:
            return
        if deleted.status_code in (401, 403):
            raise RuntimeError(f'Owned memory cleanup unauthorized: HTTP {deleted.status_code}')
        verified = await api.get(path)
        if verified.status_code != 404:
            raise RuntimeError(f'Owned memory cleanup failed: HTTP {deleted.status_code}')


async def cleanup_owned_memory(identity, memory_id: int) -> None:
    try:
        await delete_owned_memory(identity, memory_id)
        mark_asset_state('owned_memories', str(memory_id), 'DELETED')
    except Exception as exc:
        mark_asset_state('owned_memories', str(memory_id), 'ORPHANED',
                         detail=f'memory cleanup failed: {type(exc).__name__}')
        raise


async def _create_agent_memory(identity, marker: str, *, require_indexed: bool = False) -> int:
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post(
            "/memory/records",
            json={
                "layer": "agent", "memory_type": "short_term", "content": f"Remember exact marker {marker}",
                "agent_id": str(get_test_asset("agents", "basic_id")), "concept_tags": ["d3"],
                "idempotency_key": f"d3-{uuid4().hex}",
            },
        )
    assert_status(created, 200)
    body = created.json()
    memory_id = body.get("memory_id") or body.get("id")
    if not memory_id:
        raise AssertionError('memory creation omitted id')
    memory_id = int(memory_id)
    if os.getenv('RESULT_DIR'):
        try:
            register_asset('owned_memories', str(memory_id), memory_id,
                owner_case_id='MEMORY-FACTORY', cleanup={
                    'kind':'delete_owned_memory', 'identity':identity.id,
                    'memory_id':memory_id,
                })
        except Exception:
            # Do not leak a newly created record if persisting its journal fails.
            await delete_owned_memory(identity, memory_id)
            raise
    if require_indexed:
        if body.get("indexed") is not True:
            try:
                await cleanup_owned_memory(identity, memory_id)
            except Exception as exc:
                raise AssertionError('memory record was not indexed; cleanup also failed') from exc
        assert body.get("indexed") is True, 'memory record was not indexed'
    return int(memory_id)
