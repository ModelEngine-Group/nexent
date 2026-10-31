"""Real POSIX filesystem boundaries of the container's TLS bootstrap."""

import importlib.util
import os
import runpy
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Container POSIX permissions require Linux')


@pytest.fixture
def bootstrap(monkeypatch):
    source = Path(__file__).resolve().parents[4] / 'sdk/nexent/core/agents/sandbox_tls.py'
    spec = importlib.util.spec_from_file_location('standalone_tls', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='tls-tests-', dir=Path.home()) as root:
        directory = Path(root) / 'identity'

        def run(path=directory):
            launched = []
            monkeypatch.setattr(os, 'execvp', lambda command, argv: launched.append(command))
            monkeypatch.setattr(sys, 'argv', ['bootstrap', 'sandbox-test', str(path), 'jupyter'])
            try:
                runpy.run_path(str(source.with_name('sandbox_tls_bootstrap.py')), run_name='__main__')
            except (ValueError, OSError) as exc:
                return SimpleNamespace(returncode=1, stdout='', stderr=str(exc))
            return SimpleNamespace(returncode=0, stdout='gateway launched' if launched else '', stderr='')

        yield directory, run


def test_private_identity_and_restart(bootstrap):
    directory, run = bootstrap
    result = run()
    assert result.returncode == 0, result.stderr
    key_path = directory / 'server.key'
    cert_path = directory / 'server.crt'
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    original = key_path.read_bytes(), cert_path.read_bytes()
    key = serialization.load_pem_private_key(original[0], password=None)
    cert = x509.load_pem_x509_certificate(original[1])
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()
    assert run().returncode == 0
    assert (key_path.read_bytes(), cert_path.read_bytes()) == original


@pytest.mark.parametrize('target', ['directory', 'server.key', 'server.crt'])
def test_rejects_symlinks_without_modifying_target(bootstrap, tmp_path, target):
    directory, run = bootstrap
    outside = tmp_path / 'outside'
    if target == 'directory':
        outside.mkdir(mode=0o700)
        directory.symlink_to(outside, target_is_directory=True)
    else:
        directory.mkdir(mode=0o700)
        outside.write_bytes(b'untouched')
        (directory / target).symlink_to(outside)
    result = run()
    assert result.returncode != 0
    assert 'gateway launched' not in result.stdout
    if target == 'directory':
        assert list(outside.iterdir()) == []
    else:
        assert outside.read_bytes() == b'untouched'


def test_rejects_unsafe_directory_without_chmod(bootstrap):
    directory, run = bootstrap
    directory.mkdir(mode=0o700)
    directory.chmod(0o777)
    result = run()
    assert result.returncode != 0
    assert stat.S_IMODE(directory.stat().st_mode) == 0o777
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize('damage', ['mismatched_key', 'public_key_file', 'missing_certificate', 'hardlink'])
def test_rejects_damaged_existing_identity(bootstrap, tmp_path, damage):
    directory, run = bootstrap
    assert run().returncode == 0
    key = directory / 'server.key'
    if damage == 'mismatched_key':
        other = directory.parent / 'other'
        assert run(other).returncode == 0
        key.write_bytes((other / 'server.key').read_bytes())
    elif damage == 'public_key_file':
        key.chmod(0o644)
    elif damage == 'missing_certificate':
        (directory / 'server.crt').unlink()
    else:
        os.link(key, tmp_path / 'key-link')
    original = key.read_bytes()
    result = run()
    assert result.returncode != 0
    assert 'gateway launched' not in result.stdout
    assert key.read_bytes() == original


def test_rejects_untrusted_parent(bootstrap):
    directory, run = bootstrap
    directory.parent.chmod(0o777)
    result = run()
    assert result.returncode != 0
    assert not directory.exists()


def test_private_mode_is_applied_at_creation(bootstrap, monkeypatch):
    _, run = bootstrap
    original_open = os.open
    created_modes = []

    def observe_open(path, flags, mode=0o777, **kwargs):
        fd = original_open(path, flags, mode, **kwargs)
        if path == 'server.key' and flags & os.O_CREAT:
            created_modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return fd

    monkeypatch.setattr(os, 'open', observe_open)
    result = run()
    assert result.returncode == 0, result.stderr
    assert created_modes == [0o600]


def test_rejects_wrong_directory_owner(bootstrap, monkeypatch):
    directory, run = bootstrap
    directory.mkdir(mode=0o700)
    inode = directory.stat().st_ino
    original_fstat = os.fstat

    def wrong_owner(fd):
        info = original_fstat(fd)
        if info.st_ino == inode:
            return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=info.st_mode)
        return info

    with monkeypatch.context() as patch:
        patch.setattr(os, 'fstat', wrong_owner)
        assert run().returncode != 0
    assert list(directory.iterdir()) == []
