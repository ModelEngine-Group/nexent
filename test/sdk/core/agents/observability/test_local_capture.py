# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local capture binds actual tool calls and cancelled worker outcomes."""

import importlib
import json
from types import SimpleNamespace

import pytest
from opentelemetry import trace

from nexent.core.agents.resources.monitoring import _wrap_tool_with_monitoring
from nexent.core.utils.observer import MessageObserver


def test_local_tool_schema_and_call_identity_are_captured(spans, monkeypatch):
    monkeypatch.setattr(spans.manager._config, 'provider', 'local_file')
    observer = MessageObserver()
    seen = []
    tool = SimpleNamespace(name='lookup', description='Tool definition', inputs={'query': {'type': 'string'}},
                           forward=lambda query: seen.append(dict(trace.get_current_span().attributes)) or 'answer')
    _wrap_tool_with_monitoring(tool, 'root', observer=observer)
    with observer.tool_call_context('call-actual'):
        assert tool.forward(query='question') == 'answer'
    assert seen[0]['nexent.local.nexent.call_id'] == 'call-actual'
    definition = json.loads(seen[0]['nexent.local.tool.definition'])
    assert definition['inputs'] == tool.inputs
    assert definition['name'] == 'lookup'
    assert observer.current_tool_call_id is None


@pytest.mark.parametrize('outcome,boundary,expected', [
    ('completed', False, 'completed'),
    ('stopped', None, 'cancelled'),
    ('stopped', False, 'cancelled'),
    ('stopped', True, 'cancelled'),
    ('stopped', 'true', 'cancelled'),
    ('stopped', 1, 'cancelled'),
    ('failed', True, 'failed'),
    ('failed', False, 'failed'),
    (None, True, 'interrupted'),
])
def test_local_worker_preserves_business_outcome(spans, monkeypatch, outcome, boundary, expected):
    module = importlib.import_module('nexent.core.agents.orchestration.entry')
    monkeypatch.setattr(spans.manager._config, 'provider', 'local_file')
    info = SimpleNamespace(agent_config=None, query='q', model_config_list=[], history=[], attempt_outcome=None)
    if boundary is not None:
        info.observer = SimpleNamespace(boundary_reached=boundary)
    monkeypatch.setattr(module, '_agent_run_thread', lambda run, **_: setattr(run, 'attempt_outcome', outcome))
    module.agent_run_thread(info)
    root = next(span for span in spans.exporter.get_finished_spans() if span.name == 'agent.run')
    assert root.attributes['nexent.business_status'] == expected
    assert root.attributes['nexent.cancelled'] == (expected == 'cancelled')
    assert info.attempt_outcome == outcome


@pytest.mark.parametrize("request_query", ["原始用户问题", "", None])
def test_worker_input_uses_original_request_query_with_prepared_fallback(spans, monkeypatch, request_query):
    from nexent.monitor import AgentRunMetadata, agent_monitoring_context

    module = importlib.import_module('nexent.core.agents.orchestration.entry')
    monkeypatch.setattr(spans.manager._config, 'provider', 'local_file')
    info = SimpleNamespace(agent_config=None, query='prepared question with attachment and time',
                           model_config_list=[], history=[], attempt_outcome='completed')
    captured = []
    monkeypatch.setattr(module, '_agent_run_thread',
                        lambda run, **_: captured.append(dict(trace.get_current_span().attributes)))
    with agent_monitoring_context(AgentRunMetadata(query=request_query)):
        module.agent_run_thread(info)
    root = next(span for span in spans.exporter.get_finished_spans() if span.name == 'agent.run')
    expected = request_query if request_query is not None else info.query
    assert captured[0]['nexent.local.input.value'] == expected
    assert root.attributes.get('input.preview', '') == expected
