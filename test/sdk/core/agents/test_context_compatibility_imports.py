"""One-release compatibility coverage for moved context imports."""

from __future__ import annotations

import subprocess
import sys


def _run(code: str) -> None:
    subprocess.run([sys.executable, "-c", code], check=True)


def test_agent_context_package_warns_and_reexports_canonical_symbols():
    _run(
        """
import warnings
warnings.simplefilter('always', DeprecationWarning)
with warnings.catch_warnings(record=True) as caught:
    from nexent.core.agents.context import ContextManager as canonical
    from nexent.core.agents.agent_context import ContextManager as compatible
    from nexent.core.agents.agent_context.manager import ContextManager as submodule_compatible
assert compatible is canonical
assert submodule_compatible is canonical
assert any('agent_context is deprecated' in str(item.message) for item in caught)
assert any('v2.4.0' in str(item.message) for item in caught)
"""
    )


def test_summary_config_warns_and_reexports_canonical_config():
    _run(
        """
import warnings
warnings.simplefilter('always', DeprecationWarning)
with warnings.catch_warnings(record=True) as caught:
    from nexent.core.agents.context import ContextManagerConfig as canonical
    from nexent.core.agents.summary_config import ContextManagerConfig as compatible
assert compatible is canonical
assert any('summary_config is deprecated' in str(item.message) for item in caught)
assert any('v2.4.0' in str(item.message) for item in caught)
"""
    )


def test_managed_runtime_warns_and_reexports_canonical_runtime():
    _run(
        """
import warnings
warnings.simplefilter('always', DeprecationWarning)
with warnings.catch_warnings(record=True) as caught:
    from nexent.core.agents.context import ManagedContextRuntime as canonical
    from nexent.core.context_runtime.managed import ManagedContextRuntime as compatible
assert compatible is canonical
assert any('context_runtime.managed is deprecated' in str(item.message) for item in caught)
assert any('v2.4.0' in str(item.message) for item in caught)
"""
    )
