# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import os
from pathlib import Path

import pytest

from shared.config import repo_root, test_root
from shared.ksm_kubernetes import run_owned_runtime_probe


@pytest.mark.case_id('KSM-SECURITY-D5-001')
@pytest.mark.stage('D5')
def test_KSM_SECURITY_D5_001():
    evidence = Path(os.environ.get('RESULT_DIR') or test_root() / 'results/KSM-SECURITY-D5-001')
    result = run_owned_runtime_probe(repo_root(), evidence, scenario='security')
    assert result['owned_namespace_removed']
    security = result['core_agents']['runtime-a']
    assert security['pod_uid'] and security['python_result'] == 42
    assert {'cpu', 'memory'} <= security['resource_limits'].keys()
