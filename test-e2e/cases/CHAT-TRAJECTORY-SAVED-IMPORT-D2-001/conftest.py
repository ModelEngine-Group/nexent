# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Use product modules and shared fixtures through explicit repository paths."""

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for directory in (
    ROOT / "backend",
    ROOT / "sdk",
    ROOT / "test-e2e/infra/automation/shared",
):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


@pytest.fixture(autouse=True)
def release_owned_files(tmp_path):
    yield
    shutil.rmtree(tmp_path)
    assert not tmp_path.exists()
