"""Exercise real websocket-client proxy selection without external network I/O."""

import base64
import hashlib
import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from nexent.core.agents import sandbox as sb
from nexent.core.agents.sandbox_tls import SandboxTLSClient
from nexent.core.agents.sandbox_tls_bootstrap import generate_identity
from websocket import WebSocketException
from websocket import _core, _http
from websocket._url import get_proxy_info


@pytest.fixture
def transport(monkeypatch):
    resolve = MagicMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 8888))])
    monkeypatch.setattr(_http.socket, 'getaddrinfo', resolve)
    sock = MagicMock()
    sock.recv.return_value = b''
    sock.send.side_effect = len
    monkeypatch.setattr(_http, '_open_socket', MagicMock(return_value=sock))
    monkeypatch.setattr(_http, '_tunnel', MagicMock(side_effect=AssertionError('Sandbox used the proxy')))
    monkeypatch.setattr(_http, '_ssl_socket', lambda sock, options, hostname: sock)
    handshake = MagicMock(return_value=SimpleNamespace(status=101, headers={}, subprotocol=None))
    monkeypatch.setattr(_core, 'handshake', handshake)
    return resolve, sock, handshake


def make_lease(host):
    lease = object.__new__(sb._DockerKernelLease)
    lease.host, lease.port = host, 8888
    lease._closed = lease._unhealthy = False
    lease._receive_timeout_seconds = 1
    lease._ssl_context = object()
    lease._logger = MagicMock()
    lease._cancellation_scope = sb.RunCancellationScope()
    lease.ws_url = lease._build_channels_url('original')
    lease._wait_for_kernel_channel_ready = MagicMock()
    return lease


@pytest.mark.parametrize('host', ['127.0.0.1', 'nexent-runtime-sandbox', 'nexent-runtime-sandbox-session-abc123'])
@pytest.mark.parametrize('proxy_key', ['HTTPS_PROXY', 'https_proxy'])
@pytest.mark.parametrize('excluded', [None, 'unrelated.internal'])
def test_environment_proxy_is_bypassed_only_for_sandbox(monkeypatch, transport, host, proxy_key, excluded):
    for name in ('HTTPS_PROXY', 'https_proxy', 'NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(proxy_key, 'http://proxy.example:3128')
    if excluded is not None:
        monkeypatch.setenv('NO_PROXY', excluded)
    lease = make_lease(host)
    resolve, sock, handshake = transport
    for kernel in ('original', 'replacement'):
        lease.ws_url = lease._build_channels_url(kernel)
        with lease._kernel_channel() as ws:
            assert ws.sock_opt.sslopt['context'] is lease._ssl_context
    assert [call.args[0] for call in resolve.call_args_list] == [host, host]
    for call in handshake.call_args_list:
        assert call.kwargs['http_no_proxy'] == [host]
    assert get_proxy_info('external.example', True)[:2] == ('proxy.example', 3128)
    assert not lease._cancellation_scope._closers
    assert sock.close.call_count == 2


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308, 200])
def test_non_upgrade_response_is_closed_without_redirect_or_execution(transport, status):
    lease = make_lease('nexent-runtime-sandbox')
    resolve, sock, handshake = transport
    handshake.return_value.status = status
    handshake.return_value.headers = {'location': 'ws://other.example/channels'}
    with pytest.raises(WebSocketException, match='Redirect limit exhausted|handshake requires status 101'):
        with lease._kernel_channel():
            pytest.fail('An invalid handshake must not expose an execution channel')
    assert resolve.call_count == 1
    lease._wait_for_kernel_channel_ready.assert_not_called()
    assert sock.close.called
    assert not lease._cancellation_scope._closers


def test_real_wss_handshake_bypasses_unreachable_environment_proxy(monkeypatch, tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            challenge = self.headers['Sec-WebSocket-Key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
            # SHA-1 is mandated by the WebSocket handshake, not used for TLS security.
            accept = base64.b64encode(hashlib.sha1(challenge.encode(), usedforsecurity=False).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()

        def log_message(self, *args):
            pass

    key, cert = generate_identity('sandbox-test')
    key_file, cert_file = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    key_file.write_bytes(key)
    cert_file.write_bytes(cert)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert_file, key_file)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    client = SandboxTLSClient(cert)
    thread.start()
    try:
        for name in ('HTTPS_PROXY', 'https_proxy'):
            monkeypatch.setenv(name, 'http://127.0.0.1:1')
        for name in ('NO_PROXY', 'no_proxy'):
            monkeypatch.delenv(name, raising=False)
        lease = make_lease('127.0.0.1')
        lease.port = server.server_port
        lease.ws_url = lease._build_channels_url('test')
        lease._ssl_context = client.ssl_context
        with lease._kernel_channel() as ws:
            assert ws.getstatus() == 101
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
