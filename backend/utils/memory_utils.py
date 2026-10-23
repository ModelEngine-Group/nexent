"""Compatibility helper for agent cleanup paths on the new Memory system."""

from typing import Any, Dict


def build_memory_config(_tenant_id: str) -> Dict[str, Any]:
    """Return an empty legacy config.

    The removed Mem0 functions still accept this argument at a few guarded
    cleanup call sites. New Memory services resolve tenant model configuration
    through backend services instead of this utility.
    """
    return {}
