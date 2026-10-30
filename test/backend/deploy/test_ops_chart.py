# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit contracts for shared deployment settings emitted to the ops chart."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('policy', ['development', 'production'])
@pytest.mark.parametrize('component', ['application', 'infrastructure'])
@pytest.mark.parametrize('port,level', [('5016', 'info'), ('15016', 'DEBUG')])
def test_ops_helm_values_follow_component_and_runtime_settings(policy, component, port, level):
    git = shutil.which('git')
    git_bash = Path(git).resolve().parent.parent / 'bin/bash.exe' if git else None
    bash = str(git_bash) if os.name == 'nt' and git_bash and git_bash.is_file() else shutil.which('bash')
    assert bash, 'Bash is required for deployment configuration tests'
    script = '''
set -e
source "$1/deploy/common/common.sh"
DEPLOYMENT_COMPONENTS="$2"
DEPLOYMENT_PORT_POLICY="$3"
DEPLOYMENT_IMAGE_SOURCE=general
DEPLOYMENT_APP_VERSION=latest
deployment_apply_image_source
NEXENT_IMAGE=example.invalid/shared/backend:ops-check
OPS_PORT="$4"
LOG_LEVEL="$5"
deployment_render_helm_chart_values
'''
    result = subprocess.run(
        [bash, '--noprofile', '--norc', '-c', script, 'ops-values', REPO.as_posix(),
         component, policy, port, level],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert result.returncode == 0, result.stderr
    settings = yaml.safe_load(result.stdout)['nexent-ops']
    assert settings['enabled'] is (component == 'application')
    assert settings['images']['backend'] == {
        'repository': 'example.invalid/shared/backend', 'tag': 'ops-check', 'pullPolicy': 'IfNotPresent',
    }
    assert settings['service'] == {'type': 'NodePort', 'port': int(port), 'nodePort': 30016}
    assert settings['config']['logLevel'] == level.lower()
