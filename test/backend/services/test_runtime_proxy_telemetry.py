# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""NB-AC02/04/05: runtime propagation and deployed monitoring configuration."""

import ast
from pathlib import Path

import pytest
import yaml
from opentelemetry import context, propagate, trace
from opentelemetry.baggage import set_baggage
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState

from management.services.agent import runtime_client
from nexent.monitor import monitoring


@pytest.fixture
def manager(monkeypatch):
    instance = monitoring.get_monitoring_manager()
    monkeypatch.setattr(instance, '_config', monitoring.MonitoringConfig(enable_telemetry=True))
    monkeypatch.setattr(runtime_client, 'generate_internal_runtime_jwt', lambda *_: 'internal-only-jwt')
    return instance


def test_nb_ac002_internal_jwt_and_w3c_parent_survive_without_baggage(manager):
    span_context = SpanContext(0x1234, 0x5678, True, TraceFlags(1), TraceState([('vendor', 'value')]))
    ctx = trace.set_span_in_context(NonRecordingSpan(span_context))
    token = context.attach(set_baggage('private', 'never-forward', context=ctx))
    try:
        headers = runtime_client._authorization_headers('user', 'tenant')
    finally:
        context.detach(token)
    assert headers['Authorization'] == 'Bearer internal-only-jwt'
    assert headers['traceparent'] == '00-00000000000000000000000000001234-0000000000005678-01'
    assert headers['tracestate'] == 'vendor=value'
    assert set(headers) == {'Authorization', 'traceparent', 'tracestate'}
    parent = trace.get_current_span(propagate.extract(headers)).get_span_context()
    assert parent.trace_id == span_context.trace_id and parent.span_id == span_context.span_id
    assert manager.get_trace_headers() == {}, 'Context leaked beyond the original request'


@pytest.mark.parametrize('condition', ['disabled', 'missing_dependencies', 'injection_error'])
def test_nb_ac003_monitoring_failure_does_not_break_auth(manager, monkeypatch, condition):
    if condition == 'disabled':
        monkeypatch.setattr(manager, '_config', monitoring.MonitoringConfig(enable_telemetry=False))
    elif condition == 'missing_dependencies':
        monkeypatch.setattr(monitoring, 'OPENTELEMETRY_AVAILABLE', False)
    else:
        def fail(*_args):
            raise RuntimeError('controlled propagation failure')
        monkeypatch.setattr(monitoring.propagate, 'inject', fail)
    assert runtime_client._authorization_headers('user', 'tenant') == {'Authorization': 'Bearer internal-only-jwt'}


def test_nb_ac005_propagator_cannot_inject_authorization_or_baggage(manager, monkeypatch):
    def inject(carrier):
        carrier.update(traceparent='parent', Authorization='external-secret', baggage='private-data')
    monkeypatch.setattr(monitoring.propagate, 'inject', inject)
    assert runtime_client._authorization_headers('user', 'tenant') == {
        'Authorization': 'Bearer internal-only-jwt', 'traceparent': 'parent'}


def test_nb_ac004_northbound_enables_existing_monitoring_and_deployment_config():
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root/'backend/apps/northbound_base_app.py').read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'create_app']
    assert len(calls) == 1
    assert any(kw.arg == 'enable_monitoring' and ast.literal_eval(kw.value) is True for kw in calls[0].keywords)
    for name in ['docker-compose.yml', 'docker-compose.prod.yml']:
        services = yaml.safe_load((root/'deploy/docker/compose'/name).read_text())['services']
        assert '../../env/monitoring.env' in services['nexent-northbound']['env_file']
    helm = (root/'deploy/k8s/helm/nexent/charts/nexent-northbound/templates/deployment.yaml').read_text()
    assert 'name: nexent-monitoring-env' in helm.split('envFrom:')[1].split('          env:')[0]
    env = (root/'deploy/env/monitoring.env.example').read_text()
    included = next(line.split('=', 1)[1] for line in env.splitlines() if line.startswith('MONITORING_FASTAPI_INCLUDED_URLS='))
    excluded = monitoring._build_fastapi_excluded_urls(included, '')
    import re
    assert not re.search(excluded, 'http://northbound:5013/nb/v1/generate_title')
    assert not re.search(excluded, 'http://northbound:5013/api/nb/v1/generate_title')
    assert not re.search(excluded, 'http://northbound:5013/api/nb/v1/chat/run')
    assert not re.search(excluded, 'http://runtime:5014/api/agent/internal/northbound/run')
    assert re.search(excluded, 'http://northbound:5013/api/health')
    for route in ('/nb/v1/chat/run', '/nb/v1/generate_title'):
        explicit = monitoring._build_fastapi_excluded_urls(included, route)
        assert any(re.search(pattern, 'http://northbound:5013/api' + route) for pattern in explicit.split(','))
