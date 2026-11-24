# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""RESOURCE-CENTER-REVIEW-D2-001: real router, identity and PostgreSQL contract."""

import pytest

from shared.resource_center import run_backend_scenario


@pytest.mark.case_id("RESOURCE-CENTER-REVIEW-D2-001")
@pytest.mark.stage("D2")
def test_global_authorized_review_list():
    run_backend_scenario("list")
