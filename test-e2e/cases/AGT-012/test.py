"""Exercise actual Provider failure and timeout, not a nonexistent model ID."""
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest

from shared.asset_registry import AssetDependencyError, register_asset, mark_asset_state
from shared.case_evidence import write_case_evidence
from shared.config import controlled_asset_url
from shared.factories.agent import _draft_agent, _llm_id
from shared.http import assert_status, client, MODEL_TIMEOUT

CASE_ID = 'AGT-012'


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
async def fault_model(identity, mode):
    nonce = uuid.uuid4().hex
    display = 'prompt_fault_' + nonce
    await fault_control(nonce, 'reset', mode)
    created = False
    try:
        async with client('config', token=identity.access_token) as api:
            response = await api.post('/model/create', json={
                'model_factory': 'OpenAI-API-Compatible', 'model_name': 'controlled-prompt-failure',
                'model_type': 'llm', 'display_name': display, 'api_key': nonce,
                'base_url': controlled_asset_url(f'/prompt-fault/{nonce}/v1'),
                'max_tokens': 1024, 'timeout_seconds': 1, 'skip_default_backfill': True})
            assert_status(response, 200)
            created = True
            register_asset('owned_models', display, display, owner_case_id=CASE_ID,
                cleanup={'service': 'config', 'identity': identity.id, 'method': 'POST',
                         'path': '/model/delete', 'params': {'display_name': display}, 'allowed_statuses': [200, 404]})
            listed = await api.get('/model/list')
            assert_status(listed, 200)
            matches = [row for row in listed.json().get('data', []) if row.get('display_name') == display]
            assert len(matches) == 1, 'Owned failure model must be uniquely registered'
            yield int(matches[0].get('model_id') or matches[0]['id']), nonce
    finally:
        try:
            if created:
                async with client('config', token=identity.access_token) as api:
                    response = await api.post('/model/delete', params={'display_name': display})
                assert_status(response, (200, 404))
                mark_asset_state('owned_models', display, 'DELETED')
        finally:
            await fault_control(nonce, 'delete')


def snapshot(body):
    body = body.get('data') or body
    assert body.get('agent_id') or body.get('id'), 'Draft read-back must contain the owned Agent identity'
    fields = ('name', 'display_name', 'description', 'duty_prompt', 'constraint_prompt',
              'few_shots_prompt', 'greeting_message', 'example_questions', 'model_ids',
              'tools', 'skills', 'related_agent_ids')
    return {field: body.get(field) for field in fields}


def assert_fault(response, receipt, before, after, elapsed, mode):
    assert receipt['mode'] == mode and receipt['calls'] >= 1, 'Fault never reached the owned Provider'
    assert receipt['calls'] <= 12, 'Provider retries were not bounded'
    assert 0 <= elapsed < 90, 'Prompt fault did not terminate within its budget'
    # The endpoint currently maps unexpected adapter failures to this exact
    # application error. Do not accept arbitrary 5xx or false success.
    assert_status(response, 500)
    assert response.json().get('message') == 'Internal server error, please try again later.'
    assert not response.json().get('data'), 'Failure returned a successful optimization payload'
    assert before == after, 'Failed optimization partially changed the owned Agent'


async def exercise_provider_fault(identity, mode):
    async with fault_model(identity, mode) as (model_id, nonce):
        async with _draft_agent(identity, model_ids=[model_id], owner_case_id=CASE_ID) as (agent_id, _):
            payload = {'agent_id': agent_id, 'model_id': model_id, 'feedback': 'Do not invent facts',
                       'selected': {'user_question': 'What is X?', 'assistant_answer': 'Unverified answer'},
                       'history': [{'role': 'user', 'content': 'What is X?'}]}
            async with client('config', token=identity.access_token, timeout=120) as api:
                before = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
                assert_status(before, 200)
                started = time.monotonic()
                response = await api.post('/prompt/optimize/from_debug', json=payload)
                elapsed = time.monotonic() - started
            # An unhandled application error closes Uvicorn's keep-alive
            # connection. Read back through a new client; never retry the
            # optimization action or hide its original response.
            async with client('config', token=identity.access_token) as api:
                after = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
                assert_status(after, 200)
            receipt = await fault_control(nonce, 'state')
            write_case_evidence(CASE_ID + '-' + mode, {'mode': mode, 'receipt': receipt,
                'http_status': response.status_code, 'elapsed_seconds': elapsed,
                'draft_unchanged': snapshot(before.json()) == snapshot(after.json())})
            if receipt['calls'] == 0 and response.status_code == 400:
                raise AssetDependencyError('capabilities', 'jiuwen', detail='Prompt optimization SDK is unavailable')
            assert_fault(response, receipt, snapshot(before.json()), snapshot(after.json()), elapsed, mode)
            # A configured real LLM proves the shared endpoint and Agent remain
            # usable after the isolated fault. Do not replace tenant defaults.
            payload['model_id'] = await _llm_id(identity)
            async with client('config', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                recovered = await api.post('/prompt/optimize/from_debug', json=payload)
                write_case_evidence(CASE_ID + '-' + mode + '-recovery', {
                    'http_status': recovered.status_code,
                    'prompt_source': recovered.headers.get('X-Prompt-Source'),
                    'optimized_prompt_nonempty': bool((recovered.json().get('data') or {}).get('optimized_full_prompt', '').strip()),
                })
                assert_status(recovered, 200)
                assert recovered.headers.get('X-Prompt-Source') == 'jiuwen'
                assert (recovered.json().get('data') or {}).get('optimized_full_prompt', '').strip()
                readback = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
                assert_status(readback, 200)
                assert snapshot(before.json()) == snapshot(readback.json()), 'Optimization must not auto-save the draft'


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_prompt_provider_failure_preserves_draft(tenant_a_admin):
    # The formal runner requires one collected item per Case ID. Keep both
    # fault variants in that item; each still owns isolated assets/evidence.
    failures = []
    for mode in ('unavailable', 'timeout'):
        try:
            await exercise_provider_fault(tenant_a_admin, mode)
        except AssertionError as exc:
            # Keep the Case red, but exercise the other independent fault so
            # one recovery failure does not erase timeout-variant evidence.
            failures.append(f'{mode}: {exc}')
    assert not failures, '\n'.join(failures)
