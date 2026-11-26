# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""V5 REL-003 independently collected scenario."""

import pytest
from d5.scenarios.scenario_security_reliability_deployment import verify_workspace_cleanup


@pytest.mark.case_id("REL-003")
@pytest.mark.stage("D5")
def test_rel_003():
    verify_workspace_cleanup()
