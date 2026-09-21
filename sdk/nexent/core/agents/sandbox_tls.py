"""Per-container Jupyter TLS, with trust obtained through the Docker API."""

import io
import ssl
import tarfile
import tempfile
import time
from pathlib import Path


TLS_LABEL = 'com.nexent.jupyter.tls'
TLS_VERSION = '1'
TLS_DIRECTORY = '/tmp/nexent-jupyter-tls'
TLS_CERTIFICATE = TLS_DIRECTORY + '/server.crt'


class SandboxTLSMigrationRequired(RuntimeError):
    """A running plaintext container must be drained before upgrading."""


class SandboxTLSRecoveryError(RuntimeError):
    """Preserve a running owner when its TLS identity cannot be verified."""


# Executed by the image's configured user, before any kernel can run. The key
# never leaves the container, and neither the command nor Docker labels contain it.
TLS_BOOTSTRAP = '''
import ipaddress
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

directory = Path(sys.argv[2])
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(directory, 0o700)
key_path = directory / 'server.key'
cert_path = directory / 'server.crt'
if not key_path.exists() or not cert_path.exists():
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, sys.argv[1])])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName(sys.argv[1]), x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
        ]), critical=False).sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    pending_cert = directory / 'server.crt.pending'
    pending_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pending_cert.replace(cert_path)
os.execvp(sys.argv[3], sys.argv[3:])
'''


def require_tls_container(container) -> None:
    """Never delete a running legacy owner as a side effect of an upgrade."""
    if container.status == 'running' and (container.labels or {}).get(TLS_LABEL) != TLS_VERSION:
        raise SandboxTLSMigrationRequired(
            'Running sandbox uses legacy HTTP. Drain its active runs and explicitly stop '
            'the container before restarting with HTTPS; the container was preserved.'
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

        self.ssl_context = ssl.create_default_context(cadata=certificate.decode('ascii'))
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
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
