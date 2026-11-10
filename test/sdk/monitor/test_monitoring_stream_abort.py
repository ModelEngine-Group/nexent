# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cancelling a monitored stream interrupts I/O without changing normal close."""

import socket
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from nexent.monitor.monitoring import _MonitoredStreamIterator


@pytest.mark.parametrize('shutdown_error', [False, True])
def test_stream_abort_shuts_down_actual_transport_and_closes_once(shutdown_error):
    connection = Mock()
    if shutdown_error:
        connection.shutdown.side_effect = OSError('Already closed')
    network = SimpleNamespace(get_extra_info=lambda name: connection if name == 'socket' else None)
    response = httpx.Response(200, extensions={'network_stream': network})
    stream = Mock(response=response)
    wrapper = _MonitoredStreamIterator(stream, time.time(), 'model', 'llm')
    wrapper.abort()
    wrapper.close()
    connection.shutdown.assert_called_once_with(socket.SHUT_RDWR)
    stream.close.assert_called_once_with()


def test_stream_close_does_not_shutdown_a_reusable_transport():
    connection = Mock()
    response = httpx.Response(200, extensions={
        'network_stream': SimpleNamespace(get_extra_info=lambda name: connection),
    })
    stream = Mock(response=response)
    wrapper = _MonitoredStreamIterator(stream, time.time(), 'model', 'llm')
    wrapper.close()
    wrapper.close()
    connection.shutdown.assert_not_called()
    stream.close.assert_called_once_with()


def test_stream_abort_without_transport_socket_still_closes():
    stream = Mock(response=httpx.Response(200))
    wrapper = _MonitoredStreamIterator(stream, time.time(), 'model', 'llm')
    wrapper.abort()
    stream.close.assert_called_once_with()
