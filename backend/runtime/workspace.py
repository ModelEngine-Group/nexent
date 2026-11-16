# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run-local workspace paths with an explicitly injected deployment root."""

import re
from pathlib import Path


def safe_workspace_segment(value, fallback):
    """Preserve the legacy user-segment normalization."""
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._")
    return normalized or fallback


def create_run_workspace(user_id, run_id, *, workspace_root):
    """Resolve the established path; directory materialization remains caller-owned."""
    root = Path(workspace_root).resolve()
    return str(root / safe_workspace_segment(user_id, "anonymous") / run_id)
