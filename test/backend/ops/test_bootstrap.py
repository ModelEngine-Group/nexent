# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit proof for operations lifecycle, launcher and startup configuration."""

import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from ops.api.application import create_app
from ops.lifespan import ops_lifespan
import ops_service

BACKEND = Path(__file__).resolve().parents[3] / 'backend'


def test_health_follows_application_lifetime():
    app = create_app()
    client = TestClient(app)
    assert client.get('/health/live').json() == {'status': 'alive'}
    before = client.get('/health/ready')
    assert before.status_code == 503
    assert before.json() == {'status': 'not_ready'}

    with client:
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 200
        assert client.get('/health/ready').json() == {'status': 'ready'}
        assert client.get('/openapi.json').json()['paths'] == {}
        assert client.get('/docs').status_code == 200

    assert app.state.ready is False
    assert client.get('/health/ready').status_code == 503


@pytest.mark.asyncio
async def test_exceptional_shutdown_clears_readiness():
    app = create_app()
    with pytest.raises(RuntimeError, match='owned task failed'):
        async with ops_lifespan(app):
            assert app.state.ready is True
            raise RuntimeError('owned task failed')
    assert app.state.ready is False


def test_app_instances_do_not_share_readiness():
    first, second = create_app(), create_app()
    with TestClient(first):
        assert first.state.ready is True
        assert second.state.ready is False


def test_launcher_uses_operations_settings(mocker):
    run = mocker.patch('ops_service.uvicorn.run')
    mocker.patch('ops_service.OPS_PORT', 12345)
    config = {'version': 1}
    build_config = mocker.patch('ops_service.get_uvicorn_logging_config', return_value=config)
    ops_service.main()
    build_config.assert_called_once_with(categories=['ops'])
    run.assert_called_once_with(ops_service.app, host='0.0.0.0', port=12345, log_config=config)


def config_process(overrides):
    """Read real centralized settings without inherited business configuration."""
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in {
            'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC',
            'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'HOME',
        }
    }
    environment.update(PYTHON_DOTENV_DISABLED='1', **overrides)
    return subprocess.run(
        [sys.executable, '-c',
         'import json; from contracts.constants.environment import OPS_PORT, LOG_LEVEL; '
         'print(json.dumps([OPS_PORT, LOG_LEVEL]))'],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=20,
    )


@pytest.mark.parametrize(('overrides', 'expected'), [
    ({}, [5016, 'INFO']),
    ({'OPS_PORT': '1', 'LOG_LEVEL': 'DEBUG'}, [1, 'DEBUG']),
    ({'OPS_PORT': '65535'}, [65535, 'INFO']),
])
def test_configuration_defaults_overrides_and_port_boundaries(overrides, expected):
    result = config_process(overrides)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize(('overrides', 'setting'), [
    ({'OPS_PORT': '0'}, 'OPS_PORT'),
    ({'OPS_PORT': '-1'}, 'OPS_PORT'),
    ({'OPS_PORT': '65536'}, 'OPS_PORT'),
    ({'OPS_PORT': 'bad'}, 'OPS_PORT'),
])
def test_invalid_configuration_fails_with_setting_name(overrides, setting):
    result = config_process(overrides)
    assert result.returncode != 0
    assert 'ValueError' in result.stderr
    assert setting in result.stderr
