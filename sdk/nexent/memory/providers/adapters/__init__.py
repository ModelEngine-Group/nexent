"""External memory provider adapters package.

This package contains adapters for translating between Nexent's internal
models and external provider-specific formats.
"""

from .base import BaseMemoryAdapter

__all__ = [
    "BaseMemoryAdapter",
]
