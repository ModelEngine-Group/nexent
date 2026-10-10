"""Nexent API + real Agent/LLM against a controlled external memory Provider."""

from __future__ import annotations

from uuid import uuid4

import pytest

from d3.assets import temporary_conversation
from shared.case_evidence import read_sse_with_evidence, write_case_evidence
from shared.factories.agent import _draft_agent
from shared.factories.model import owned_configured_model
from shared.factories.provider import owned_provider_client
from shared.factories.tenant import isolated_accounts
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.memory_mock import memory_mock
from shared.sse import assert_terminal_event


CASE_ID = 'AGT-071'


def final_text(events):
    payloads = [event.get('data') for event in events if isinstance(event.get('data'), dict)]
    assert not any(item.get('type') == 'error' for item in payloads), 'Agent emitted a runtime error'
    text = ''.join(item.get('content', '') for item in payloads
                   if item.get('type') == 'final_answer' and isinstance(item.get('content'), str))
    assert text.strip(), 'Missing actual final answer; tool/query echo is not an answer'
    return text


async def run_memory_agent(identity, agent_id, query, phase):
    async with temporary_conversation(identity, 'D3 external memory ' + phase) as conversation_id:
        async with client('runtime', token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream('POST', '/agent/run', json={
                'agent_id': agent_id, 'conversation_id': conversation_id, 'query': query,
                # Debug deliberately disables memory. Publish the owned Agent
                # and exercise the same normal runtime path as a real user.
                'history': [], 'is_debug': False}) as response:
                assert_status(response, 200)
                events = await read_sse_with_evidence(response, CASE_ID + '-' + phase,
                    secrets=(identity.access_token, identity.refresh_token))
        assert_terminal_event(events)
        return final_text(events)


@pytest.mark.stage("D3")
@pytest.mark.case_id("AGT-071")
@pytest.mark.asyncio
async def test_external_memory_real_ingest_search_and_hot_update() -> None:
    # Isolate both provider fan-out and local long-term memory from developer
    # accounts. Cleanup order: Agent -> model -> Provider -> fixture -> tenant.
    async with isolated_accounts(['tenant_a_admin']) as accounts:
        identity = accounts['tenant_a_admin']
        async with memory_mock(identity) as mock, owned_provider_client(identity, owner_case_id=CASE_ID) as api:
            await exercise_external_memory(identity, mock, api)


async def exercise_external_memory(identity, mock, api):
    nonce = uuid4().hex
    lookup, marker, local_marker = 'MEMLOOKUP-' + nonce, 'EXTMEM-' + nonce, 'LOCALMEM-' + nonce
    name = 'case-memory-' + nonce
    api_key = mock.settings['api_key']
    params = mock.provider_params()
    async with owned_configured_model(identity, CASE_ID) as model_id:
        async with _draft_agent(identity, model_ids=[model_id], owner_case_id=CASE_ID) as (agent_id, payload):
            configured = await api.post('/agent/update', json={**payload,
                'duty_prompt': 'Answer using provided memory context. Return only the requested marker. '
                               'If no matching memory exists, return NOT_FOUND. Never invent or store markers.'})
            assert_status(configured, 200)
            published = await api.post(f'/agent/{agent_id}/publish', json={
                'version_name': 'case-memory', 'release_note': 'Owned external memory acceptance'})
            assert_status(published, 200)
            assert_status(await api.post('/memory/config/set', json={'key': 'MEMORY_SWITCH', 'value': True}), 200)
            local = await api.post('/memory/long-term/user/versions', json={
                'content': f'Local lookup LOCALLOOKUP-{nonce} has unique answer {local_marker}',
                'expected_active_version_id': None})
            assert_status(local, 201)
            created = await api.post("/memory/providers", json={
                "provider_name": name,
                "connection_type": "plugin",
                "enabled": True,
                "timeout_seconds": 3,
                "params": params,
            })
            assert_status(created, 200)
            provider_id = int(created.json()["provider_config_id"])
            prefix = f'/memory/providers/{provider_id}'
            # Query never contains the answer marker: echoing input cannot pass.
            query = f'What is the unique answer for {lookup}? Return only that answer from memory.'
            empty = await api.post(prefix + '/test-search', json={'query': lookup, 'top_k': 10})
            assert_status(empty, 200)
            assert empty.json()['items'] == []
            ingested = await api.post(prefix + '/test-ingest', json={'units': [{
                'event_id': nonce, 'event_type': 'memory_stored', 'unit_type': 'text',
                'unit_content': f'Nexent lookup {lookup} has unique answer {marker}',
                'metadata': {'case_id': CASE_ID, 'run_marker': nonce}}]})
            assert_status(ingested, 200)
            assert ingested.json()['accepted_count'] == 1 and ingested.json()['rejected_count'] == 0
            searched = await api.post(prefix + '/test-search', json={'query': lookup, 'top_k': 10})
            assert_status(searched, 200)
            assert any(marker in item['content'] and item.get('is_external') is True for item in searched.json()['items'])
            before = await mock.counts()
            answer = await run_memory_agent(identity, agent_id, query, 'initial')
            observed = await mock.counts()
            assert observed.get('search', 0) > before.get('search', 0), 'Agent did not query external Provider'
            assert marker in answer, 'Agent final answer did not use retrieved external memory'
            # Hot-update only this owned Provider to an empty org. Fresh
            # conversations prevent an old answer in chat history from passing.
            updated = await api.put(prefix, json={'provider_name': name + '-updated',
                'timeout_seconds': 2, 'params': mock.provider_params(org=mock.org + '-empty')})
            assert_status(updated, 200)
            reread = await api.get(prefix)
            assert_status(reread, 200)
            assert reread.json()['timeout_seconds'] == 2 and api_key not in reread.text
            missing = await run_memory_agent(identity, agent_id, query, 'hot-update')
            assert marker not in missing and 'NOT_FOUND' in missing, 'Hot-updated configuration did not affect later runs'
            assert_status(await api.put(prefix, json={'params': params}), 200)
            for phase, status, delay in (('unavailable', 503, 0), ('timeout', 200, 3)):
                await mock.fault(status, delay)
                failed = await api.post(prefix + '/test-search', json={'query': lookup, 'top_k': 10})
                assert_status(failed, 400)
                diagnostic = await api.get(prefix)
                assert_status(diagnostic, 200)
                expected_code = 'timeout' if delay else 'provider_error'
                assert diagnostic.json()['last_error_code'] == expected_code
                fallback = await run_memory_agent(identity, agent_id,
                    f'Return the unique local memory answer for LOCALLOOKUP-{nonce}.', 'local-' + phase)
                assert local_marker in fallback, 'External Provider fault blocked local memory context'
                write_case_evidence(CASE_ID + '-' + phase + '-receipt', {
                    'profile': 'mock', 'error_code': expected_code, 'local_fallback': True})
                await mock.fault()
            recovered = await run_memory_agent(identity, agent_id, query, 'recovery')
            assert marker in recovered, 'External retrieval did not recover after scoped faults'
            write_case_evidence(CASE_ID + '-summary', {'profile': 'mock', 'real_llm': True,
                'initial_hit': marker in answer, 'updated_org_has_no_hit': marker not in missing,
                'recovered_hit': marker in recovered, 'wire_counts': await mock.counts()}, secrets=(api_key,))
