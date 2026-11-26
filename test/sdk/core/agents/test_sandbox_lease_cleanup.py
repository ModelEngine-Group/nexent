# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""A failed lease cleanup cannot terminate a sibling's shared container."""

import socket
from concurrent.futures import CancelledError, TimeoutError
from unittest.mock import Mock, call

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from nexent.core.agents.sandbox import execution as sandbox
from nexent.core.concurrency import RunCancellationScope


@pytest.mark.parametrize("error", [RuntimeError("failed"), TimeoutError()])
@pytest.mark.parametrize("is_lease", [False, True])
def test_cleanup_fallback_respects_container_ownership(mocker, error, is_lease):
    manager = Mock()
    manager.run_sync.side_effect = error
    mocker.patch.object(sandbox, "_get_sandbox_thread_manager", return_value=manager)
    executor = Mock(_nexent_kernel_lease=is_lease)
    sandbox.cleanup_executor(executor, Mock(), timeout=0.1)
    manager.run_sync.assert_called_once()
    if is_lease:
        executor.container.kill.assert_not_called()
    else:
        executor.container.kill.assert_called_once()


def test_cancelled_channel_closes_without_marking_lease_unhealthy(monkeypatch):
    from websocket import WebSocketConnectionClosedException

    scope = RunCancellationScope()
    channel = Mock()
    lease = object.__new__(sandbox._DockerKernelLease)
    lease._cancellation_scope = scope
    lease._closed = False
    lease._unhealthy = False
    lease.ws_url = "ws://logical-gateway/channels"
    lease._ssl_context = None
    lease._receive_timeout_seconds = 1
    lease._wait_for_kernel_channel_ready = lambda _ws: None
    monkeypatch.setattr("websocket.create_connection", lambda *_args, **_kwargs: channel)
    channel.getstatus.return_value = 101

    def interrupted(*_args, **_kwargs):
        scope.cancel()
        raise WebSocketConnectionClosedException("closed by cancellation")

    channel.recv_data.side_effect = interrupted
    with pytest.raises(CancelledError):
        lease.run_code_raise_errors("controlled execution")
    channel.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    channel.shutdown.assert_called_once()
    channel.close.assert_called_once()
    assert lease._unhealthy is False


@pytest.mark.parametrize("retry_status", [204, 404, None])
def test_kernel_cleanup_retries_same_lease_within_deadline(monkeypatch, retry_status):
    times = iter((10, 11 if retry_status is not None else 15))
    monkeypatch.setattr(sandbox.time, "monotonic", lambda: next(times))
    lease = object.__new__(sandbox._DockerKernelLease)
    lease._closed = False
    lease._requests = Mock()
    lease.base_url = "https://logical-gateway"
    lease.kernel_id = "owned-kernel"
    lease._requests.delete.side_effect = [RequestsConnectionError("connection closed"), Mock(status_code=retry_status)]

    url = "https://logical-gateway/api/kernels/owned-kernel"
    if retry_status is None:
        with pytest.raises(RequestsConnectionError):
            lease.cleanup()
        lease._requests.delete.assert_called_once_with(url, timeout=5)
    else:
        lease.cleanup()
        assert lease._requests.delete.call_args_list == [call(url, timeout=5), call(url, timeout=4)]
    assert lease._closed
