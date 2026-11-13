# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Nexent public exports, resolved on demand without initializing optional integrations."""

from importlib import import_module


_MODULES = ("core", "datamate", "memory", "storage", "vector_database", "skills")
_EXPORTS = {
    "MessageObserver": "core",
    "ProcessType": "core",
    "DataMateClient": "datamate",
    "MemoryRecord": "memory",
    "MemoryLayer": "memory",
    "MemoryType": "memory",
    "MemoryStatus": "memory",
    "MemoryConfig": "memory",
    "MemorySearchRequest": "memory",
    "MemorySearchResult": "memory",
    "MemorySearchContext": "memory",
    "ExternalMemoryItem": "memory",
    "StoreMemoryResult": "memory",
    "UnitIngestResult": "memory",
    "UnitIngestStatus": "memory",
    "ProviderError": "memory",
    "ProviderErrorCode": "memory",
    "ProviderErrorSeverity": "memory",
    "RetrievalSource": "memory",
    "PipelineMemoryRecord": "memory",
    "PipelineConfig": "memory",
    "MemoryService": "memory",
    "get_memory_service": "memory",
    "reset_memory_service": "memory",
    "MemoryAccessPolicy": "memory",
    "MemoryRetrievalPolicy": "memory",
    "MemoryStoragePolicy": "memory",
    "EmbeddingModelInfo": "memory",
    "get_embedding_client": "memory",
    "BaseMemoryProvider": "memory",
    "SearchableMemoryProvider": "memory",
    "IngestibleMemoryProvider": "memory",
    "ExternalHttpProvider": "memory",
    "ProviderRegistry": "memory",
    "get_provider_registry": "memory",
    "reset_provider_registry": "memory",
    "RetryConfig": "memory",
    "RetryableProviderError": "memory",
    "DegradableProviderError": "memory",
    "NonRetryableProviderError": "memory",
    "execute_with_retry": "memory",
    "Normalizer": "memory",
    "ScoreFusion": "memory",
    "TemporalDecayer": "memory",
    "MMRDeduplicator": "memory",
    "TokenBudgetSelector": "memory",
    "RetrievalPipeline": "memory",
    "PipelineResult": "memory",
    "count_tokens": "memory",
    "count_tokens_from_records": "memory",
    "StorageClient": "storage",
    "StorageConfig": "storage",
    "MinIOStorageConfig": "storage",
    "create_storage_client_from_config": "storage",
    "MinIOStorageClient": "storage",
    "StorageInterface": "storage",
    "RecordStore": "storage",
    "ObjectStore": "storage",
    "VectorStore": "storage",
    "KeyValueStore": "storage",
    "DataMateCore": "vector_database",
    "SkillLoader": "skills",
    "SkillManager": "skills",
    "SKILL_FILE_NAME": "skills",
}

__all__ = list(_MODULES)


def __getattr__(name):
    if name in _MODULES:
        value = import_module(f".{name}", __name__)
    elif name in _EXPORTS:
        value = getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_MODULES) | set(_EXPORTS))
