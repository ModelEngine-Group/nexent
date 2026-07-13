"""Provider registry for managing external memory providers.

This module provides a registry for discovering and managing external memory
providers. Providers are registered by name and can be retrieved for use
in the memory retrieval pipeline.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from .base import BaseMemoryProvider, IngestibleMemoryProvider, SearchableMemoryProvider


logger = logging.getLogger("memory_providers_registry")


class ProviderRegistry:
    """Registry for managing memory providers.

    This registry maintains a collection of external memory providers
    and allows lookup by name for use in memory operations.
    """

    def __init__(self):
        """Initialize an empty registry."""
        self._providers: Dict[str, SearchableMemoryProvider | IngestibleMemoryProvider] = {}
        self._provider_classes: Dict[str, Type[BaseMemoryProvider]] = {}

    def register(
        self,
        provider: SearchableMemoryProvider | IngestibleMemoryProvider,
    ) -> None:
        """Register a provider instance.

        Args:
            provider: The provider instance to register.
        """
        name = provider.provider_name
        self._providers[name] = provider
        logger.debug(f"Registered provider: {name}")

    def register_class(
        self,
        name: str,
        provider_class: Type[BaseMemoryProvider],
    ) -> None:
        """Register a provider class for lazy instantiation.

        Args:
            name: The name to register the class under.
            provider_class: The provider class to register.
        """
        self._provider_classes[name] = provider_class
        logger.debug(f"Registered provider class: {name}")

    def get(self, name: str) -> Optional[SearchableMemoryProvider | IngestibleMemoryProvider]:
        """Get a registered provider by name.

        Args:
            name: The name of the provider to retrieve.

        Returns:
            The provider instance, or None if not found.
        """
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        """List all registered provider names.

        Returns:
            List of provider names.
        """
        return list(self._providers.keys())

    def unregister(self, name: str) -> bool:
        """Unregister a provider.

        Args:
            name: The name of the provider to unregister.

        Returns:
            True if the provider was unregistered, False if not found.
        """
        if name in self._providers:
            del self._providers[name]
            logger.debug(f"Unregistered provider: {name}")
            return True
        return False

    def clear(self) -> None:
        """Clear all registered providers."""
        self._providers.clear()
        logger.debug("Cleared all providers")


# Global registry instance
_provider_registry: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    """Get the global provider registry instance.

    Returns:
        The global ProviderRegistry instance.
    """
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = ProviderRegistry()
    return _provider_registry


def reset_provider_registry() -> None:
    """Reset the global provider registry.

    This is primarily useful for testing.
    """
    global _provider_registry
    if _provider_registry is not None:
        _provider_registry.clear()
    _provider_registry = None
