"""MultimodalGateway: the unified entry point replacing hardcoded dispatch.

Backend services (``image_service``/``voice_service``/``vectordatabase_service``)
resolve an adapter through :meth:`get_adapter` instead of ``if model_factory``
branches. The gateway caches adapter instances per ``(tenant, modality, slot,
model_name, factory)`` so a given model is constructed once.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from .multimodal_adapter import MultimodalAdapter
from .model_context import ModelContext
from .registry import AdapterRegistry, get_registry


class MultimodalGateway:
    """Resolve and cache :class:`MultimodalAdapter` instances by context."""

    def __init__(self, registry: AdapterRegistry = None) -> None:
        """Initializes the gateway with a registry and empty cache.

        Args:
            registry: The adapter registry to resolve from. Defaults to the
                process-wide singleton.
        """
        self._registry = registry or get_registry()
        self._adapter_cache: Dict[Tuple, MultimodalAdapter] = {}

    def get_adapter(self, context: ModelContext) -> MultimodalAdapter:
        """Returns the adapter for ``context``, building and caching it once.

        Args:
            context: The construction context identifying the desired model.

        Returns:
            The cached or newly built adapter instance.
        """
        cls = self._registry.resolve(context.factory, context.modality)
        key = context.cache_key()
        if key not in self._adapter_cache:
            self._adapter_cache[key] = cls(context)
        return self._adapter_cache[key]

    async def invoke(self, context: ModelContext, request: Any) -> Any:
        """Resolves the adapter for ``context`` and invokes it.

        Args:
            context: The construction context identifying the desired model.
            request: The modality-specific request payload.

        Returns:
            The modality-specific response.
        """
        return await self.get_adapter(context).invoke(request)

    def stream(self, context: ModelContext, request: Any):
        """Returns the adapter's async iterator (not awaited — it's a generator).

        Args:
            context: The construction context identifying the desired model.
            request: The modality-specific request payload.

        Returns:
            The adapter's async stream object.
        """
        return self.get_adapter(context).stream(request)

    async def health_check(self, context: ModelContext) -> bool:
        """Resolves the adapter for ``context`` and checks its health.

        Args:
            context: The construction context identifying the desired model.

        Returns:
            True if the model is reachable, False otherwise.
        """
        return await self.get_adapter(context).health_check()

    def invalidate(self, context: ModelContext = None) -> None:
        """Drops cached adapter instances.

        Args:
            context: If provided, drops only that context's cached adapter.
                If None, drops the entire cache.
        """
        if context is None:
            self._adapter_cache.clear()
        else:
            self._adapter_cache.pop(context.cache_key(), None)


_gateway: MultimodalGateway = None


def get_gateway() -> MultimodalGateway:
    """Returns the process-wide gateway singleton (lazy).

    Returns:
        The shared :class:`MultimodalGateway` instance.
    """
    global _gateway
    if _gateway is None:
        _gateway = MultimodalGateway()
    return _gateway
