# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Daily complete PostgreSQL upgrade with a million affected rows."""

import os
from pathlib import Path
import sys

import pytest

from shared.config import repo_root, test_root as configured_test_home

sys.path.insert(0, str(Path(__file__).resolve().parent))
from upgrade import exercise


@pytest.mark.case_id("DB-MIGRATION-D5-001")
@pytest.mark.stage("D5")
def test_complete_million_row_upgrade():
    exercise(repo_root(), configured_test_home(), Path(os.environ["RESULT_DIR"]) / "runtime")
