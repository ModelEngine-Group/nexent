# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Daily bounded concurrency through the deployed product."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load import exercise


@pytest.mark.case_id("PERF-02")
@pytest.mark.stage("D5")
@pytest.mark.asyncio
async def test_perf_02(tenant_a_admin):
    await exercise(tenant_a_admin)
