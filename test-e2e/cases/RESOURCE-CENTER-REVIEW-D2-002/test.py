# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""RESOURCE-CENTER-REVIEW-D2-002: real router, identity and PostgreSQL contract."""

import pytest

from shared.resource_center import run_backend_scenario


@pytest.mark.case_id("RESOURCE-CENTER-REVIEW-D2-002")
@pytest.mark.stage("D2")
def test_typed_details_and_revision_decisions():
    run_backend_scenario("detail")
