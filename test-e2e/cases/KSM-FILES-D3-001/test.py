# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import os
from hashlib import sha256
from pathlib import Path

import pytest

from shared.config import repo_root, test_root
from shared.ksm_kubernetes import run_owned_runtime_probe


@pytest.mark.case_id('KSM-FILES-D3-001')
@pytest.mark.stage('D3')
def test_KSM_FILES_D3_001():
    evidence = Path(os.environ.get('RESULT_DIR') or test_root() / 'results/KSM-FILES-D3-001')
    result = run_owned_runtime_probe(repo_root(), evidence, scenario='files')
    assert result['owned_namespace_removed']
    owners = list(result['core_agents'].values())
    assert len({owner['pod_uid'] for owner in owners}) == 2
    assert {owner['output_sha256'] for owner in owners} == {sha256(b'2\n4\n6\n').hexdigest()}
