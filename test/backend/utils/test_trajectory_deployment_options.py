# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment provider owns mutually exclusive capture and fixed query defaults."""

import runpy
from unittest.mock import Mock

import pytest


def test_trajectory_default_directory_and_removed_configuration(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', lambda **kwargs: False)
    monkeypatch.delenv('TRAJECTORY_ROOT_DIR', raising=False)
    monkeypatch.setenv('TRAJECTORY_STORAGE_ROOT_ID', 'obsolete')
    monkeypatch.setenv('TRAJECTORY_QUERY_TIMEOUT_SECONDS', '1')
    monkeypatch.setenv('MONITORING_TRACE_SINK', 'both')
    config = runpy.run_module('contracts.constants.environment', run_name='trajectory_deployment_test')
    assert config['TRAJECTORY_ROOT_DIR'] == '/mnt/nexent-data/trajectory'
    for key in ('TRAJECTORY_STORAGE_ROOT_ID', 'TRAJECTORY_QUERY_TIMEOUT_SECONDS', 'MONITORING_TRACE_SINK'):
        assert key not in config


def test_store_initializes_directory_without_root_id_and_preserves_manifest(tmp_path):
    from uuid import uuid4

    from infrastructure.observability.trajectory_store import (
        CaptureIdentity,
        TrajectoryFileStore,
    )

    root = tmp_path / 'trajectory'
    identity = CaptureIdentity('tenant', 'user', '1', '2')
    store = TrajectoryFileStore(root, authorize=Mock())
    with store.start(identity, str(uuid4()), str(uuid4()), core_type='smolagents') as writer:
        writer.finish('completed')
    meta = store.manifest(identity)
    assert 'storage_root_id' not in meta
    reopened = TrajectoryFileStore(root, authorize=Mock())
    assert reopened.manifest(identity) == meta


def test_trajectory_budget_defaults_to_thirty_seconds():
    from ops.services.trajectory.primitives import Budget
    from ops.services.trajectory.service import TrajectoryService

    assert Budget().seconds == 30
    assert TrajectoryService(Mock(), Mock(), Mock()).budget().seconds == 30


@pytest.mark.parametrize('provider', ['both', 'grafana', 'zipkin', 'invalid'])
def test_removed_or_invalid_deployment_provider_is_rejected(monkeypatch, provider):
    monkeypatch.setattr('dotenv.load_dotenv', lambda **kwargs: False)
    monkeypatch.setenv('MONITORING_PROVIDER', provider)
    with pytest.raises(ValueError, match='MONITORING_PROVIDER'):
        runpy.run_module('contracts.constants.environment', run_name='trajectory_deployment_test')


def test_local_provider_disables_metrics_without_changing_remote_default(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', lambda **kwargs: False)
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_METRICS_ENABLED', 'true')
    for provider, expected in [('local_file', False), ('otlp', True)]:
        monkeypatch.setenv('MONITORING_PROVIDER', provider)
        config = runpy.run_module('contracts.constants.environment', run_name='trajectory_deployment_test')
        assert config['OTEL_EXPORTER_OTLP_METRICS_ENABLED'] is expected
