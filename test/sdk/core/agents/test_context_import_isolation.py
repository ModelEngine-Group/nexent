"""Import-level isolation tests for ContextManager-on/off paths."""
from __future__ import annotations

import subprocess
import sys


def _run_isolation_check(module_name: str) -> None:
    code = f"""
import sys
import {module_name}
forbidden = [
    'nexent.core.agents.agent_context',
    'nexent.core.context_runtime.managed.runtime',
    'nexent.core.context_runtime.legacy.runtime',
]
loaded = [name for name in forbidden if name in sys.modules]
assert not loaded, loaded
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_agent_model_import_does_not_load_context_manager_or_runtimes():
    _run_isolation_check("nexent.core.agents.agent_model")


def test_nexent_agent_import_does_not_load_context_manager_or_runtimes():
    _run_isolation_check("nexent.core.agents.nexent_agent")
