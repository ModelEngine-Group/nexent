from __future__ import annotations

import os
import subprocess
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from d5.assets import bash_path, require_command
from shared.config import repo_root

CASE_ID = 'DEP-AUTO-00C24E57476D8253'


def _write_oci_archive(path: Path) -> None:
    """Write a minimal, standards-compliant OCI image-layout archive."""
    config = json.dumps({
        'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': []},
        'config': {}, 'history': [],
    }, separators=(',', ':')).encode()
    config_digest = hashlib.sha256(config).hexdigest()
    manifest = json.dumps({
        'schemaVersion': 2,
        'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'config': {
            'mediaType': 'application/vnd.oci.image.config.v1+json',
            'digest': f'sha256:{config_digest}', 'size': len(config),
        },
        'layers': [],
    }, separators=(',', ':')).encode()
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    index = json.dumps({
        'schemaVersion': 2,
        'manifests': [{
            'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'digest': f'sha256:{manifest_digest}', 'size': len(manifest),
            'annotations': {'org.opencontainers.image.ref.name': 'nexent-test:latest'},
        }],
    }, separators=(',', ':')).encode()
    entries = {
        'oci-layout': b'{"imageLayoutVersion":"1.0.0"}',
        'index.json': index,
        f'blobs/sha256/{config_digest}': config,
        f'blobs/sha256/{manifest_digest}': manifest,
    }
    with tarfile.open(path, 'w') as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding='utf-8', newline='\n')
    path.chmod(0o755)


def _loader_sandbox(tmp_path: Path) -> dict:
    pkg = tmp_path / 'package'
    bin_dir = tmp_path / 'bin'
    (pkg / 'images').mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    load_script = repo_root() / 'deploy' / 'offline' / 'load-images.sh'
    (pkg / 'load-images.sh').write_text(load_script.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    _write_oci_archive(pkg / 'images' / 'nexent.tar')

    _write_executable(
        bin_dir / 'docker',
        '''#!/bin/bash
echo "docker:$*" >> "$IMAGE_LOADER_LOG"
''',
    )
    _write_executable(
        bin_dir / 'ctr',
        '''#!/bin/bash
echo "ctr:$*" >> "$IMAGE_LOADER_LOG"
if [ "${FAKE_CTR_NO_SOCKET:-false}" = "true" ]; then
  exit 1
fi
if [ "${FAKE_CTR_FAIL_IMPORT:-false}" = "true" ] && [ "$4" = "import" ]; then
  exit 42
fi
exit 0
''',
    )
    _write_executable(
        bin_dir / 'sudo',
        '''#!/bin/bash
echo "sudo:$*" >> "$IMAGE_LOADER_LOG"
if [ "${FAKE_SUDO_OK:-true}" = "true" ]; then exit 0; else exit 1; fi
''',
    )
    _write_executable(
        bin_dir / 'id',
        '''#!/bin/bash
if [ "$1" = "-u" ]; then
  echo "${FAKE_ID_UID:-0}"
else
  echo "uid=${FAKE_ID_UID:-0}(fake) gid=0(fake) groups=0(fake)"
fi
''',
    )

    log = tmp_path / 'loader.log'
    # Keep the command lookup hermetic.  Otherwise deleting the fake ctr still
    # discovers the host's real /usr/bin/ctr and the fallback branch is never
    # exercised.
    _write_executable(bin_dir / 'dirname', '#!/bin/bash\nexec /usr/bin/dirname "$@"\n')
    env = dict(os.environ)
    env['PATH'] = bash_path(bin_dir)
    env['NEXENT_LOADER_PATH'] = bash_path(bin_dir)
    env['IMAGE_LOADER_LOG'] = bash_path(log)
    return {'script': pkg / 'load-images.sh', 'env': env, 'log': log, 'bin': bin_dir}


def _run_load(script: Path, env: dict, target: str) -> subprocess.CompletedProcess:
    # Git Bash prepends host utilities during startup; reset PATH afterwards
    # so every loader branch uses the sandbox's fake id/ctr/docker commands.
    return subprocess.run([require_command('bash'), '-c',
                           'export PATH="$NEXENT_LOADER_PATH"; source "$1" "$2"',
                           'loader-contract', bash_path(script), target], env=env,
                          capture_output=True, text=True, encoding='utf-8')


def _extract_bash_function(text: str, name: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == f'{name}() {{':
            start = i
            break
    if start is None:
        raise RuntimeError(f'bash function not found: {name}')
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == '}':
            return chr(10).join(lines[start:j + 1])
    raise RuntimeError(f'unterminated bash function: {name}')


def _run_build_bundle(tmp_path: Path, with_assets: bool):
    fake_repo = tmp_path / 'repo'
    out = tmp_path / 'out'
    deploy = fake_repo / 'deploy'
    (deploy / 'docker').mkdir(parents=True)
    (deploy / 'k8s').mkdir(parents=True)
    (fake_repo / 'deploy.sh').write_text('''DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE=""
''', encoding='utf-8')
    (fake_repo / 'uninstall.sh').write_text('''#!/bin/sh
''', encoding='utf-8')
    (deploy / 'docker' / 'docker-compose.yml').write_text('''version: '3'
''', encoding='utf-8')
    (deploy / 'k8s' / 'values.yaml').write_text('''replicas: 1
''', encoding='utf-8')
    if with_assets:
        official = deploy / 'docker' / 'assets' / 'official-skills-zip'
        official.mkdir(parents=True)
        for i in range(1, 11):
            (official / f'skill-{i}.zip').write_bytes(b'')
    out.mkdir()

    build_script = repo_root() / 'deploy' / 'offline' / 'build_offline_package.sh'
    func = _extract_bash_function(build_script.read_text(encoding='utf-8'), 'copy_deployment_bundle')

    harness = f'''#!/usr/bin/env bash
set +e
PROJECT_ROOT="{bash_path(fake_repo)}"
DEPLOY_ROOT="$PROJECT_ROOT/deploy"
OUTPUT_DIR="{bash_path(out)}"
VERSION="latest"
TARGET="k8s"
create_offline_deploy_entrypoint() {{ return 0; }}
{func}

copy_deployment_bundle
rc=$?
echo "BUILD_RC=$rc" >&2
'''
    harness_path = tmp_path / 'harness.sh'
    harness_path.write_text(harness, encoding='utf-8', newline='\n')
    result = subprocess.run([require_command('bash'), bash_path(harness_path)],
                            capture_output=True, text=True, encoding='utf-8')
    return result, out


@pytest.mark.stage('D5')
@pytest.mark.case_id(CASE_ID)
def test_offline_k8s_image_load(tmp_path: Path) -> None:
    ctx = _loader_sandbox(tmp_path / 'basic')
    ctx['env']['FAKE_ID_UID'] = '0'
    result = _run_load(ctx['script'], ctx['env'], 'k8s')
    assert result.returncode == 0, result.stderr
    assert 'ctr:-n k8s.io images import' in ctx['log'].read_text(encoding='utf-8')
    assert 'docker:' not in ctx['log'].read_text(encoding='utf-8')

    ctx = _loader_sandbox(tmp_path / 'fail')
    ctx['env']['FAKE_ID_UID'] = '0'
    ctx['env']['FAKE_CTR_FAIL_IMPORT'] = 'true'
    result = _run_load(ctx['script'], ctx['env'], 'k8s')
    assert result.returncode != 0
    assert 'docker:' not in ctx['log'].read_text(encoding='utf-8')

    ctx = _loader_sandbox(tmp_path / 'fallback')
    ctx['env']['FAKE_ID_UID'] = '0'
    (ctx['bin'] / 'ctr').unlink()
    result = _run_load(ctx['script'], ctx['env'], 'k8s')
    assert result.returncode == 0, result.stderr
    assert 'docker:load -i' in ctx['log'].read_text(encoding='utf-8')
    assert 'falling back to Docker' in result.stderr

    ctx = _loader_sandbox(tmp_path / 'sudo')
    ctx['env']['FAKE_ID_UID'] = '1000'
    ctx['env']['FAKE_SUDO_OK'] = 'true'
    result = _run_load(ctx['script'], ctx['env'], 'k8s')
    assert result.returncode == 0, result.stderr
    assert 'sudo:-n ctr -n k8s.io images import' in ctx['log'].read_text(encoding='utf-8')

    ctx = _loader_sandbox(tmp_path / 'nosocket')
    ctx['env']['FAKE_ID_UID'] = '1000'
    ctx['env']['FAKE_SUDO_OK'] = 'false'
    ctx['env']['FAKE_CTR_NO_SOCKET'] = 'true'
    result = _run_load(ctx['script'], ctx['env'], 'k8s')
    assert result.returncode != 0
    assert 'containerd socket is not accessible' in result.stderr

    result, out = _run_build_bundle(tmp_path / 'build', with_assets=True)
    assert 'BUILD_RC=0' in result.stderr, result.stderr
    official = out / 'deploy' / 'docker' / 'assets' / 'official-skills-zip'
    zips = sorted(p.name for p in official.glob('*.zip'))
    assert len(zips) == 10
    docker_dir = out / 'deploy' / 'docker'
    assert sorted(p.name for p in docker_dir.iterdir()) == ['assets']
    assert (out / 'deploy' / 'k8s' / 'values.yaml').exists()

    result, _ = _run_build_bundle(tmp_path / 'missing', with_assets=False)
    assert 'BUILD_RC=1' in result.stderr, result.stderr
    assert 'Required K8s official skill assets not found' in result.stdout
