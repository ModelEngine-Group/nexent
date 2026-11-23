"""Standalone Linux container bootstrap, sent as source to existing sandbox images."""

import ipaddress
import os
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@contextmanager
def private_directory(path):
    """Walk without following links; pin every lookup to the verified parent."""
    path = PurePosixPath(path)
    if not path.is_absolute() or '..' in path.parts or len(path.parts) < 3:
        raise ValueError('TLS directory must be an absolute private path')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
                raise ValueError('Unsafe TLS parent directory')
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open(path.name, flags, dir_fd=fd)
        os.close(fd)
        fd = child
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('TLS directory must be owned by the runtime user with mode 0700')
        yield fd
    finally:
        os.close(fd)


def read_identity_file(directory_fd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 16384):
            raise ValueError('Unsafe TLS identity file')
        return stream.read(16385)


def write_identity_file(directory_fd, name, contents):
    """Exclusive creation with private permissions before the first byte is written."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


def generate_identity(hostname):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName(hostname), x509.DNSName('localhost'),
                x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
            ]), critical=False).sign(key, hashes.SHA256()))
    return (
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()),
        cert.public_bytes(serialization.Encoding.PEM),
    )


def validate_identity(key_data, cert_data):
    key = serialization.load_pem_private_key(key_data, password=None)
    cert = x509.load_pem_x509_certificate(cert_data)
    encoding = serialization.Encoding.DER
    public_format = serialization.PublicFormat.SubjectPublicKeyInfo
    if key.public_key().public_bytes(encoding, public_format) != cert.public_key().public_bytes(encoding, public_format):
        raise ValueError('TLS certificate and private key do not match')
    now = datetime.now(timezone.utc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise ValueError('TLS certificate is not currently valid; drain and recreate the container')


def prepare_identity(hostname, directory):
    with private_directory(directory) as fd:
        key_data = read_identity_file(fd, 'server.key')
        cert_data = read_identity_file(fd, 'server.crt')
        if key_data is None and cert_data is None:
            key_data, cert_data = generate_identity(hostname)
            validate_identity(key_data, cert_data)
            write_identity_file(fd, 'server.key', key_data)
            write_identity_file(fd, 'server.crt.pending', cert_data)
            os.replace('server.crt.pending', 'server.crt', src_dir_fd=fd, dst_dir_fd=fd)
        elif key_data is None or cert_data is None:
            raise ValueError('Incomplete TLS identity; refusing to replace it')
        else:
            validate_identity(key_data, cert_data)


if __name__ == '__main__':
    prepare_identity(sys.argv[1], sys.argv[2])
    os.execvp(sys.argv[3], sys.argv[3:])
