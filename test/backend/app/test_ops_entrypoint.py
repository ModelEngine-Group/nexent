# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run the configured Ops Python entrypoint without binding a real server."""
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml


def test_docker_ops_entrypoint_imports_standard_logging_before_server_start(tmp_path):
    root = Path(__file__).resolve().parents[3]
    manifest = yaml.safe_load((root / 'deploy/docker/compose/docker-compose-ops.yml').read_text())
    command = manifest['services']['nexent-ops']['entrypoint'][1:]
    (tmp_path / 'uvicorn.py').write_text(
        'import json\nimport logging.config\n'
        'def run(app, **kwargs):\n'
        '    print(json.dumps({"stdlib_logging": hasattr(logging, "__path__"), "port": kwargs["port"]}))\n')
    for directory in (tmp_path / 'ops', tmp_path / 'ops/api'):
        directory.mkdir(exist_ok=True)
        (directory / '__init__.py').touch()
    (tmp_path / 'ops/api/application.py').write_text('app = object()\n')
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(tmp_path), str(root), str(root / 'backend')]),
           'OPS_PORT': '5016', 'LOG_DIR': str(tmp_path / 'logs'), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, *command[1:]], cwd=root, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {'stdlib_logging': True, 'port': 5016}
