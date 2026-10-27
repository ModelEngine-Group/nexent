# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Owned CMSR fixtures; existing runner owns the HTTP service lifetime."""
import asyncio
import json
import os
import uuid

import httpx

from shared.asset_registry import AssetDependencyError, register_asset
from shared.auth import sign_in
from shared.config import controlled_asset_url
from shared.http import assert_status, client


async def control(nonce, operation, *, mode=None):
    local = os.environ.get('NEXENT_TEST_ASSETS_LOCAL_URL', '').rstrip('/')
    if not local:
        raise AssetDependencyError('services', 'cmsr_provider', detail='Controlled HTTP service is required')
    async with httpx.AsyncClient(base_url=local, timeout=10, trust_env=False) as api:
        path = f'/cmsr/{nonce}'
        if operation == 'reset':
            response = await api.post(path + '/reset', json={'mode': mode})
        elif operation == 'delete':
            response = await api.delete(path)
        elif operation == 'state':
            response = await api.get(path + '/state')
        else:
            response = await api.post(path + '/release/' + operation)
    assert_status(response, 200)
    return response.json()


async def wait_paused(nonce, phase):
    async with asyncio.timeout(60):
        while True:
            state = await control(nonce, 'state')
            assert not state['expired'], 'Provider release deadline expired'
            if state['paused'] == phase:
                return state
            await asyncio.sleep(0.1)


async def setup(case_id, *, publish=False):
    identity = await sign_in('tenant_a_admin')
    nonce = uuid.uuid4().hex
    display = 'cmsr_' + nonce
    async with client('config', token=identity.access_token) as api:
        created = await api.post('/model/create', json={
            'model_factory': 'OpenAI-API-Compatible', 'model_name': 'cmsr', 'model_type': 'llm',
            'api_key': nonce, 'base_url': controlled_asset_url(f'/cmsr/{nonce}/v1'),
            'display_name': display, 'max_tokens': 4096})
        assert_status(created, 200)
        register_asset('owned_models', display, display, owner_case_id=case_id,
            cleanup={'service': 'config', 'identity': identity.id, 'method': 'POST',
                     'path': '/model/delete', 'params': {'display_name': display}, 'allowed_statuses': [200, 404]})
        catalog = await api.get('/model/list')
        assert_status(catalog, 200)
        rows = catalog.json()
        if isinstance(rows, dict):
            rows = rows.get('data') or rows.get('models') or []
        matches = [row for row in rows if row.get('display_name') == display]
        assert len(matches) == 1
        model_id = int(matches[0].get('model_id') or matches[0]['id'])
        health = await api.post('/model/healthcheck', params={'display_name': display, 'model_type': 'llm'})
        assert_status(health, 200)
        health_body = health.json()
        assert health_body.get('data', health_body).get('connectivity') is True, 'Owned fixture model must be available to published chat'
        agent = await api.post('/agent/update', json={
            'name': 'cmsr_' + nonce, 'display_name': display, 'description': 'Owned retry fixture',
            'business_description': 'CMSR integration', 'max_steps': 3, 'provide_run_summary': False,
            'model_ids': [model_id], 'enabled_tool_ids': [], 'enabled_skill_ids': [],
            'enabled': True, 'version_no': 0, 'enable_protocol_repair_retry': True})
        assert_status(agent, 200)
        agent_id = int(agent.json()['agent_id'])
        register_asset('owned_agents', str(agent_id), agent_id, owner_case_id=case_id,
            cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                     'path': '/agent', 'json': {'agent_id': agent_id}, 'allowed_statuses': [200, 404]})
        assert_status(await api.put(f'/agent/clear_new/{agent_id}'), 200)
        if publish:
            assert_status(await api.post(f'/agent/{agent_id}/publish',
                json={'version_name': 'cmsr-test', 'release_note': 'Owned CMSR fixture'}), 200)
    return {'nonce': nonce, 'agent_id': agent_id, 'display': display}


class HistoryVerificationError(AssertionError):
    """Expose only controller-authored diagnostics, never history text."""


def verify_rejected_history(body, events, nonce):
    """Permit exact pre-run memory logs, never rejected model action units."""
    first_step = next(index for index, event in enumerate(events) if event.get('type') == 'step_count')
    # The product performs memory pre-search before Step 1. These independent
    # logs may be persisted even when every subsequent model attempt rolls back.
    def pre_run_unit(part):
        return part.get('type'), json.dumps(part.get('content') or '', sort_keys=True)
    allowed_prefix = [pre_run_unit(event) for event in events[:first_step]
                      if event.get('type') in {'tool', 'tool-call', 'execution_logs'}]
    observed_prefix = []
    if any(event.get('type') == 'final_answer' for event in events):
        raise HistoryVerificationError('Rejected SSE unexpectedly emitted a final answer')
    assistants = [message for row in body.get('data', []) for message in row.get('message', [])
                  if message.get('role') == 'assistant']
    if len(assistants) != 1:
        raise HistoryVerificationError('Rejected run must have one persisted assistant message')
    parts = [part for part in assistants[0].get('message', []) if isinstance(part, dict)]
    if sum(part.get('type') == 'step_count' for part in parts) != 1:
        raise HistoryVerificationError('Rejected run must retain exactly one Step 1')
    in_step = False
    for index, part in enumerate(parts):
        kind, content = part.get('type', ''), part.get('content') or ''
        if kind == 'step_count':
            in_step = True
        if kind.startswith('model_output_') or kind == 'parse':
            raise HistoryVerificationError('Rejected model output/action persisted')
        if kind == 'final_answer':
            # The history formatter appends this empty view-only placeholder
            # when no final-answer unit was stored. A stored unit carries its
            # unit metadata; neither that nor a nonempty answer is permitted.
            if (set(part) != {'type', 'content'} or part['content'] != ''
                    or index != len(parts) - 1):
                raise HistoryVerificationError('Rejected run persisted a final answer')
        if 'CMSR_REJECTED_' + nonce in str(content):
            raise HistoryVerificationError('Rejected fixture marker persisted')
        if kind in {'tool', 'tool-call'} and (in_step or content):
            raise HistoryVerificationError('Rejected run persisted a model tool action')
        if kind in {'tool', 'tool-call', 'execution_logs'}:
            if in_step:
                raise HistoryVerificationError('Rejected run persisted unmatched execution logs')
            observed_prefix.append(pre_run_unit(part))
    if observed_prefix != allowed_prefix:
        raise HistoryVerificationError('History pre-run tools/logs differ from observed SSE order/content')
    return {'assistant_count': 1, 'step_count': 1,
            'pre_run_log_count': sum(event.get('type') == 'execution_logs' for event in events[:first_step]),
            'rejected_action_persisted': False}


def history_diagnostics(body, nonce):
    """Summarize persisted output without disclosing prompts or credentials."""
    histories = body.get('data') or []
    assistants = [message for history in histories for message in history.get('message', [])
                  if message.get('role') == 'assistant']
    parts = [part for message in assistants for part in message.get('message', []) if isinstance(part, dict)]
    content = ''.join(str(part.get('content') or '') for part in parts)
    final = ''.join(str(part.get('content') or '') for part in parts if part.get('type') == 'final_answer')
    return {
        'assistant_count': len(assistants),
        'failed_fragment_present': 'CMSR_FAILED_' + nonce in content,
        'empty_code_present': '<code></code>' in content,
        'committed_marker_present': 'CMSR_OK_' + nonce in content,
        'final_marker_present': 'CMSR_FINAL_' + nonce in final,
        'parse_count': sum(part.get('type') == 'parse' for part in parts),
        'step_count': sum(part.get('type') == 'step_count' for part in parts),
    }


def verify_history(body, nonce):
    # Inspect persisted assistant units only; user prompt echoes are not proof.
    diagnostics = history_diagnostics(body, nonce)
    checks = {
        'failed_fragment_present': False, 'empty_code_present': False,
        'committed_marker_present': True, 'final_marker_present': True,
        # Only the code action owns a persisted reasoning step. The pure final
        # answer's Step 2 marker is projected away by the final-answer contract.
        'parse_count': 1, 'step_count': 1,
    }
    for key, expected in checks.items():
        if diagnostics[key] != expected:
            raise HistoryVerificationError(f'{key}: expected {expected}, observed {diagnostics[key]}')
