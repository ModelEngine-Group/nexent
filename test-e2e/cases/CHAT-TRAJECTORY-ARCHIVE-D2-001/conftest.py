# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Use product modules and shared fixtures through explicit repository paths."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for directory in (ROOT / "backend", ROOT / "sdk", ROOT / "test-e2e/infra/automation/shared"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
