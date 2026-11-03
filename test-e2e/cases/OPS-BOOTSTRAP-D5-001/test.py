# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real process startup and restart with business boundaries forbidden."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest


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
        PYTHON_DOTENV_DISABLED='1', OPS_PORT=str(port), LOG_LEVEL='info', LOG_DIR=str(tmp_path / 'persistent-logs'),
    )
    # Audit the real launcher rather than substituting its application or clients.
    bootstrap = '''
import importlib.abc
import runpy
import socket
import sys

class BusinessImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'management', 'runtime', 'nexent', 'redis',
            'elasticsearch', 'minio', 'supabase', 'sqlalchemy', 'psycopg2',
        }:
            raise RuntimeError('Forbidden business import: ' + fullname)
        if fullname.startswith('infrastructure.') and fullname != 'infrastructure.logging':
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

sys.meta_path.insert(0, BusinessImportGuard())
sys.addaudithook(audit)
runpy.run_path('ops_service.py', run_name='__main__')
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
                    assert schema['paths'] == {}
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
