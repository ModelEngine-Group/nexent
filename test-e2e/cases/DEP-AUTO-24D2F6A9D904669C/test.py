from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from shared.config import repo_root
from shared.asset_registry import AssetDependencyError

CASE_ID = 'DEP-AUTO-24D2F6A9D904669C'
EXPECTED_LOG_DIR = '/mnt/nexent-data/logs'

LEGACY_FILES = {
    'modelengine-logo.png': b'mock-legacy-logo-1',
    'modelengine-logo2.png': b'mock-legacy-logo-2',
    'locales/zh/custom.json': b'some-legacy-zh-custom',
    'locales/en/custom.json': b'some-legacy-en-custom',
}


def _sandbox_blocked(detail):
    raise AssetDependencyError('deployment', 'sandbox',
                               dependency_case_id='D5-DEPLOY-SANDBOX', detail=detail)


def _deploy_script():
    return _sandbox_repo() / 'deploy' / 'docker' / 'deploy.sh'


def _env_file():
    return _sandbox_repo() / 'deploy' / 'env' / '.env'


def _sandbox_repo():
    configured = os.environ.get('D5_DEPLOY_SANDBOX_REPO', '').strip()
    if not configured:
        _sandbox_blocked('configure a separate D5_DEPLOY_SANDBOX_REPO for the real deploy test')
    sandbox = Path(configured).resolve()
    if sandbox == repo_root().resolve():
        _sandbox_blocked('deploy sandbox repo is the live product repo')
    if (sandbox / 'deploy').resolve() == (repo_root() / 'deploy').resolve():
        _sandbox_blocked('sandbox repo reuses the live deploy directory')
    if not (sandbox / 'deploy' / 'docker' / 'deploy.sh').is_file():
        _sandbox_blocked('deploy sandbox repo is incomplete')
    live_env = (repo_root() / 'deploy' / 'env' / '.env').resolve()
    if (sandbox / 'deploy' / 'env' / '.env').resolve() == live_env:
        _sandbox_blocked('sandbox and live repo share deploy/env/.env')
    return sandbox


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def _docker_ok():
    try:
        proc = subprocess.run(
            ['docker', 'version'],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _daemon_id(env):
    try:
        proc = subprocess.run(
            ['docker', 'info', '--format', '{{.ID}}'],
            capture_output=True, text=True, timeout=60, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    return proc.stdout.strip() if proc.returncode == 0 else ''


def _isolated_docker_host():
    """Never run deploy.sh against the daemon hosting the test environment."""
    sandbox_host = os.environ.get('D5_DEPLOY_SANDBOX_DOCKER_HOST', '').strip()
    if not sandbox_host:
        _sandbox_blocked('configure a separate D5_DEPLOY_SANDBOX_DOCKER_HOST for the real deploy test')
    current_env = dict(os.environ)
    sandbox_env = dict(current_env)
    sandbox_env.pop('DOCKER_CONTEXT', None)
    sandbox_env['DOCKER_HOST'] = sandbox_host
    current_id = _daemon_id(current_env)
    sandbox_id = _daemon_id(sandbox_env)
    if not current_id or not sandbox_id or current_id == sandbox_id:
        _sandbox_blocked('deploy sandbox is unavailable or resolves to the shared Docker daemon')
    return sandbox_host


def _run_deploy(root_dir):
    env = dict(os.environ)
    env['ROOT_DIR'] = str(root_dir)
    return subprocess.run(
        [str(_deploy_script()), '--root-dir', str(root_dir), '--defaults'],
        cwd=str(_sandbox_repo()),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )


def _read_env():
    result = {}
    path = _env_file()
    if not path.is_file():
        return result
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = value.strip()
    return result


def _remove_container(name):
    proc = subprocess.run(
        ['docker', 'ps', '-a', '--filter', 'name=' + name, '--format', '{{.Names}}'],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if name in proc.stdout.splitlines():
        subprocess.run(
            ['docker', 'rm', '-f', name],
            capture_output=True,
            text=True,
            timeout=120,
        )


def _reset_environment(root):
    # The caller supplies a fresh pytest-owned directory. Never recursively
    # remove a shared deployment root to make room for this case.
    if root.exists():
        raise RuntimeError('deployment case root must be new and empty')
    root.mkdir(parents=True, exist_ok=True, mode=0o775)
    _remove_container('nexent-web')


def _precreate_legacy_container(root_dir):
    _remove_container('nexent-web')
    src = root_dir / 'legacy-src'
    shutil.rmtree(src, ignore_errors=True)
    for rel, content in LEGACY_FILES.items():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    proc = subprocess.run(
        [
            'docker', 'run', '-d', '--name', 'nexent-web',
            '-v', str(src) + ':/opt/frontend-dist/public:ro',
            'alpine:3.20', 'sleep', 'infinity',
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        'failed to create legacy nexent-web container: ' + proc.stderr
    )


def _assert_dir(path, mode):
    assert path.is_dir(), 'expected directory ' + str(path) + ' to exist'
    assert _mode(path) == mode, (
        'expected ' + str(path) + ' mode ' + oct(mode) + ' got ' + oct(_mode(path))
    )


def _assert_nonempty_file(path, mode):
    assert path.is_file(), 'expected file ' + str(path) + ' to exist'
    assert path.stat().st_size > 0, 'expected file ' + str(path) + ' to be non-empty'
    assert _mode(path) == mode, (
        'expected ' + str(path) + ' mode ' + oct(mode) + ' got ' + oct(_mode(path))
    )


@pytest.mark.stage('D5')
@pytest.mark.special_id(CASE_ID)
@pytest.mark.case_id("DEP-AUTO-24D2F6A9D904669C")
def test_docker_deploy_persistence_migration_idempotency(tmp_path, monkeypatch):
    if (os.environ.get('D5_ENABLE_MUTATING_DEPLOYMENT', '').lower() != 'true'
            or os.environ.get('D5_ISOLATED_ENVIRONMENT', '').lower() != 'true'):
        pytest.skip('SKIPPED_BY_SAFETY: dedicated mutating deployment is required')
    if not _docker_ok():
        pytest.fail('dockerd unavailable: cannot validate Docker deploy (environment failure)')

    sandbox_host = _isolated_docker_host()
    monkeypatch.delenv('DOCKER_CONTEXT', raising=False)
    monkeypatch.setenv('DOCKER_HOST', sandbox_host)

    assert _deploy_script().is_file(), 'deploy.sh not found: ' + str(_deploy_script())

    root_dir = tmp_path / 'root-dir'
    _reset_environment(root_dir)

    first = _run_deploy(root_dir)
    assert first.returncode == 0, (
        'fresh deploy.sh exited ' + str(first.returncode)
        + ' stdout=' + first.stdout + ' stderr=' + first.stderr
    )

    env = _read_env()
    assert env.get('LOG_DIR') == EXPECTED_LOG_DIR, (
        'LOG_DIR must be /mnt/nexent-data/logs, got ' + repr(env.get('LOG_DIR'))
    )
    _assert_dir(root_dir / 'logs', 0o775)
    _assert_dir(root_dir / 'memory-provider-plugins', 0o775)
    _assert_dir(root_dir / 'project-config', 0o775)

    _precreate_legacy_container(root_dir)
    migrate = _run_deploy(root_dir)
    assert migrate.returncode == 0, (
        'legacy-migration deploy.sh exited ' + str(migrate.returncode)
        + ' stdout=' + migrate.stdout + ' stderr=' + migrate.stderr
    )
    for rel in LEGACY_FILES:
        _assert_nonempty_file(root_dir / 'project-config' / rel, 0o664)
    _assert_dir(root_dir / 'project-config', 0o775)

    rerun = _run_deploy(root_dir)
    assert rerun.returncode == 0, 'idempotent rerun exited ' + str(rerun.returncode) + ' ' + rerun.stderr
    assert _read_env().get('LOG_DIR') == EXPECTED_LOG_DIR, 'LOG_DIR was rewritten on rerun'
    combined = rerun.stdout + rerun.stderr
    assert 'legacy migration skipped' in combined, 'expected legacy migration to be skipped, got: ' + combined
    for rel in LEGACY_FILES:
        assert (root_dir / 'project-config' / rel).is_file(), (
            'existing migrated file ' + rel + ' removed during idempotent rerun'
        )
