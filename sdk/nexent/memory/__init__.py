"""Memory module providing memory management functionality."""

from .embedding_model import (
    EmbeddingModelInfo,
    get_embedding_client,
    reset_embedding_client_cache,
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
    PipelineConfig,
    PipelineMemoryRecord,
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
    RetrievalSource,
    StoreMemoryResult,
    UnitIngestResult,
    UnitIngestStatus,
)
from .policy import (
    MemoryAccessPolicy,
    MemoryRetrievalPolicy,
    MemoryStoragePolicy,
)
from .service import MemoryService, get_memory_service, reset_memory_service

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

from .providers.adapters import (
    A800Adapter,
    Mem0Adapter,
)

from .retrieval import (
    MMRDeduplicator,
    Normalizer,
    PipelineResult,
    RetrievalPipeline,
    ScoreFusion,
    TemporalDecayer,
    TokenBudgetSelector,
    count_tokens,
    count_tokens_from_records,
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
    # Phase 4 models
    "RetrievalSource",
    "PipelineMemoryRecord",
    "PipelineConfig",
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
    "get_embedding_client",
    "reset_embedding_client_cache",
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
    # Retrieval pipeline (Phase 4)
    "Normalizer",
    "ScoreFusion",
    "TemporalDecayer",
    "MMRDeduplicator",
    "TokenBudgetSelector",
    "RetrievalPipeline",
    "PipelineResult",
    "count_tokens",
    "count_tokens_from_records",
]
