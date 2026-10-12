"""Invalid section ranges and controlled Provider failures preserve the draft."""
import time

import pytest

from shared.case_evidence import write_case_evidence
from shared.factories.agent import _draft_agent, _llm_id
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.prompt_fault import fault_control, owned_prompt_fault_model

CASE_ID = 'AGT-010'


def invalid_ranges(content):
    # insert ignores end_pos. Invalidating only end_pos was a false negative.
    return ({'mode': 'insert', 'start_pos': -1, 'end_pos': None},
            {'mode': 'insert', 'start_pos': len(content) + 1, 'end_pos': None},
            {'mode': 'select', 'start_pos': 6, 'end_pos': 0})


async def draft_snapshot(identity, agent_id):
    async with client('config', token=identity.access_token) as api:
        response = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
    assert_status(response, 200)
    body = response.json().get('data') or response.json()
    assert int(body.get('agent_id') or body.get('id') or 0) == agent_id
    return {key: body.get(key) for key in ('name', 'description', 'duty_prompt',
            'constraint_prompt', 'few_shots_prompt', 'model_ids', 'tools', 'skills', 'related_agent_ids')}


def assert_rejected(response, before, after):
    assert_status(response, (400, 422))
    assert response.json().get('message') or response.json().get('detail'), 'Missing explicit error'
    assert not response.json().get('data'), 'Invalid optimization returned a success payload'
    assert before == after, 'Rejected optimization partially changed the draft'


@pytest.mark.stage('D3')
@pytest.mark.case_id(CASE_ID)
@pytest.mark.asyncio
async def test_section_negative_and_provider_fault_preserve_draft(tenant_a_admin):
    model_id = await _llm_id(tenant_a_admin)
    async with _draft_agent(tenant_a_admin, model_ids=[model_id], owner_case_id=CASE_ID) as (agent_id, _):
        payload = {'task_description': 'Answer safely', 'agent_id': agent_id, 'model_id': model_id,
                   'section_type': 'duty', 'section_title': 'Duty', 'current_content': 'Answer questions.',
                   'feedback': 'Make it concise.', 'mode': 'select', 'start_pos': 0, 'end_pos': 6,
                   'tool_ids': [], 'sub_agent_ids': [], 'knowledge_base_display_names': []}
        before = await draft_snapshot(tenant_a_admin, agent_id)
        for index, bounds in enumerate(invalid_ranges(payload['current_content'])):
            for attempt in range(2):
                async with client('config', token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
                    response = await api.post('/prompt/optimize', json={**payload, **bounds})
                after = await draft_snapshot(tenant_a_admin, agent_id)
                write_case_evidence(f'{CASE_ID}-range-{index}-{attempt}', {
                    'bounds': bounds, 'http_status': response.status_code, 'draft_unchanged': before == after})
                assert_rejected(response, before, after)
        for mode in ('unavailable', 'timeout'):
            async with owned_prompt_fault_model(tenant_a_admin, CASE_ID, mode) as (fault_id, nonce):
                started = time.monotonic()
                async with client('config', token=tenant_a_admin.access_token, timeout=90) as api:
                    response = await api.post('/prompt/optimize', json={**payload, 'model_id': fault_id})
                elapsed = time.monotonic() - started
                receipt = await fault_control(nonce, 'state')
                after = await draft_snapshot(tenant_a_admin, agent_id)
                write_case_evidence(f'{CASE_ID}-{mode}', {'receipt': receipt,
                    'http_status': response.status_code, 'elapsed_seconds': elapsed, 'draft_unchanged': before == after})
                assert receipt['mode'] == mode and 1 <= receipt['calls'] <= 12, 'Owned Provider fault not exercised'
                assert elapsed < 90, 'Unbounded Provider failure'
                assert_rejected(response, before, after)
                # Current section endpoint returns the precise capability error
                # after Jiuwen fails and native select fallback is unsupported.
                assert_status(response, 400)
                assert 'mode=select' in response.json()['message'] and 'general' in response.json()['message']
        async with client('config', token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
            recovered = await api.post('/prompt/optimize', json=payload)
        write_case_evidence(CASE_ID + '-recovery', {'http_status': recovered.status_code,
            'source': recovered.headers.get('X-Prompt-Source')})
        assert_status(recovered, 200)
        assert recovered.headers.get('X-Prompt-Source') == 'jiuwen'
        assert (recovered.json().get('data') or {}).get('optimized_content', '').strip()
        assert before == await draft_snapshot(tenant_a_admin, agent_id), 'Suggestions must not automatically save'
