# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise actual Provider failure and timeout, not a nonexistent model ID."""
import time

import pytest

from shared.asset_registry import AssetDependencyError
from shared.case_evidence import write_case_evidence
from shared.factories.agent import _draft_agent, _llm_id
from shared.http import MODEL_TIMEOUT, assert_status, client, response_message
from shared.prompt_fault import fault_control, owned_prompt_fault_model

CASE_ID = 'AGT-012'


def fault_model(identity, mode):
    """Use the runner-owned Provider and its failure-preserving cleanup."""
    return owned_prompt_fault_model(identity, CASE_ID, mode)


def require_prompt_sdk(response, receipt):
    """Distinguish the explicit capability rejection from other HTTP 400 errors."""
    if (receipt['calls'] == 0 and response.status_code == 400
            and response_message(response) ==
            'Auto optimize from debug requires Jiuwen SDK to be enabled.'):
        raise AssetDependencyError(
            'capabilities', 'jiuwen',
            detail='Enable NEXENT_ENABLE_JIUWEN_SDK and install the configuration service Jiuwen adapter dependencies')


def snapshot(body):
    body = body.get('data') or body
    assert body.get('agent_id') or body.get('id'), 'Draft read-back must contain the owned Agent identity'
    fields = ('name', 'display_name', 'description', 'prompt',
              'greeting_message', 'example_questions', 'model_ids',
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
        async with _draft_agent(identity, model_ids=[model_id], owner_case_id=CASE_ID) as (agent_id, draft):
            payload = {'agent_id': agent_id, 'model_id': model_id, 'feedback': 'Do not invent facts',
                       'selected': {'user_question': 'What is X?', 'assistant_answer': 'Unverified answer'},
                       'history': [{'role': 'user', 'content': 'What is X?'}]}
            async with client('config', token=identity.access_token, timeout=120) as api:
                # Debug optimization requires an existing system prompt. New
                # drafts no longer receive one from retired prompt templates.
                initialized = await api.post('/agent/update', json={
                    **draft, 'agent_id': agent_id,
                    'prompt': 'Answer questions using verified facts.',
                })
                assert_status(initialized, 200)
                before = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
                assert_status(before, 200)
                assert (snapshot(before.json()).get('prompt') or '').strip(), 'Owned draft requires a saved prompt'
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
            require_prompt_sdk(response, receipt)
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
