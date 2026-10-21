# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""MCP port checks must not expose a temporary server to the network."""

import errno
from unittest.mock import MagicMock

import pytest

from management.services.mcp import provisioning


@pytest.fixture
def sockets(mocker):
    mocker.patch.object(provisioning.socket, "has_ipv6", False)
    mocker.patch.object(provisioning.socket, "getaddrinfo", side_effect=OSError("unavailable host alias"))
    connect = MagicMock()
    connect.connect_ex.return_value = errno.ECONNREFUSED
    bind = MagicMock()
    for value in (connect, bind):
        value.__enter__.return_value = value
    mocker.patch.object(provisioning.socket, "socket", side_effect=[connect, bind])
    return connect, bind


def test_free_port_checks_only_loopback_without_listening(sockets):
    connect, bind = sockets

    assert provisioning.check_runtime_host_port_available(8080)
    connect.connect_ex.assert_called_once_with(("127.0.0.1", 8080))
    bind.bind.assert_called_once_with(("127.0.0.1", 8080))
    bind.listen.assert_not_called()


def test_connected_listener_is_rejected_without_binding(sockets):
    connect, bind = sockets
    connect.connect_ex.return_value = 0

    assert not provisioning.check_runtime_host_port_available(8080)
    bind.bind.assert_not_called()


def test_bound_port_is_rejected_and_socket_closed(sockets):
    _, bind = sockets
    bind.bind.side_effect = OSError(errno.EADDRINUSE, "port busy")

    assert not provisioning.check_runtime_host_port_available(8080)
    bind.__exit__.assert_called_once()
    bind.listen.assert_not_called()
