# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""KSM-EXECUTION-D3-001: controlled model and real Runtime/Kubernetes execution."""

import os
from pathlib import Path

import pytest
from shared.config import repo_root, test_root
from shared.ksm_kubernetes import run_owned_runtime_probe


@pytest.mark.case_id('KSM-EXECUTION-D3-001')
@pytest.mark.stage('D3')
def test_KSM_EXECUTION_D3_001_real_runtime_execution():
    evidence = Path(os.environ.get('RESULT_DIR') or test_root() / 'results/KSM-EXECUTION-D3-001')
    result = run_owned_runtime_probe(repo_root(), evidence)
    owners = list(result['core_agents'].values())
    assert len(owners) == 2
    assert len({owner['owner_uid'] for owner in owners}) == 2
    assert len({owner['pod_uid'] for owner in owners}) == 2
    assert len({entry['node'] for entry in result['runtimes'].values()}) == 1
    for owner in owners:
        assert owner['twenty_acquisitions'] == 1
        assert owner['lost_create_response'] and owner['foreign_resource_rejected']
        assert len(set(owner['kernels'])) == 3
        assert owner['parent_kernel'] in owner['kernels']
        assert owner['state_persisted'] and owner['child_release_preserved_parent']
        assert owner['cancelled_child_preserved_parent']
        windows = owner['execution_windows']
        assert {window['ksm_child'] for window in windows} == {'LEFT', 'RIGHT'}
        assert max(window['start'] for window in windows) < min(window['end'] for window in windows)
        assert owner['callback_statuses'].count(200) >= 3
        assert owner['callback_statuses'].count(403) == 2 and owner['stale_context_rejected']
        matrix = owner['script_matrix']
        assert matrix['scripts'] == ['skill.py', 'skill.sh', 'workspace.py', 'workspace.js', 'workspace.mjs']
        assert all(matrix[key] for key in ('argv_cwd_env', 'separate_python_process', 'stderr_nonzero',
                                           'timeout_once', 'original_crlf_preserved', 'full_readonly_seed'))
    assert owners[1]['script_matrix']['online_store_writable']
    assert result['owned_namespace_removed']
