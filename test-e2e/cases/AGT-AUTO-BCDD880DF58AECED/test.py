# D3 AGENT-IT integration test for memory pre-search (memory-presearch).
# Case ID: AGT-AUTO-BCDD880DF58AECED
#
# Verifies that create_agent_config runs memory pre-search through
# run_blocking('memory-presearch', lane='model-tool-io', owner='runtime')
# and that an external memory provider search failure degrades to
# external_results=None (logging event=external_provider_search_failed)
# without blocking long/short-term memory population or agent startup.

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest


CASE_ID = 'AGT-AUTO-BCDD880DF58AECED'

FIXED_SEARCH_RESULT = 'Found 2 memories'


class _FixedSearchResult:
    def __init__(self, memory_id, content, score, source='external', metadata=None):
        self.memory_id = memory_id
        self.external_id = memory_id
        self.content = content
        self.score = score
        self.source = source
        self.metadata = metadata or {}


class _ExternalProviderStub:
    def __init__(self, results=None, error=None):
        self.results = list(results or [])
        self.error = error
        self.search_calls = []

    async def search_all_enabled(self, tenant_id, request, limit):
        self.search_calls.append({'tenant_id': tenant_id, 'request': request, 'limit': limit})
        if self.error is not None:
            raise self.error
        return list(self.results)


class _MemoryContextServiceStub:
    def __init__(self):
        self.build_calls = []

    async def build_context(self, **kwargs):
        self.build_calls.append(kwargs)
        return SimpleNamespace(tenant_long_term=[], user_long_term=[])


class _FixedSearchToolSpy:
    def __init__(self):
        self.forward_calls = []
        self.external_results = None
        self.memory_context_service = None
        self.tenant_id = ''
        self.user_id = ''
        self.agent_id = ''
        self.conversation_id = ''
        self.embedding_configured = False

    def forward(self, query, top_k=5):
        self.forward_calls.append({'query': query, 'top_k': top_k})
        return FIXED_SEARCH_RESULT


class _RunBlockingSpy:
    def __init__(self):
        self.calls = []

    async def __call__(self, task_name, fn, *args, lane=None, owner=None, **kwargs):
        self.calls.append({
            'task_name': task_name,
            'lane': lane,
            'owner': owner,
            'args': args,
            'kwargs': kwargs,
        })
        if callable(fn):
            return fn(*args)
        return None


def _minimal_agent_info():
    return {
        'name': 'mem-presearch-agent',
        'description': 'memory presearch test agent',
        'model_ids': [],
        'max_steps': 15,
        'requested_output_tokens': None,
        'provide_run_summary': False,
        'allow_chat_metadata': False,
        'enable_context_manager': False,
        'sandbox_policy': None,
        'context_policy': None,
        'verification_config': {},
    }


def _setup_memory_runtime(monkeypatch, provider):
    import agents.create_agent_info as mod

    run_blocking_spy = _RunBlockingSpy()
    fixed_tool_spy = _FixedSearchToolSpy()
    context_service_stub = _MemoryContextServiceStub()

    monkeypatch.setattr(mod, 'search_agent_info_by_agent_id', lambda **kwargs: _minimal_agent_info())
    monkeypatch.setattr(mod, 'query_sub_agent_relations', lambda **kwargs: [])

    async def _no_tools(*args, **kwargs):
        return []

    monkeypatch.setattr(mod, 'create_tool_config_list', _no_tools)
    monkeypatch.setattr(mod, '_get_external_a2a_agents', lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, '_get_skills_for_template', lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, '_get_skill_script_tools', lambda *args, **kwargs: [])

    async def _no_prompt_templates(*args, **kwargs):
        # AgentConfig.prompt_templates is a mapping.  Returning a list makes
        # the fixture fail Pydantic validation before memory pre-search runs.
        return {}

    monkeypatch.setattr(mod, 'prepare_prompt_templates', _no_prompt_templates)
    monkeypatch.setattr(mod, 'get_local_python_authorized_imports', lambda: [])

    def _memory_context(*args, **kwargs):
        return SimpleNamespace(
            user_config=SimpleNamespace(memory_switch=True, external_provider_top_k=5),
            tenant_id='tenant-test',
            user_id='user-test',
            agent_id='agent-test',
        )

    monkeypatch.setattr(mod, 'build_memory_context', _memory_context)
    monkeypatch.setattr(mod, 'run_blocking', run_blocking_spy)
    monkeypatch.setattr(mod, '_create_fixed_search_memory_tool', lambda: fixed_tool_spy)
    monkeypatch.setattr(mod, 'get_memory_external_provider_service', lambda: provider)

    monkeypatch.setattr(
        'services.memory_context_service.get_memory_context_service',
        lambda: context_service_stub,
    )
    monkeypatch.setattr(
        'services.memory_backend_adapter.build_memory_service_for_agent',
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        'services.memory_record_service._resolve_tenant_embedding_model_info',
        lambda tenant_id: {'model_id': 1},
    )
    monkeypatch.setattr(
        mod,
        'tenant_config_manager',
        SimpleNamespace(get_context_policy=lambda tenant_id: {}),
    )

    return SimpleNamespace(
        run_blocking=run_blocking_spy,
        fixed_tool=fixed_tool_spy,
        context_service=context_service_stub,
        provider=provider,
    )


async def _run_create_agent_config(monkeypatch, provider, query):
    import agents.create_agent_info as mod

    handle = _setup_memory_runtime(monkeypatch, provider)
    config = await mod.create_agent_config(
        agent_id='agent-test',
        tenant_id='tenant-test',
        user_id='user-test',
        last_user_query=query,
        allow_memory_search=True,
    )
    return config, handle


def _assert_search_memory_event(config):
    tool_events = [
        event
        for event in config.pre_run_tool_events
        if event.get('type') == 'tool' and event.get('tool_name') == 'search_memory'
    ]
    assert tool_events, 'pre_run_tool_events must contain a search_memory tool event'
    arguments = tool_events[0].get('tool_arguments') or {}
    assert arguments.get('top_k') == 5
    return arguments


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_memory_presearch_run_blocking_and_provider_degradation(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger='create_agent_info')

    provider = _ExternalProviderStub(results=[
        _FixedSearchResult('mem-1', 'tenant preference A', 0.9, source='stub'),
        _FixedSearchResult('mem-2', 'user preference B', 0.8, source='stub'),
    ])
    config, handle = await _run_create_agent_config(monkeypatch, provider, 'hello memory')

    assert config is not None
    presearch_calls = [
        call
        for call in handle.run_blocking.calls
        if call['task_name'] == 'memory-presearch'
    ]
    assert presearch_calls, 'memory pre-search must run via run_blocking'
    call = presearch_calls[0]
    assert call['lane'] == 'model-tool-io'
    assert call['owner'] == 'runtime'
    assert tuple(call['args']) == ('hello memory', 5)

    assert handle.fixed_tool.external_results is not None
    assert len(handle.fixed_tool.external_results) == 2
    assert handle.fixed_tool.forward_calls
    assert handle.fixed_tool.forward_calls[-1] == {'query': 'hello memory', 'top_k': 5}
    assert provider.search_calls

    arguments = _assert_search_memory_event(config)
    assert arguments.get('query') == 'hello memory'

    logs = [
        event
        for event in config.pre_run_tool_events
        if event.get('type') == 'execution_logs'
    ]
    assert logs and logs[-1].get('content') == FIXED_SEARCH_RESULT

    failing_provider = _ExternalProviderStub(error=RuntimeError('search unavailable'))
    config2, handle2 = await _run_create_agent_config(monkeypatch, failing_provider, 'hello memory')

    assert config2 is not None
    assert handle2.fixed_tool.external_results is None
    assert handle2.fixed_tool.forward_calls
    _assert_search_memory_event(config2)

    assert 'event=external_provider_search_failed' in caplog.text

    boundary_provider = _ExternalProviderStub(results=[])
    config3, handle3 = await _run_create_agent_config(monkeypatch, boundary_provider, '')

    assert config3 is not None
    assert handle3.fixed_tool.forward_calls
    assert handle3.fixed_tool.forward_calls[-1] == {'query': '', 'top_k': 5}
    arguments3 = _assert_search_memory_event(config3)
    assert arguments3.get('query') == ''
