"""Adapter registry: maps ``(factory, modality)`` → adapter class.

Paradigm aligned with :mod:`sdk.nexent.memory.providers.registry`. Vendors opt
in via the ``@register_adapter(factory, modality)`` decorator on their adapter
class; the backend never hardcodes vendor dispatch (``if model_factory == ...``).
"""

from __future__ import annotations

import logging
from typing import Dict, Tuple, Type

from .base import MultimodalAdapter

logger = logging.getLogger("adapter_registry")


class AdapterRegistry:
    """Registry of adapter classes keyed by ``(factory, modality)``."""

    def __init__(self) -> None:
        self._table: Dict[Tuple[str, str], Type[MultimodalAdapter]] = {}

    def register(self, factory: str, modality: str):
        """Class decorator: register an adapter under ``(factory, modality)``."""

        def deco(cls: Type[MultimodalAdapter]) -> Type[MultimodalAdapter]:
            key = (factory.lower().strip(), modality)
            self._table[key] = cls
            logger.debug("Registered adapter %s for %s", key, cls.__name__)
            return cls

        return deco

    def resolve(self, factory: str, modality: str) -> Type[MultimodalAdapter]:
        """Return the adapter class for ``(factory, modality)``.

        Raises:
            KeyError: if no adapter is registered for the pair.
        """
        key = (factory.lower().strip(), modality)
        if key not in self._table:
            raise KeyError(
                f"No adapter registered for factory={factory!r} modality={modality!r}; "
                f"registered: {self.list_adapters()}"
            )
        return self._table[key]

    def has(self, factory: str, modality: str) -> bool:
        return (factory.lower().strip(), modality) in self._table

    def list_adapters(self) -> list:
        return list(self._table.keys())


_registry = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    """Return the process-wide adapter registry singleton."""
    return _registry


def register_adapter(factory: str, modality: str):
    """Module-level convenience alias for ``AdapterRegistry.register``."""
    return _registry.register(factory, modality)
