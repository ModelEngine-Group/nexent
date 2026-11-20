# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Direct API security boundaries and legacy decision compatibility."""

import pytest

from shared.resource_center import run_backend_scenario


@pytest.mark.case_id("RESOURCE-CENTER-ACCESS-D5-001")
@pytest.mark.stage("D5")
def test_per_type_scopes_and_direct_decision_authorization():
    run_backend_scenario("access")
    run_backend_scenario("lifecycle")
