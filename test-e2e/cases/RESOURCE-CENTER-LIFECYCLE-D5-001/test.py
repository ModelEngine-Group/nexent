# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Concurrent decisions, replacement races and post-commit delivery faults."""

import pytest

from shared.resource_center import run_backend_scenario


@pytest.mark.case_id("RESOURCE-CENTER-LIFECYCLE-D5-001")
@pytest.mark.stage("D5")
def test_revision_races_rollback_and_notification_failure_windows():
    run_backend_scenario("reliability")
