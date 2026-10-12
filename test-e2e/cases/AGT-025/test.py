"""Real Planning execution observes an owned deterministic MCP failure."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from urllib.parse import quote
import uuid

import pytest

from shared.asset_registry import AssetDependencyError, register_asset, mark_asset_state
from shared.case_evidence import read_sse_with_evidence, write_case_evidence
from shared.factories.agent import _draft_agent
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import assert_terminal_event

CASE_ID = 'AGT-025'


def fault_calls(marker):
    filename = os.environ.get('NEXENT_TEST_MCP_WIRE_LOG')
    if not filename:
        raise AssetDependencyError('services', 'controlled_mcp_wire', detail='Runner-owned MCP wire log required')
    path = Path(filename)
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    return [row for row in rows if row.get('tool') == 'always_fail'
            and row.get('arguments', {}).get('code') == marker]


def assert_failed_plan(events, receipts, marker):
    assert receipts and all(row.get('error') == marker for row in receipts), 'No real controlled failure invocation'
    payloads = [event['data'] for event in events if isinstance(event.get('data'), dict)]
    plans, updates = [], []
    for payload in payloads:
        if payload.get('type') not in {'plan', 'plan_step_update'}:
            continue
        content = payload.get('content')
        decoded = json.loads(content) if isinstance(content, str) else content
        assert isinstance(decoded, dict), 'Planning event is not structured'
        (plans if payload['type'] == 'plan' else updates).append(decoded)
    assert len(plans) == 1, 'Expected one actual plan, not model prose or repeated plan creation'
    steps = plans[0].get('steps')
    assert isinstance(steps, list) and len(steps) >= 3
    ids = [step['id'] for step in steps]
    assert len(ids) == len(set(ids)), 'Plan has duplicate step identifiers'
    assert updates and all(update.get('step_id') in ids for update in updates), 'Plan update references an unknown step'
    assert all(update.get('status') in {'pending', 'in_progress', 'completed', 'skipped'} for update in updates)
    assert any(update.get('step_id') == ids[1] and update.get('status') == 'skipped'
               for update in updates), 'Failed dependency was not explicitly skipped'
    assert_terminal_event(events, allow_error=True)
    assert marker in json.dumps(payloads, ensure_ascii=False), 'Controlled failure is absent from product events'
    final = [payload for payload in payloads if payload.get('type') in {'final_answer', 'error'}]
    assert final and final[-1].get('content'), 'Failure handling did not produce a bounded terminal result'
    if final[-1]['type'] == 'final_answer':
        assert marker in final[-1]['content'], 'Final result concealed the actual failed dependency'


async def clean_generated_files(identity, events):
    # A real model may still generate a file despite the inline-report request.
    # Delete only exact keys returned by this owned run and owned by this user.
    for event in events:
        payload = event.get('data')
        if not isinstance(payload, dict) or payload.get('type') != 'files':
            continue
        content = payload.get('content')
        body = json.loads(content) if isinstance(content, str) else content
        for file in body.get('file_uploads', []):
            name = file.get('object_name')
            if file.get('status') != 'success' or not name:
                continue
            assert name.startswith(f'workspace/{identity.user_id}/') and '..' not in name.split('/'), 'Generated file is outside the owned workspace'
            register_asset('owned_attachments', name, name, owner_case_id=CASE_ID,
                cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                         'path': '/file/storage/' + quote(name, safe='/'), 'allowed_statuses': [200, 404]})
            async with client('config', token=identity.access_token) as api:
                deleted = await api.delete('/file/storage/' + quote(name, safe='/'))
            assert_status(deleted, (200, 404))
            mark_asset_state('owned_attachments', name, 'DELETED')


@asynccontextmanager
async def owned_failure_tool(identity):
    url = os.environ.get('NEXENT_TEST_MCP_URL', '').strip()
    if not url:
        raise AssetDependencyError('services', 'controlled_mcp_url', detail='Runner-owned MCP service required')
    name = 'planning-fault-' + uuid.uuid4().hex[:10]
    service_id = None
    try:
        async with client('config', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            created = await api.post('/mcp/add', json={
                'name': name, 'server_url': url, 'description': 'Owned Planning failure probe',
                'source': 'local', 'tags': ['automation', 'd3'], 'enabled': True,
                'ingroup_permission': 'PRIVATE', 'skip_health_check': False,
                'shared_fields': {'server_url': False, 'authorization_token': False},
            })
            assert_status(created, 200)
            listed = await api.get('/mcp/list')
            assert_status(listed, 200)
            matching = [row for row in listed.json().get('remote_mcp_server_list', [])
                        if (row.get('remote_mcp_server_name') or row.get('name')) == name]
            assert len(matching) == 1, 'Owned MCP service is not uniquely registered'
            service_id = int(matching[0]['mcp_id'])
            register_asset('owned_mcp', name, service_id, owner_case_id=CASE_ID,
                           cleanup={'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                                    'path': f'/mcp/{service_id}', 'allowed_statuses': [200, 404]})
            refreshed = await api.post('/mcp/refresh-tools', params={'mcp_id': service_id})
            assert_status(refreshed, 200)
            scanned = await api.get('/tool/scan_tool')
            assert_status(scanned, 200)
            response = await api.get('/tool/list')
            assert_status(response, 200)
            tools = [row for row in response.json() if row.get('source') == 'mcp'
                     and row.get('usage') == name and row.get('origin_name') == 'always_fail']
            assert len(tools) == 1, 'Owned deterministic failure tool was not registered'
            tool_id = int(tools[0].get('tool_id') or tools[0]['id'])
        yield tool_id
    finally:
        if service_id is not None:
            async with client('config', token=identity.access_token) as api:
                deleted = await api.delete(f'/mcp/{service_id}')
            assert_status(deleted, (200, 404))
            mark_asset_state('owned_mcp', name, 'DELETED')


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_agt_025(tenant_a_admin):
    async with owned_failure_tool(tenant_a_admin) as tool_id:
        async with _draft_agent(tenant_a_admin, name_prefix='planning-failure', enabled_tool_ids=[tool_id]) as (agent_id, _):
            for attempt in (1, 2):
                marker = 'PLAN_FAILURE_' + uuid.uuid4().hex
                assert not fault_calls(marker), 'Failure marker was already used'
                run_id = None
                try:
                    async with client('runtime', token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
                        async with api.stream('POST', '/agent/run', json={
                            'agent_id': agent_id, 'history': [], 'is_debug': True, 'enable_plan': True,
                            'query': (
                                'Create exactly one three-step plan using create_plan. '
                                'Step 1: state that this is a dependency failure probe and complete it. '
                                f'Step 2: call the bound always_fail tool with code="{marker}" exactly once; '
                                'observe its real error and mark that step skipped, not completed. '
                                'Step 3: complete a bounded failure report; do not retry the failed tool '
                                f'or pretend it succeeded. The final answer must contain the actual error code {marker}. '
                                'Use update_plan_step to record progress and finish this run.'
                                ' Return inline plain text only: do not write, generate, upload or attach any files.'
                            ),
                        }) as response:
                            assert_status(response, 200)
                            run_id = response.headers.get('run_id')
                            assert run_id and run_id.startswith('debug-'), 'Missing owned debug run identifier'
                            events = await read_sse_with_evidence(response, f'{CASE_ID}-planning-{attempt}',
                                                                 secrets=(tenant_a_admin.access_token, tenant_a_admin.refresh_token))
                    receipts = fault_calls(marker)
                    await clean_generated_files(tenant_a_admin, events)
                    write_case_evidence(f'{CASE_ID}-failure-{attempt}', {
                        'run_id': run_id, 'agent_id': agent_id, 'marker': marker, 'wire_calls': receipts,
                    }, secrets=(tenant_a_admin.access_token, tenant_a_admin.refresh_token))
                    assert len(receipts) == 1, 'Failed tool was retried or never invoked'
                    assert_failed_plan(events, receipts, marker)
                except BaseException as exc:
                    if run_id is not None:
                        try:
                            async with client('runtime', token=tenant_a_admin.access_token) as stopper:
                                stopped = await stopper.get(f'/agent/stop/{run_id}')
                            assert_status(stopped, 200)
                        except Exception as cleanup_error:
                            exc.add_note(f'Owned Planning stop failed: {type(cleanup_error).__name__}')
                    raise
