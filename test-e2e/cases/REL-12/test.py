"""D5 security/reliability checks added for HITL and persistent logging."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from shared.config import load_yaml, test_root as get_test_root
from shared.http import assert_status, client






@pytest.mark.stage("D5")
@pytest.mark.case_id("REL-12")
def test_persistent_log_directories_are_bounded_and_secret_free() -> None:
    environment = load_yaml("environment.yaml")
    configured = (
        os.environ.get("NEXENT_LOG_DIR")
        or environment.get("log_dir")
        or (environment.get("logging") or {}).get("directory")
    )
    candidates = [Path(str(configured))] if configured else []
    candidates.extend([get_test_root() / "runs", Path("/mnt/nexent-data/logs")])
    root = next((path for path in candidates if path.exists()), None)
    assert root is not None, f"no configured persistent log root exists: {candidates}"
    files = [path for path in root.rglob("*.log*") if path.is_file()]
    assert files, f"persistent log root contains no log files: {root}"
    assert all(path.stat().st_size < 2 * 1024 * 1024 * 1024 for path in files)
    secret_values = [
        value for key, value in os.environ.items()
        if value and len(value) >= 12 and any(token in key.upper() for token in ("API_KEY", "PASSWORD", "TOKEN"))
    ]
    for path in files[-50:]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not any(secret in text for secret in secret_values), f"secret leaked in {path}"
