# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Only trusted deployment constants supply owner identity and the SYSTEM profile."""

from types import SimpleNamespace

import pytest
from contracts import constants
from runtime.adapters.nexent.sandbox import get_runtime_sandbox_options


@pytest.fixture
def settings(monkeypatch):
    value = SimpleNamespace(
        NEXENT_SANDBOX_PROVIDER='kubernetes', NEXENT_SANDBOX_ENABLED=True,
        IS_DEPLOYED_BY_KUBERNETES=True, NEXENT_RUNTIME_DEPLOYMENT_ID='release',
        NEXENT_RUNTIME_POD_NAMESPACE='ns', NEXENT_RUNTIME_POD_NAME='pod',
        NEXENT_RUNTIME_POD_UID='uid', NEXENT_RUNTIME_POD_IP='10.0.0.1',
        NEXENT_SANDBOX_DOCKER_IMAGE='sandbox:fixed', NEXENT_SANDBOX_WORKSPACE_CLAIM='workspace',
        NEXENT_SANDBOX_MEMORY_LIMIT_MB=2048, NEXENT_SANDBOX_CPU_QUOTA=1.0,
        NEXENT_SANDBOX_NETWORK_DISABLED=True, NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT='',
        NEXENT_SANDBOX_EXECUTION_UID=1000, NEXENT_SANDBOX_EXECUTION_GID=1000,
    )
    monkeypatch.setattr(constants, 'environment', value, raising=False)
    return value


def test_owner_epoch_and_profile_are_stable_within_the_process(settings):
    first, second = get_runtime_sandbox_options(), get_runtime_sandbox_options()
    assert first['owner'] == second['owner']
    assert first['owner'].pod_uid == 'uid'
    assert first['system_profile'].execution_image == 'sandbox:fixed'
    assert first['system_profile'].workspace_mode == 'bind'
    assert first['system_profile'].fingerprint == second['system_profile'].fingerprint


def test_docker_does_not_require_kubernetes_identity(settings):
    settings.NEXENT_SANDBOX_PROVIDER = 'docker'
    settings.NEXENT_RUNTIME_POD_UID = ''
    assert get_runtime_sandbox_options() == {}


def test_disabled_provider_does_not_require_owner_or_claim(settings):
    settings.NEXENT_SANDBOX_ENABLED = False
    settings.NEXENT_RUNTIME_POD_UID = ''
    settings.NEXENT_SANDBOX_WORKSPACE_CLAIM = ''
    assert get_runtime_sandbox_options() == {'provider': 'kubernetes', 'enabled': False}


@pytest.mark.parametrize('field,value', [
    ('IS_DEPLOYED_BY_KUBERNETES', False), ('NEXENT_RUNTIME_POD_UID', ''),
    ('NEXENT_SANDBOX_WORKSPACE_CLAIM', ''), ('NEXENT_SANDBOX_EXECUTION_UID', 0),
    ('NEXENT_SANDBOX_PROVIDER', 'invalid'),
])
def test_incomplete_or_invalid_trusted_configuration_fails(settings, field, value):
    setattr(settings, field, value)
    with pytest.raises(ValueError):
        get_runtime_sandbox_options()
