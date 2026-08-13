"""Deprecated compatibility path for context configuration."""

import warnings

from .context.config import ContextManagerConfig


COMPATIBILITY_REMOVAL_VERSION = "v2.4.0"
warnings.warn(
    "nexent.core.agents.summary_config is deprecated; use nexent.core.agents.context.config; "
    f"the compatibility path will be removed in {COMPATIBILITY_REMOVAL_VERSION}",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["COMPATIBILITY_REMOVAL_VERSION", "ContextManagerConfig"]
