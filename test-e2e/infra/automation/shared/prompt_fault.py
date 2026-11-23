"""Owned Prompt Provider faults shared by section and Debug acceptance."""
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx

from shared.asset_registry import AssetDependencyError, mark_asset_state, register_asset
from shared.config import controlled_asset_url
from shared.http import assert_status, client


async def fault_control(nonce, operation, mode=None):
    base = os.environ.get('NEXENT_TEST_ASSETS_LOCAL_URL', '').rstrip('/')
    if not base:
        raise AssetDependencyError('services', 'prompt_fault', detail='Runner-owned controlled HTTP service required')
    async with httpx.AsyncClient(base_url=base, timeout=10, trust_env=False) as api:
        path = f'/prompt-fault/{nonce}'
        if operation == 'reset':
            response = await api.post(path + '/reset', json={'mode': mode})
        elif operation == 'state':
            response = await api.get(path + '/state')
        else:
            response = await api.delete(path)
    assert_status(response, 200)
    return response.json()


@asynccontextmanager
async def owned_prompt_fault_model(identity, case_id, mode):
    nonce = uuid4().hex
    display = 'prompt_fault_' + nonce
    await fault_control(nonce, 'reset', mode)
    created = False
    primary = None
    try:
        async with client('config', token=identity.access_token) as api:
            response = await api.post('/model/create', json={
                'model_factory': 'OpenAI-API-Compatible', 'model_name': 'controlled-prompt-failure',
                'model_type': 'llm', 'display_name': display, 'api_key': nonce,
                'base_url': controlled_asset_url(f'/prompt-fault/{nonce}/v1'),
                'max_tokens': 1024, 'timeout_seconds': 1, 'skip_default_backfill': True})
            assert_status(response, 200)
            created = True
            register_asset('owned_models', display, display, owner_case_id=case_id,
                cleanup={'service': 'config', 'identity': identity.id, 'method': 'POST',
                         'path': '/model/delete', 'params': {'display_name': display}, 'allowed_statuses': [200, 404]})
            listed = await api.get('/model/list')
            assert_status(listed, 200)
            matches = [row for row in listed.json().get('data', []) if row.get('display_name') == display]
            assert len(matches) == 1, 'Owned failure model must be uniquely registered'
        yield int(matches[0].get('model_id') or matches[0]['id']), nonce
    except BaseException as exc:
        primary = exc
        raise
    finally:
        failures = []
        if created:
            try:
                async with client('config', token=identity.access_token) as api:
                    response = await api.post('/model/delete', params={'display_name': display})
                assert_status(response, (200, 404))
                mark_asset_state('owned_models', display, 'DELETED')
            except Exception as exc:
                mark_asset_state('owned_models', display, 'ORPHANED', detail=type(exc).__name__)
                failures.append('owned model cleanup failed')
        try:
            await fault_control(nonce, 'delete')
        except Exception:
            failures.append('owned fault cleanup failed')
        if failures:
            message = '; '.join(failures)
            if primary is None:
                raise RuntimeError(message)
            primary.add_note(message)
