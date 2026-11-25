# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import os
from pathlib import Path

import pytest

from shared.config import repo_root, test_root
from shared.ksm_kubernetes import run_owned_runtime_probe


@pytest.mark.case_id('KSM-MULTIRUNTIME-D5-001')
@pytest.mark.stage('D5')
def test_KSM_MULTIRUNTIME_D5_001():
    evidence = Path(os.environ.get('RESULT_DIR') or test_root() / 'results/KSM-MULTIRUNTIME-D5-001')
    result = run_owned_runtime_probe(repo_root(), evidence, scenario='multiruntime')
    assert result['owned_namespace_removed']
    verdicts = list(result['core_agents'].values())
    assert sum(verdict['accepted'] for verdict in verdicts) == 1
    winner, = (verdict for verdict in verdicts if verdict['accepted'])
    assert winner['renewed'] and winner['current_generation'] != winner['previous_generation']
    assert winner['stale_events_isolated'] and winner['current_stop_recorded']
