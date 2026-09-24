"""Per-container Jupyter TLS, with trust obtained through the Docker API."""

import io
import ssl
import tarfile
import tempfile
import time
from pathlib import Path


TLS_LABEL = 'com.nexent.jupyter.tls'
TLS_VERSION = '2'
TLS_DIRECTORY = '/home/sandbox/.nexent-jupyter-tls'
TLS_CERTIFICATE = TLS_DIRECTORY + '/server.crt'


class SandboxTLSMigrationRequired(RuntimeError):
    """A running plaintext container must be drained before upgrading."""


class SandboxTLSRecoveryError(RuntimeError):
    """Preserve a running owner when its TLS identity cannot be verified."""


# Executed by the image's configured user, before any kernel can run. The key
# never leaves the container, and neither the command nor Docker labels contain it.
TLS_BOOTSTRAP = Path(__file__).with_name('sandbox_tls_bootstrap.py').read_text(encoding='utf-8')


def require_tls_container(container) -> None:
    """Never delete a running owner with an older transport or identity layout."""
    if container.status == 'running' and (container.labels or {}).get(TLS_LABEL) != TLS_VERSION:
        raise SandboxTLSMigrationRequired(
            'Running sandbox uses a legacy transport or TLS identity layout. Drain its active runs '
            'and explicitly stop the container before upgrading; the container was preserved.'
        )


class SandboxTLSClient:
    """One owner's verified HTTPS session and WSS trust; leases borrow it."""

    def __init__(self, certificate: bytes):
        import requests

        class HTTPSOnlySession(requests.Session):
            def request(self, method, url, **kwargs):
                if not url.startswith('https://'):
                    raise ValueError('Sandbox control requests require HTTPS')
                kwargs['allow_redirects'] = False
                return super().request(method, url, **kwargs)

        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.ssl_context.load_verify_locations(cadata=certificate.decode('ascii'))
        self._directory = tempfile.TemporaryDirectory(prefix='nexent-tls-trust-')
        self.ca_file = Path(self._directory.name) / 'server.crt'
        try:
            self.ca_file.write_bytes(certificate)
            self.http = HTTPSOnlySession()
            self.http.verify = str(self.ca_file)
            # Internal Docker control traffic must not follow external proxy settings.
            self.http.trust_env = False
        except Exception:
            self._directory.cleanup()
            raise

    def close(self) -> None:
        self.http.close()
        self._directory.cleanup()


def load_container_tls(container, *, timeout: float = 10, check_cancelled=lambda: None) -> SandboxTLSClient:
    """Read only the public certificate over the already trusted Docker channel."""
    from docker.errors import NotFound

    deadline = time.monotonic() + timeout
    while True:
        check_cancelled()
        try:
            stream, _ = container.get_archive(TLS_CERTIFICATE)
            data = bytearray()
            for chunk in stream:
                data.extend(chunk)
                if len(data) > 65536:
                    raise ValueError('Sandbox TLS certificate archive is too large')
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                member = archive.getmember('server.crt')
                if not member.isfile() or member.size > 16384:
                    raise ValueError('Invalid sandbox TLS certificate member')
                certificate = archive.extractfile(member).read()
            return SandboxTLSClient(certificate)
        except NotFound:
            if time.monotonic() >= deadline:
                raise RuntimeError('Sandbox TLS certificate was not generated before the startup deadline') from None
            time.sleep(0.1)
