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


def external_context_has_marker(events, marker):
    """Only retrieved external context, not model reasoning or echo, is proof."""
    for event in events:
        data = event.get('data')
        if not isinstance(data, dict) or data.get('type') != 'execution_logs':
            continue
        content = data.get('content')
        if not isinstance(content, str) or '#### External Memory\n' not in content:
            continue
        external = content.split('#### External Memory\n', 1)[1].split('\n#### ', 1)[0]
        if marker in external:
            return True
    return False


async def run_memory_agent(identity, agent_id, query, phase, *, expected_external=None):
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
        if expected_external is not None:
            observed = external_context_has_marker(events, expected_external)
            write_case_evidence(CASE_ID + '-' + phase + '-context', {
                'external_memory_context_present': observed,
            })
            assert observed, 'External Provider result did not reach runtime memory context'
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
    lookup, marker = 'MEMLOOKUP-' + nonce, 'EXTMEM-' + nonce
    local_nonce = uuid4().hex
    local_lookup, local_marker = 'LOCALLOOKUP-' + local_nonce, 'LOCALMEM-' + local_nonce
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
            answer = await run_memory_agent(identity, agent_id, query, 'initial', expected_external=marker)
            observed = await mock.counts()
            assert observed.get('search', 0) > before.get('search', 0), 'Agent did not query external Provider'
            assert marker in answer, 'Agent final answer did not use retrieved external memory'
            # Hot-update only this owned Provider to an empty org. Fresh
            # conversations prevent an old answer in chat history from passing.
            empty_org = mock.org + '-empty'
            updated = await api.put(prefix, json={'provider_name': name + '-updated',
                'timeout_seconds': 2, 'params': mock.provider_params(org=empty_org)})
            assert_status(updated, 200)
            reread = await api.get(prefix)
            assert_status(reread, 200)
            assert reread.json()['timeout_seconds'] == 2 and api_key not in reread.text
            empty_search = await api.post(prefix + '/test-search', json={'query': lookup, 'top_k': 10})
            assert_status(empty_search, 200)
            assert empty_search.json()['items'] == [], 'Updated organization unexpectedly returned memories'
            old_before, new_before = await mock.counts(), await mock.counts(org=empty_org)
            missing = await run_memory_agent(identity, agent_id, query, 'hot-update')
            old_after, new_after = await mock.counts(), await mock.counts(org=empty_org)
            write_case_evidence(CASE_ID + '-hot-update-wire', {
                'old_scope_search_delta': old_after.get('search', 0) - old_before.get('search', 0),
                'new_scope_search_delta': new_after.get('search', 0) - new_before.get('search', 0),
                'empty_scope_items': len(empty_search.json()['items']),
                'old_answer_present': marker in missing,
                'missing_answer_present': 'NOT_FOUND' in missing,
            })
            assert old_after.get('search', 0) == old_before.get('search', 0), 'Runtime searched the stale organization'
            assert new_after.get('search', 0) > new_before.get('search', 0), 'Runtime did not search the updated organization'
            assert marker not in missing and 'NOT_FOUND' in missing, 'Updated empty memory context did not produce NOT_FOUND'
            assert_status(await api.put(prefix, json={'params': params}), 200)
            # User long-term memory is loaded in full, not query-filtered.
            # Seed it only after the empty-organization acceptance is complete.
            local = await api.post('/memory/long-term/user/versions', json={
                'content': f'Local lookup {local_lookup} has unique answer {local_marker}',
                'expected_active_version_id': None})
            assert_status(local, 201)
            for phase, status, delay in (('unavailable', 503, 0), ('timeout', 200, 3)):
                await mock.fault(status, delay)
                failed = await api.post(prefix + '/test-search', json={'query': lookup, 'top_k': 10})
                assert_status(failed, 400)
                diagnostic = await api.get(prefix)
                assert_status(diagnostic, 200)
                expected_code = 'timeout' if delay else 'provider_error'
                assert diagnostic.json()['last_error_code'] == expected_code
                fallback = await run_memory_agent(identity, agent_id,
                        f'Return the unique local memory answer for {local_lookup}.', 'local-' + phase)
                assert local_marker in fallback, 'External Provider fault blocked local memory context'
                write_case_evidence(CASE_ID + '-' + phase + '-receipt', {
                    'profile': 'mock', 'error_code': expected_code, 'local_fallback': True})
                await mock.fault()
            # Completed turns are legitimately ingested back into the Provider.
            # A fresh lookup avoids old query echoes/thinking outranking the
            # seed in the lexical Mock. Keep the same Provider/org/Agent and
            # local memory: rebuilding or clearing them would hide recovery bugs.
            recovery_nonce = uuid4().hex
            recovery_lookup = 'RECOVERYLOOKUP-' + recovery_nonce
            recovery_marker = 'RECOVERYANSWER-' + recovery_nonce
            recovery_ingest = await api.post(prefix + '/test-ingest', json={'units': [{
                'event_id': recovery_nonce, 'event_type': 'memory_stored', 'unit_type': 'text',
                'unit_content': f'Nexent lookup {recovery_lookup} has unique answer {recovery_marker}',
                'metadata': {'case_id': CASE_ID, 'run_marker': recovery_nonce}}]})
            assert_status(recovery_ingest, 200)
            assert recovery_ingest.json()['accepted_count'] == 1 and recovery_ingest.json()['rejected_count'] == 0
            recovery_search = await api.post(prefix + '/test-search', json={
                'query': recovery_lookup, 'top_k': 10})
            assert_status(recovery_search, 200)
            matches = recovery_search.json()['items']
            seed_found = any(recovery_marker in item['content'] and item.get('is_external') is True
                             for item in matches)
            local_found = any(local_marker in item['content'] for item in matches)
            write_case_evidence(CASE_ID + '-recovery-search', {
                'seed_found': seed_found, 'items': len(matches),
                'local_answer_present': local_found,
                'lookup': recovery_lookup,
            })
            assert seed_found, 'Same external Provider did not recover its ingest/search path'
            assert not local_found, 'Fresh recovery lookup returned unrelated local dialogue'
            # The query contains only the independent lookup, never its answer.
            # This is still a real Agent/LLM call, not a fixture-supplied answer.
            recovery_before = await mock.counts()
            recovered = await run_memory_agent(identity, agent_id, recovery_lookup, 'recovery',
                                                expected_external=recovery_marker)
            recovery_after = await mock.counts()
            search_delta = recovery_after.get('search', 0) - recovery_before.get('search', 0)
            write_case_evidence(CASE_ID + '-recovery-wire', {
                'search_delta': search_delta, 'expected_answer_present': recovery_marker in recovered,
                'local_answer_present': local_marker in recovered,
            })
            assert search_delta > 0, 'Recovery Agent did not query the same external Provider'
            assert recovery_marker in recovered, 'Recovery Agent did not consume the fresh external memory'
            assert local_marker not in recovered, 'Recovery Agent returned the unrelated local memory'
            write_case_evidence(CASE_ID + '-summary', {'profile': 'mock', 'real_llm': True,
                'initial_hit': marker in answer, 'updated_org_has_no_hit': marker not in missing,
                'recovered_hit': recovery_marker in recovered, 'wire_counts': await mock.counts()}, secrets=(api_key,))
