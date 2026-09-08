"""MultimodalGateway: the unified entry point replacing hardcoded dispatch."""

from __future__ import annotations

from typing import Any

from .multimodal_adapter import MultimodalAdapter
from .model_context import ModelContext
from .registry import AdapterRegistry, get_registry


class MultimodalGateway:
    """Resolve :class:`MultimodalAdapter` instances from a construction context.

    Adapters are built fresh on every call. An earlier revision cached them by
    ``(tenant_id, modality, slot, model_name, factory)``, a key that omitted
    ``base_url``, ``api_key``, ``ssl_verify``, ``timeout_seconds`` and every
    sampling parameter. Two model records sharing a repo/name but pointing at
    different endpoints therefore resolved to the same instance, and editing a
    model in the management UI had no effect until the process restarted -
    adapters also memoize their wrapped model, so stale config was baked in
    twice. Building an adapter is cheap (the wrapped model creates its HTTP
    client lazily), so correctness wins over reuse here.
    """

    def __init__(self, registry: AdapterRegistry = None) -> None:
        """Initializes the gateway with a registry.

        Args:
            registry: The adapter registry to resolve from. Defaults to the
                process-wide singleton.
        """
        self._registry = registry or get_registry()

    def get_adapter(self, context: ModelContext) -> MultimodalAdapter:
        """Returns a newly built adapter for ``context``.

        Args:
            context: The construction context identifying the desired model.

        Returns:
            A fresh adapter instance bound to ``context``.
        """
        cls = self._registry.resolve(context.factory, context.modality)
        return cls(context)

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
        """Returns the adapter's async iterator (not awaited - it's a generator).

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
