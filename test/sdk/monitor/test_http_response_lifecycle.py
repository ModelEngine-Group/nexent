# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run real OTel ASGI cases outside the global legacy OTel test stubs."""

import os
import subprocess
import sys
from pathlib import Path


def test_nb_ac001_real_asgi_response_lifecycle(tmp_path):
    root = Path(__file__).resolve().parents[4]
    cases = Path(__file__).with_name('_http_response_lifecycle_cases.py')
    env = {**os.environ, 'PYTHONPATH': str(root/'sdk')}
    result = subprocess.run([sys.executable, '-m', 'pytest', str(cases),
                             '--noconftest', '--basetemp', str(tmp_path/'child'), '-q'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '8 passed' in result.stdout
