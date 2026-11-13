# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox_kubernetes_lease import KubernetesKernelLease


@pytest.mark.parametrize('pending,status,confirmed', [(True, 204, True), (True, 404, False),
                                                    (True, 500, False), (False, 404, True)])
def test_kernel_cleanup_releases_only_proved_finished_business(pending, status, confirmed):
    lease = object.__new__(KubernetesKernelLease)
    lease._closed, lease._execution_pending = False, pending
    lease._runtime_lifecycle = Mock()
    lease._lifetime_holder = 'kernel:fixture'
    lease._container_executor = SimpleNamespace(assert_generation=Mock())
    lease._requests = Mock()
    lease._requests.delete.return_value.status_code = status
    lease.base_url, lease.kernel_id, lease._logger = 'https://fixture', 'kernel', logging.getLogger(__name__)
    lease.cleanup()
    if confirmed:
        lease._runtime_lifecycle.finish.assert_called_once_with('kernel:fixture')
        lease._runtime_lifecycle.unknown.assert_not_called()
    else:
        lease._runtime_lifecycle.unknown.assert_called_once_with('kernel:fixture')
        lease._runtime_lifecycle.finish.assert_not_called()
    lease.cleanup()
    assert lease._closed
