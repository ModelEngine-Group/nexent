# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shipped upgrade runner and independent review submission migration."""

import pytest

from resource_center.migration_scenario import run_migration_scenario


@pytest.mark.case_id("RESOURCE-CENTER-LIFECYCLE-D5-002")
@pytest.mark.stage("D5")
def test_additive_upgrade_and_legacy_protocol_compatibility():
    run_migration_scenario()
