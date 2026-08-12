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
        """Initializes an empty registry."""
        self._adapter_map: Dict[Tuple[str, str], Type[MultimodalAdapter]] = {}

    def register(self, factory: str, modality: str):
        """Class decorator: register an adapter under ``(factory, modality)``.

        Args:
            factory: The normalized provider name.
            modality: The capability family identifier.

        Returns:
            The class decorator that registers and returns the class.
        """

        def deco(cls: Type[MultimodalAdapter]) -> Type[MultimodalAdapter]:
            key = (factory.lower().strip(), modality)
            self._adapter_map[key] = cls
            logger.debug("Registered adapter %s for %s", key, cls.__name__)
            return cls

        return deco

    def resolve(self, factory: str, modality: str) -> Type[MultimodalAdapter]:
        """Returns the adapter class for ``(factory, modality)``.

        Args:
            factory: The normalized provider name.
            modality: The capability family identifier.

        Returns:
            The registered adapter class.

        Raises:
            KeyError: If no adapter is registered for the pair.
        """
        key = (factory.lower().strip(), modality)
        if key not in self._adapter_map:
            raise KeyError(
                f"No adapter registered for factory={factory!r} modality={modality!r}; "
                f"registered: {self.list_adapters()}"
            )
        return self._adapter_map[key]

    def has(self, factory: str, modality: str) -> bool:
        """Returns whether a ``(factory, modality)`` pair is registered.

        Args:
            factory: The normalized provider name.
            modality: The capability family identifier.

        Returns:
            True if a pair is registered, False otherwise.
        """
        return (factory.lower().strip(), modality) in self._adapter_map

    def list_adapters(self) -> list:
        """Returns all registered ``(factory, modality)`` pairs.

        Returns:
            A list of registered key tuples.
        """
        return list(self._adapter_map.keys())


_registry = AdapterRegistry()


def get_registry() -> AdapterRegistry:
    """Returns the process-wide adapter registry singleton.

    Returns:
        The shared :class:`AdapterRegistry` instance.
    """
    return _registry


def register_adapter(factory: str, modality: str):
    """Module-level convenience alias for ``AdapterRegistry.register``.

    Args:
        factory: The normalized provider name.
        modality: The capability family identifier.

    Returns:
        The class decorator that registers the adapter.
    """
    return _registry.register(factory, modality)
