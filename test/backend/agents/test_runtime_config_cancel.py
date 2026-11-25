# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import Mock

import pytest

from runtime.sandbox_cancel import signal_distributed_cancel


def test_config_cancel_uses_trusted_business_scope_without_runtime_pod_identity():
    redis = Mock()
    redis.eval.return_value = 1
    assert signal_distributed_cancel(redis, deployment_id='release', namespace='namespace', tenant_id='tenant',
        user_id='user', conversation_id=7, expected_generation=19, cancel_ttl=30)
    arguments = redis.eval.call_args.args
    assert arguments[1] == 2
    assert arguments[2].startswith('runtime:ksm:lease:')
    assert arguments[3].endswith(':current')
    assert arguments[-3] == '19' and arguments[-1] == 30


@pytest.mark.parametrize('field', ['deployment_id', 'namespace', 'tenant_id', 'user_id'])
def test_missing_scope_never_writes_a_broad_cancellation(field):
    redis = Mock()
    options = dict(deployment_id='release', namespace='namespace', tenant_id='tenant', user_id='user')
    options[field] = ''
    with pytest.raises(ValueError):
        signal_distributed_cancel(redis, **options, conversation_id=7, cancel_ttl=30)
    redis.eval.assert_not_called()
