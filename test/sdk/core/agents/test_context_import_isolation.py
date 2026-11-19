# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Import-level isolation tests for ContextManager-on/off paths."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_isolation_check(module_name: str) -> None:
    code = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[4] / "sdk")!r})
import {module_name}
forbidden = [
    'nexent.core.agents.context.manager',
    'nexent.core.agents.cores.smolagents.context',
]
loaded = [name for name in forbidden if name in sys.modules]
assert not loaded, loaded
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_agent_model_import_does_not_load_context_manager_or_runtimes():
    _run_isolation_check("nexent.core.agents.contracts.config")


def test_nexent_agent_import_does_not_load_context_manager_or_runtimes():
    _run_isolation_check("nexent.core.agents.cores.smolagents.agent")


def test_legacy_context_runtime_is_removed():
    result = subprocess.run(
        [sys.executable, "-c", "import nexent.core.agents.cores.smolagents.context_contracts.legacy.runtime"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ModuleNotFoundError" in result.stderr
