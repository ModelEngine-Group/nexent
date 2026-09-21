"""Verified TLS transport and non-destructive migration of legacy containers."""

import io
import logging
import runpy
import socket
import ssl
import sys
import tarfile
from concurrent.futures import CancelledError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock

import pytest
from cryptography import x509
from nexent.core.agents import sandbox
from nexent.core.agents import sandbox_tls as tls
from requests.exceptions import SSLError


@pytest.fixture
def certificate(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'sandbox-test', str(tmp_path), 'jupyter'])
    launch = Mock()
    monkeypatch.setattr('os.execvp', launch)
    (tmp_path / 'bootstrap.py').write_text(tls.TLS_BOOTSTRAP, encoding='utf-8')
    runpy.run_path(str(tmp_path / 'bootstrap.py'))
    launch.assert_called_once_with('jupyter', ['jupyter'])
    return (tmp_path / 'server.crt').read_bytes()


def test_generated_certificate_covers_native_and_docker_hosts(certificate):
    cert = x509.load_pem_x509_certificate(certificate)
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert 'sandbox-test' in names.get_values_for_type(x509.DNSName)
    assert '127.0.0.1' in [str(value) for value in names.get_values_for_type(x509.IPAddress)]


def test_verified_transport_keeps_certificate_checks_enabled(certificate):
    client = tls.SandboxTLSClient(certificate)
    try:
        assert client.ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert client.ssl_context.check_hostname
        assert client.http.verify == str(client.ca_file)
        assert client.http.trust_env is False
        assert client.ca_file.read_bytes() == certificate
    finally:
        client.close()
    assert not client.ca_file.exists()


def test_recovered_executor_uses_https(certificate):
    client = tls.SandboxTLSClient(certificate)
    owner = sandbox._RecoveredDockerExecutor(Mock(), logging.getLogger('tls-test'), '127.0.0.1',
                                             port=49000, tls_client=client)
    try:
        assert owner.base_url == 'https://127.0.0.1:49000'
    finally:
        owner.cleanup()


@pytest.mark.parametrize('status', [200, 302, 500])
def test_kernel_creation_rejects_non_created_status(status):
    lease = object.__new__(sandbox._DockerKernelLease)
    lease.base_url = 'https://sandbox-test:8888'
    lease._receive_timeout_seconds = 3
    lease._requests = Mock()
    lease._requests.post.return_value.status_code = status
    with pytest.raises(RuntimeError, match=f'status={status}'):
        lease._create_kernel()
    lease._requests.post.assert_called_once_with('https://sandbox-test:8888/api/kernels', timeout=3)


def test_trust_file_creation_failure_cleans_temporary_directory(certificate, monkeypatch, tmp_path):
    directory = Mock(name=str(tmp_path))
    directory.name = str(tmp_path)
    monkeypatch.setattr(tls.tempfile, 'TemporaryDirectory', lambda **kwargs: directory)
    monkeypatch.setattr(tls.Path, 'write_bytes', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError, match='disk full'):
        tls.SandboxTLSClient(certificate)
    directory.cleanup.assert_called_once()


def test_tls_gateway_command_includes_certificate_and_key():
    command = sandbox._kernel_gateway_command('session-test')
    assert '--KernelGatewayApp.certfile=' + tls.TLS_CERTIFICATE in command
    assert '--KernelGatewayApp.keyfile=' + tls.TLS_DIRECTORY + '/server.key' in command
    assert command[:2] == ['python', '-c']
    assert 'session-test' in command


def test_running_legacy_container_requires_explicit_migration():
    container = Mock(status='running', labels={'com.nexent.sandbox': 'runtime'})
    with pytest.raises(tls.SandboxTLSMigrationRequired, match='Drain'):
        tls.require_tls_container(container)
    container.remove.assert_not_called()


def test_certificate_loaded_via_docker_api(certificate):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        member = tarfile.TarInfo('server.crt')
        member.size = len(certificate)
        archive.addfile(member, io.BytesIO(certificate))
    container = Mock()
    container.get_archive.return_value = ([buffer.getvalue()], {})
    client = tls.load_container_tls(container)
    try:
        assert client.ca_file.read_bytes() == certificate
        container.get_archive.assert_called_once_with(tls.TLS_CERTIFICATE)
    finally:
        client.close()


@pytest.fixture
def https_server(certificate, tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if self.path == '/redirect' else 200)
            self.send_header('Location', 'http://127.0.0.1:1/plaintext')
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / 'server.crt', tmp_path / 'server.key')
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_real_https_verification_and_no_plaintext_redirect(certificate, https_server):
    host, port = https_server
    client = tls.SandboxTLSClient(certificate)
    try:
        assert client.http.get(f'https://{host}:{port}', timeout=3).status_code == 200
        response = client.http.get(f'https://{host}:{port}/redirect', timeout=3)
        assert response.status_code == 302
        assert not response.history
        with pytest.raises(ValueError, match='require HTTPS'):
            client.http.get(f'http://{host}:{port}', timeout=3)
    finally:
        client.close()


def test_real_handshake_rejects_wrong_host_and_untrusted_ca(certificate, https_server):
    client = tls.SandboxTLSClient(certificate)
    try:
        for context, hostname in [
            (client.ssl_context, 'wrong-sandbox'),
            (ssl.create_default_context(), 'localhost'),
        ]:
            with socket.create_connection(https_server, timeout=3) as raw, pytest.raises(ssl.SSLCertVerificationError):
                context.wrap_socket(raw, server_hostname=hostname)
        # The same context used by WSS also validates the Docker DNS SAN.
        with (
            socket.create_connection(https_server, timeout=3) as raw,
            client.ssl_context.wrap_socket(raw, server_hostname='sandbox-test') as secured,
        ):
            assert secured.version() is not None
    finally:
        client.close()


def test_bootstrap_preserves_identity_on_restart(certificate, tmp_path):
    key = (tmp_path / 'server.key').read_bytes()
    runpy.run_path(str(tmp_path / 'bootstrap.py'))
    assert (tmp_path / 'server.crt').read_bytes() == certificate
    assert (tmp_path / 'server.key').read_bytes() == key


def test_certificate_wait_handles_retry_timeout_and_cancellation(certificate, monkeypatch):
    from docker.errors import NotFound

    container = Mock()
    container.get_archive.side_effect = NotFound('not ready')
    with pytest.raises(RuntimeError, match='startup deadline'):
        tls.load_container_tls(container, timeout=0)
    monkeypatch.setattr(tls.time, 'sleep', Mock(side_effect=CancelledError))
    with pytest.raises(CancelledError):
        tls.load_container_tls(container)
    container.reset_mock()
    with pytest.raises(CancelledError):
        tls.load_container_tls(container, check_cancelled=Mock(side_effect=CancelledError))
    container.get_archive.assert_not_called()


@pytest.mark.parametrize('kind', ['archive_size', 'member_size', 'symlink', 'invalid_cert'])
def test_rejects_invalid_certificate_archives(kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        member = tarfile.TarInfo('server.crt')
        data = b'x' * (16385 if kind == 'member_size' else 4)
        member.size = len(data)
        if kind == 'symlink':
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/shadow'
        archive.addfile(member, io.BytesIO(data))
    container = Mock()
    container.get_archive.return_value = ([b'x' * 65537 if kind == 'archive_size' else buffer.getvalue()], {})
    with pytest.raises((ValueError, ssl.SSLError)):
        tls.load_container_tls(container)


@pytest.mark.parametrize('failure', ['legacy', 'certificate', 'handshake'])
def test_recovery_security_failure_preserves_running_owner(monkeypatch, failure):
    container = Mock(status='running', labels={'com.nexent.sandbox': 'runtime'})
    container.name = sandbox.SANDBOX_CONTAINER_NAME
    container.attrs = {'NetworkSettings': {'Ports': {'8888/tcp': [
        {'HostIp': '127.0.0.1', 'HostPort': '49000'},
    ]}}}
    if failure != 'legacy':
        container.labels[tls.TLS_LABEL] = tls.TLS_VERSION
    client = Mock()
    client.containers.list.return_value = [container]
    monkeypatch.setattr('docker.from_env', lambda: client)
    monkeypatch.setattr(sandbox, '_is_containerized_runtime', lambda: False)
    transport = Mock()
    transport.http.get.side_effect = SSLError('expired or wrong identity')
    loader = Mock(return_value=transport)
    if failure == 'certificate':
        loader.side_effect = ssl.SSLError('invalid certificate')
    monkeypatch.setattr(sandbox, 'load_container_tls', loader)
    config = sandbox.SandboxConfig(level=sandbox.SandboxLevel.DOCKER, scope=sandbox.SandboxScope.SYSTEM)
    pool = sandbox.SandboxPoolManager()
    with pytest.raises((tls.SandboxTLSMigrationRequired, tls.SandboxTLSRecoveryError)):
        pool._acquire_shared_docker_kernel(config, logging.getLogger(__name__), False)
    container.remove.assert_not_called()
    client.containers.run.assert_not_called()
    if failure == 'handshake':
        transport.close.assert_called_once()
    if failure == 'legacy':
        with pytest.raises(tls.SandboxTLSMigrationRequired):
            pool._remove_stale_docker_containers(config, logging.getLogger(__name__))
        container.remove.assert_not_called()
