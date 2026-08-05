"""Base protocols for external memory providers.

This module defines the contracts that external memory providers must implement
to integrate with the Nexent memory system. Providers can implement
SearchableMemoryProvider for search operations and/or IngestibleMemoryProvider
for context ingestion operations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ..models import (
    ExternalMemoryItem,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
)


@runtime_checkable
class SearchableMemoryProvider(Protocol):
    """Protocol for memory providers that support semantic search.

    External providers implementing this protocol can be used to augment
    the internal memory retrieval pipeline with external knowledge sources.
    """

    @property
    def provider_name(self) -> str:
        """Return the unique name of this provider."""
        ...

    async def search(
        self,
        request: MemorySearchRequest,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemorySearchResult]:
        """Search for relevant memories from this provider.

        Args:
            request: The search request containing query and scope.
            limit: Maximum number of results to return.
            filters: Optional filters to narrow search scope.

        Returns:
            List of search results from this provider.

        Raises:
            ProviderError: If the search operation fails.
        """
        ...


@runtime_checkable
class IngestibleMemoryProvider(Protocol):
    """Protocol for memory providers that accept context ingestion.

    External providers implementing this protocol can receive context
    units from agent conversations for external storage and retrieval.
    """

    @property
    def provider_name(self) -> str:
        """Return the unique name of this provider."""
        ...

    async def ingest(
        self,
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        """Ingest context units to this provider.

        Args:
            request: The ingest request containing units to store.

        Returns:
            Ingest result with acceptance status for each unit.

        Raises:
            ProviderError: If the ingest operation fails.
        """
        ...


class BaseMemoryProvider:
    """Base class providing common functionality for memory providers.

    This class can be inherited by concrete provider implementations
    to share common logic like configuration validation and error handling.
    """

    def __init__(
        self,
        provider_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """Initialize the base provider.

        Args:
            provider_name: Unique identifier for this provider.
            api_key: Optional API key for authentication.
            base_url: Optional base URL for the provider API.
            timeout: Request timeout in seconds.
        """
        self._provider_name = provider_name
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers including authentication."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def validate_config(self) -> None:
        """Validate provider configuration.

        Raises:
            ValueError: If required configuration is missing.
        """
        if not self.provider_name:
            raise ValueError("provider_name is required")
