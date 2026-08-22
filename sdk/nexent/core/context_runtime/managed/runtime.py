"""Deprecated compatibility path for the agent context runtime."""

import warnings

from ...agents.context.runtime import ManagedContextRuntime


COMPATIBILITY_REMOVAL_VERSION = "v2.4.0"
warnings.warn(
    "nexent.core.context_runtime.managed is deprecated; use nexent.core.agents.context.runtime; "
    f"the compatibility path will be removed in {COMPATIBILITY_REMOVAL_VERSION}",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["COMPATIBILITY_REMOVAL_VERSION", "ManagedContextRuntime"]
