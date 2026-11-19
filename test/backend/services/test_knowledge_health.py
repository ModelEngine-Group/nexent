# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HEALTH-SI-02/04 preserves the public result and bounds the managed operation."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.storage.errors import DeadlineExceeded, ScopeDenied, Unavailable


@pytest.fixture
def health():
    from management.services.knowledge_base import health

    return health


def port(count):
    @contextmanager
    def ports(*, context):
        yield SimpleNamespace(count=count)
    return ports


def test_health_check_healthy(health):
    result = health.health_result(ports=port(Mock(return_value=2)))
    assert result == {'status': 'healthy', 'elasticsearch': 'connected', 'indices_count': 2}


def test_health_check_unhealthy(health):
    with pytest.raises(RuntimeError, match='Health check failed: Connection error'):
        health.health_result(ports=port(Mock(side_effect=RuntimeError('Connection error'))))


def test_health_check_success_status_200(health):
    result = health.health_result(ports=port(Mock(return_value=2)))
    assert isinstance(result, dict)
    assert result['status'] == 'healthy' and result['elasticsearch'] == 'connected'


@pytest.mark.parametrize('error', [Unavailable(), ScopeDenied()])
def test_es_provider_failure_preserves_existing_empty_list_policy(health, error):
    count = Mock(side_effect=error)
    assert health.health_result(ports=port(count))['indices_count'] == 0
    count.assert_called_once()


def test_deadline_is_not_swallowed_by_existing_empty_list_policy(health):
    with pytest.raises(DeadlineExceeded):
        health.health_result(ports=port(Mock(side_effect=DeadlineExceeded())))


def test_datamate_configuration_failure_is_not_es_healthy_zero(health, mocker):
    from contracts.knowledge import VectorDatabaseType

    with pytest.raises(ValueError, match='tenant_id must be provided'):
        health.health_result(VectorDatabaseType.DATAMATE)
    mocker.patch('management.services.knowledge_base.providers.configuration.datamate_configuration_url', return_value='')
    with pytest.raises(ValueError, match='DataMate URL not configured for tenant selected'):
        health.health_result(VectorDatabaseType.DATAMATE, 'selected')


def test_datamate_uses_same_root_context_for_si_config_and_count(health, mocker):
    from time import monotonic

    from contracts.knowledge import VectorDatabaseType
    from nexent.storage.models import OperationContext

    config = mocker.patch('management.services.knowledge_base.providers.configuration.datamate_configuration_url', return_value='https://owned.invalid')
    count = mocker.patch('infrastructure.vdb.datamate_inventory.datamate_collection_count', return_value=3)
    ctx = OperationContext('owned', monotonic()+5)
    assert health.health_result(VectorDatabaseType.DATAMATE, 'selected', context=ctx)['indices_count'] == 3
    config.assert_called_once_with('selected', context=ctx)
    count.assert_called_once_with('https://owned.invalid', context=ctx)


@pytest.mark.asyncio
async def test_managed_operation_propagates_context_and_always_cancels(health, mocker):
    captured = {}
    async def run(name, action, *args, **kwargs):
        captured.update(kwargs)
        return {'owned': True}
    mocker.patch.object(health, 'run_blocking', side_effect=run)
    assert await health.check_knowledge_health() == {'owned': True}
    assert captured['lane'] == 'control-io' and captured['owner'] == 'management.knowledge.health'
    assert captured['context'].cancelled.is_set()


@pytest.mark.asyncio
async def test_root_timeout_is_one_warning_and_cancels(health, mocker, caplog):
    from time import monotonic

    from nexent.storage.models import OperationContext

    original = OperationContext
    captured = []
    def short(operation_id, deadline, cancelled):
        ctx = original(operation_id, monotonic()+.02, cancelled=cancelled)
        captured.append(ctx)
        return ctx
    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()
    mocker.patch.object(health, 'OperationContext', side_effect=short)
    mocker.patch.object(health, 'run_blocking', side_effect=blocked)
    with pytest.raises(DeadlineExceeded):
        await health.check_knowledge_health()
    assert captured[0].cancelled.is_set()
    assert len([r for r in caplog.records if r.levelname == 'WARNING' and 'knowledge_health_timeout' in r.message]) == 1
    assert not [r for r in caplog.records if r.levelname == 'ERROR']


@pytest.mark.asyncio
async def test_configuration_read_timeout_keeps_its_existing_warning_only(health, mocker, caplog):
    from contracts.errors.exceptions import RuntimeServiceTimeoutError
    from contracts.knowledge import VectorDatabaseType

    @contextmanager
    def refused(*args, **kwargs):
        raise DeadlineExceeded()
        yield
    mocker.patch('infrastructure.datamate_configuration.datamate_configuration_ports', refused)
    async def run(name, action, *args, **kwargs):
        return action(*args, context=kwargs['context'])
    mocker.patch.object(health, 'run_blocking', side_effect=run)
    with pytest.raises(RuntimeServiceTimeoutError):
        await health.check_knowledge_health(VectorDatabaseType.DATAMATE, 'selected')
    warnings = [r for r in caplog.records if r.levelname == 'WARNING']
    assert len(warnings) == 1 and 'datamate_configuration_timeout' in warnings[0].message
    assert not [r for r in caplog.records if r.levelname == 'ERROR']


@pytest.mark.asyncio
async def test_external_read_timeout_is_one_redacted_warning(health, mocker, caplog):
    import httpx
    from contracts.knowledge import VectorDatabaseType

    mocker.patch.object(health, 'run_blocking', side_effect=httpx.ReadTimeout('private-owned-url'))
    with pytest.raises(DeadlineExceeded):
        await health.check_knowledge_health(VectorDatabaseType.DATAMATE, 'selected')
    warnings = [r for r in caplog.records if r.levelname == 'WARNING']
    assert len(warnings) == 1 and 'phase=datamate_request threshold_seconds=5' in warnings[0].message
    assert 'private-owned-url' not in caplog.text
    assert not [r for r in caplog.records if r.levelname == 'ERROR']
