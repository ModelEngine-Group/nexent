"""MultimodalGateway: the unified entry point replacing hardcoded dispatch.

Backend services (``image_service``/``voice_service``/``vectordatabase_service``)
resolve an adapter through :meth:`get_adapter` instead of ``if model_factory``
branches. The gateway caches adapter instances per ``(tenant, modality, slot,
model_name, factory)`` so a given model is constructed once.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from .base import MultimodalAdapter
from .context import ModelContext
from .registry import AdapterRegistry, get_registry


class MultimodalGateway:
    """Resolve and cache :class:`MultimodalAdapter` instances by context."""

    def __init__(self, registry: AdapterRegistry = None) -> None:
        self._registry = registry or get_registry()
        self._instances: Dict[Tuple, MultimodalAdapter] = {}

    def get_adapter(self, context: ModelContext) -> MultimodalAdapter:
        """Return the adapter for ``context`` (cached after first build)."""
        cls = self._registry.resolve(context.factory, context.modality)
        key = context.cache_key()
        if key not in self._instances:
            self._instances[key] = cls(context)
        return self._instances[key]

    async def invoke(self, context: ModelContext, request: Any) -> Any:
        return await self.get_adapter(context).invoke(request)

    def stream(self, context: ModelContext, request: Any):
        """Return the adapter's async iterator (not awaited — it's a generator)."""
        return self.get_adapter(context).stream(request)

    async def health_check(self, context: ModelContext) -> bool:
        return await self.get_adapter(context).health_check()

    def invalidate(self, context: ModelContext = None) -> None:
        """Drop cached instances (all, or a specific context's)."""
        if context is None:
            self._instances.clear()
        else:
            self._instances.pop(context.cache_key(), None)


_gateway: MultimodalGateway = None


def get_gateway() -> MultimodalGateway:
    """Return the process-wide gateway singleton (lazy)."""
    global _gateway
    if _gateway is None:
        _gateway = MultimodalGateway()
    return _gateway
