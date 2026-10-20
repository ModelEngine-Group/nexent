# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Configuration works in repository tools and backend service entry points."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("directory,module", [(ROOT, "backend.consts.const"), (ROOT / "backend", "consts.const")])
def test_configuration_import_without_inherited_python_paths(directory, module):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["RUNTIME_AGENT_THREAD_MAX_WORKERS"] = "13"
    probe = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **kw: None; "
        f"from {module} import RUNTIME_AGENT_THREAD_MAX_WORKERS; "
        "print(RUNTIME_AGENT_THREAD_MAX_WORKERS)"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=directory, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "13"
