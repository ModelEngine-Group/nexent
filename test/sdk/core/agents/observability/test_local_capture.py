# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local capture binds actual tool calls and cancelled worker outcomes."""

import importlib
import json
from types import SimpleNamespace

import pytest
from nexent.core.agents.nexent_agent import _wrap_tool_with_monitoring
from nexent.core.utils.observer import MessageObserver
from opentelemetry import trace


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


@pytest.mark.parametrize('outcome,expected', [('completed', 'completed'), ('stopped', 'cancelled'), ('failed', 'failed')])
def test_local_worker_preserves_business_outcome(spans, monkeypatch, outcome, expected):
    module = importlib.import_module('nexent.core.agents.run_agent')
    monkeypatch.setattr(spans.manager._config, 'provider', 'local_file')
    info = SimpleNamespace(agent_config=None, query='q', model_config_list=[], history=[], attempt_outcome=None)
    monkeypatch.setattr(module, '_agent_run_thread', lambda run: setattr(run, 'attempt_outcome', outcome))
    module.agent_run_thread(info)
    root = next(span for span in spans.exporter.get_finished_spans() if span.name == 'agent.run')
    assert root.attributes['nexent.business_status'] == expected
    assert root.attributes['nexent.cancelled'] == (expected == 'cancelled')
