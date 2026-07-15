"""Memory module providing memory management functionality.

This module exposes the new Memory system framework as outlined in the
memory design document. The new architecture supports:

- Three-layer memory hierarchy: tenant / user / agent
- Layer-based access policies
- Embedding-model-aware metadata for the backend to derive index names
  (the SDK itself never talks to Elasticsearch)
- External provider integration via ``SearchableMemoryProvider`` /
  ``IngestibleMemoryProvider``
"""

from .embedding_registry import (
    EmbeddingModelInfo,
    EmbeddingModelRegistry,
    get_embedding_registry,
    reset_embedding_registry,
)
from .models import (
    ExternalMemoryItem,
    MemoryConfig,
    MemoryLayer,
    MemoryRecord,
    MemorySearchContext,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
    StoreMemoryResult,
    UnitIngestResult,
    UnitIngestStatus,
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
)
from .policy import (
    MemoryAccessPolicy,
    MemoryRetrievalPolicy,
    MemoryStoragePolicy,
)
from .service import MemoryService, get_memory_service, reset_memory_service

# Providers
from .providers import (
    BaseMemoryProvider,
    DegradableProviderError,
    ExternalHttpProvider,
    IngestibleMemoryProvider,
    NonRetryableProviderError,
    ProviderRegistry,
    RetryConfig,
    RetryableProviderError,
    SearchableMemoryProvider,
    execute_with_retry,
    get_provider_registry,
    reset_provider_registry,
)

# Provider adapters
from .providers.adapters import (
    A800Adapter,
    Mem0Adapter,
)

__all__ = [
    # Models
    "MemoryRecord",
    "MemoryLayer",
    "MemoryType",
    "MemoryStatus",
    "MemoryConfig",
    "MemorySearchRequest",
    "MemorySearchResult",
    "MemorySearchContext",
    "ExternalMemoryItem",
    "StoreMemoryResult",
    "UnitIngestResult",
    "UnitIngestStatus",
    "ProviderError",
    "ProviderErrorCode",
    "ProviderErrorSeverity",
    # Service
    "MemoryService",
    "get_memory_service",
    "reset_memory_service",
    # Policy
    "MemoryAccessPolicy",
    "MemoryRetrievalPolicy",
    "MemoryStoragePolicy",
    # Embedding
    "EmbeddingModelInfo",
    "EmbeddingModelRegistry",
    "get_embedding_registry",
    "reset_embedding_registry",
    # Providers
    "BaseMemoryProvider",
    "SearchableMemoryProvider",
    "IngestibleMemoryProvider",
    "ExternalHttpProvider",
    "ProviderRegistry",
    "get_provider_registry",
    "reset_provider_registry",
    "RetryConfig",
    "RetryableProviderError",
    "DegradableProviderError",
    "NonRetryableProviderError",
    "execute_with_retry",
    # Provider adapters
    "A800Adapter",
    "Mem0Adapter",
]
