"""Neutral context-runtime contracts.

Concrete legacy/managed runtimes are intentionally not imported here.  Importing
this package is a common side effect of importing ``contracts``; loading both
runtime implementations at package import time would create an import-level
intersection between the ContextManager-on and ContextManager-off paths.
"""

from .contracts import ContextEvidence, ContextRuntime, FinalContext, UnconfiguredContextRuntime

__all__ = [
    "ContextEvidence",
    "ContextRuntime",
    "FinalContext",
    "UnconfiguredContextRuntime",
]
