"""Install an owned failure model without replacing the tenant default LLM."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import uuid

import httpx

from shared.asset_registry import AssetDependencyError, register_asset, mark_asset_state
from shared.config import controlled_asset_url
from shared.http import assert_status, client


async def fault_control(nonce, *, clear=False):
    local = os.environ.get('NEXENT_TEST_ASSETS_LOCAL_URL', '').rstrip('/')
    if not local:
        raise AssetDependencyError('services', 'runtime_fault', detail='Runner-owned controlled HTTP service is required')
    async with httpx.AsyncClient(base_url=local, timeout=10, trust_env=False) as api:
        response = (await api.delete(f'/runtime-fault/{nonce}') if clear
                    else await api.get(f'/runtime-fault/{nonce}/state'))
    assert_status(response, 200)
    receipt = response.json()
    if not clear and os.environ.get('RESULT_DIR'):
        import json
        path = Path(os.environ['RESULT_DIR']) / 'runtime/provider-fault.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as output:
            output.write(json.dumps({'nonce': nonce, **receipt}) + '\n')
    return receipt


@asynccontextmanager
async def owned_failure_model(identity, case_id):
    nonce = uuid.uuid4().hex
    assert (await fault_control(nonce))['calls'] == 0
    display = 'runtime_fault_' + nonce
    created = False
    try:
        async with client('config', token=identity.access_token) as api:
            response = await api.post('/model/create', json={
                'model_factory': 'OpenAI-API-Compatible', 'model_name': 'controlled-failure',
                'model_type': 'llm', 'display_name': display, 'max_tokens': 1024,
                # This nonce is a non-secret fixture token, not a provider credential.
                'api_key': nonce, 'base_url': controlled_asset_url(f'/runtime-fault/{nonce}/v1'),
            })
            assert_status(response, 200)
            created = True
            register_asset('owned_models', display, display, owner_case_id=case_id,
                cleanup={'service': 'config', 'identity': identity.id, 'method': 'POST',
                         'path': '/model/delete', 'params': {'display_name': display}, 'allowed_statuses': [200, 404]})
            response = await api.get('/model/list')
            assert_status(response, 200)
            rows = response.json().get('data') or []
            models = [row for row in rows if row.get('display_name') == display]
            assert len(models) == 1, 'Owned failure model is not uniquely registered'
            model_id = int(models[0].get('model_id') or models[0]['id'])
        yield model_id, nonce
    finally:
        try:
            if created:
                async with client('config', token=identity.access_token) as api:
                    response = await api.post('/model/delete', params={'display_name': display})
                assert_status(response, (200, 404))
                mark_asset_state('owned_models', display, 'DELETED')
        finally:
            await fault_control(nonce, clear=True)
