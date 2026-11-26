# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real process startup and restart with business boundaries forbidden."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

import pytest
import yaml


@pytest.mark.case_id('OPS-BOOTSTRAP-D5-001')
@pytest.mark.stage('D5')
@pytest.mark.rel
@pytest.mark.parametrize('deployment', ['compose', 'helm'])
def test_ops_deployed_start_and_restart(tmp_path, deployment):
    """Execute deployment arguments through the real wrapper, then restart."""
    repo = Path(__file__).resolve().parents[3]
    if deployment == 'compose':
        source = repo / 'deploy/docker/compose/docker-compose-ops.yml'
        command = yaml.safe_load(source.read_text(encoding='utf-8'))['services']['nexent-ops']['entrypoint']
    else:
        helm = shutil.which('helm')
        assert helm, 'Helm is required to verify the deployed Ops command'
        result = subprocess.run(
            [helm, 'template', 'ops-startup', str(repo / 'deploy/k8s/helm/nexent/charts/nexent-ops')],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        pod = next(doc['spec']['template']['spec'] for doc in yaml.safe_load_all(result.stdout)
                   if isinstance(doc, dict) and doc.get('kind') == 'Deployment')
        command = pod['containers'][0]['command']
    assert command[:2] == ['/opt/nexent/scripts/start-ops.sh', 'python']
    bash = shutil.which('bash')
    assert bash, 'Bash is required for the actual backend startup wrapper'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME'}}
    environment.update(
        PYTHONPATH=os.pathsep.join((str(repo), str(repo / 'backend'), str(repo / 'sdk'))),
        PYTHON_DOTENV_DISABLED='1', GATEWAY_AUTH_ENABLED='false', OPS_PORT=str(port),
        NEXENT_SQL_STARTUP_MODE='off', OPS_MONITORING_ENABLED='false', LOG_DIR=str(tmp_path / 'logs'),
    )
    actual = [bash, str(repo / 'deploy/common/start-ops.sh'), sys.executable, *command[2:]]
    opener = build_opener(ProxyHandler({}))
    for attempt in range(2):
        output_path = tmp_path / f'{deployment}-{attempt}.log'
        with output_path.open('w', encoding='utf-8') as output:
            process = subprocess.Popen(actual, cwd=repo, env=environment, stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while True:
                    assert process.poll() is None, output_path.read_text(encoding='utf-8')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/health/ready', timeout=1) as response:
                            assert response.status == 200 and json.load(response) == {'status': 'ready'}
                        break
                    except (URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            pytest.fail(output_path.read_text(encoding='utf-8'))
                        time.sleep(0.1)
                with opener.open(f'http://127.0.0.1:{port}/health/live', timeout=2) as response:
                    assert response.status == 200 and json.load(response) == {'status': 'alive'}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.poll() is not None
        contents = (tmp_path / 'logs/ops/nexent_ops.log').read_text(encoding='utf-8')
        assert contents.count('Started server process') >= attempt + 1
        assert 'GET /health/live' in contents


@pytest.mark.case_id('OPS-BOOTSTRAP-D5-001')
@pytest.mark.stage('D5')
@pytest.mark.rel
def test_ops_isolated_start_and_restart(tmp_path):
    backend = Path(__file__).resolve().parents[3] / 'backend'
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]

    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in {
            'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'COMSPEC',
            'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'HOME',
        }
    }
    environment.update(
        PYTHONPATH=os.pathsep.join((str(backend.parent), str(backend), str(backend.parent / 'sdk'))),
        PYTHON_DOTENV_DISABLED='1', OPS_MONITORING_ENABLED='false', GATEWAY_AUTH_ENABLED='false', OPS_PORT=str(port), LOG_LEVEL='info', LOG_DIR=str(tmp_path / 'persistent-logs'),
    )
    # Audit the real launcher rather than substituting its application or clients.
    bootstrap = '''
import importlib.abc
import platform
import runpy
import socket
import sys

class BusinessImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        allowed_base_imports = {
            'management', 'management.db', 'management.utils',
            'management.utils.exception_handlers', 'management.utils.request_context',
            'management.utils.account_passwords',
            'management.configuration',
            'management.api', 'management.api.permission',
            'management.api.permission.ops_access', 'management.services.permission.ops_access',
        }
        allowed_shared_import = (
            fullname in allowed_base_imports
            or fullname.startswith('management.db.')
            or fullname.startswith('management.services.permission.identity')
            or fullname in {'management.services', 'management.services.permission'}
            or fullname.startswith('infrastructure.system_configuration.')
            or fullname == 'nexent' or fullname.startswith('nexent.')
        )
        if not allowed_shared_import and fullname.split('.')[0] in {
            'management', 'runtime', 'nexent', 'elasticsearch', 'minio', 'supabase',
        }:
            raise RuntimeError('Forbidden business import: ' + fullname)
        if fullname.startswith('infrastructure.') and not fullname.startswith((
            'infrastructure.rdb', 'infrastructure.system_configuration', 'infrastructure.trace',
            'infrastructure.skill_execution',
        )):
            raise RuntimeError('Forbidden business import: ' + fullname)

def audit(event, args):
    if event == 'socket.connect':
        caller = sys._getframe(1)
        if not (
            caller.f_globals is vars(socket)
            and caller.f_code in {
                getattr(getattr(socket, name, None), '__code__', None)
                for name in ('socketpair', '_fallback_socketpair')
            }
        ):
            raise RuntimeError('Forbidden outbound connection')
    if event in {'subprocess.Popen', 'os.system'}:
        raise RuntimeError('Forbidden child command')

# Cache OS metadata before the audit guard; Windows platform probing can spawn cmd.
if sys.platform == 'win32':
    platform.uname()
sys.meta_path.insert(0, BusinessImportGuard())
sys.addaudithook(audit)
runpy.run_module('backend.http.ops_service', run_name='__main__')
'''
    opener = build_opener(ProxyHandler({}))
    for attempt in range(2):
        log_path = tmp_path / f'ops-{attempt}.log'
        with log_path.open('w+', encoding='utf-8') as output:
            process = subprocess.Popen(
                [sys.executable, '-c', bootstrap], cwd=backend, env=environment,
                stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 20
                while True:
                    assert process.poll() is None, log_path.read_text(encoding='utf-8')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/health/ready', timeout=1) as response:
                            assert response.status == 200
                            assert json.load(response) == {'status': 'ready'}
                            break
                    except (URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            pytest.fail(log_path.read_text(encoding='utf-8'))
                        time.sleep(0.1)
                with opener.open(f'http://127.0.0.1:{port}/health/live', timeout=2) as response:
                    assert response.status == 200
                    assert json.load(response) == {'status': 'alive'}
                with opener.open(f'http://127.0.0.1:{port}/openapi.json', timeout=2) as response:
                    assert response.status == 200
                    schema = json.load(response)
                    assert schema['info']['title'] == 'Nexent Operations API'
                    assert set(schema['paths']) == {
                        '/system_configurations', '/system_configurations/recommendations',
                        '/ops/authorization', '/ops/resources', '/ops/scope',
                        '/trajectory/imports', '/trajectory/imports/{import_id}',
                    }
                try:
                    opener.open(f'http://127.0.0.1:{port}/system_configurations', timeout=2)
                    raise AssertionError('Anonymous configuration query must be rejected')
                except HTTPError as error:
                    assert error.code == 401
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.poll() is not None
        assert 'Forbidden ' not in log_path.read_text(encoding='utf-8')
        persisted = tmp_path / 'persistent-logs/ops/nexent_ops.log'
        assert persisted.is_file()
        contents = persisted.read_text(encoding='utf-8')
        assert contents.count('Started server process') >= attempt + 1
        assert 'GET /health/live' in contents
