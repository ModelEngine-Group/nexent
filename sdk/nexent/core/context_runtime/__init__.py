"""Neutral contracts for the ContextManager-backed runtime.

The concrete runtime is intentionally not imported here so contract imports do
not initialize context assembly implementations as a side effect.
"""

from .contracts import (
    ContextEvidence,
    ContextRuntime,
    FinalContext,
    UnconfiguredContextRuntime,
)


__all__ = [
    "ContextEvidence",
    "ContextRuntime",
    "FinalContext",
    "UnconfiguredContextRuntime",
]
