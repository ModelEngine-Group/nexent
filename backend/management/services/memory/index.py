# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management adapter for the shared Memory index."""

from typing import Optional

from contracts.knowledge import VectorDatabaseType
from infrastructure.vdb.memory_index import MemoryIndexService as StorageMemoryIndex
from infrastructure.vdb.memory_index import _memory_chunk_payload as _memory_chunk_payload
from infrastructure.vdb.memory_index import _safe_score_preview as _safe_score_preview
from management.services.knowledge_base.service import get_vector_db_core


class MemoryIndexService(StorageMemoryIndex):
    def __init__(self, vdb_core=None):
        super().__init__(vdb_core, create_core=lambda: get_vector_db_core(VectorDatabaseType.ELASTICSEARCH))


# Singleton-style accessor matching the rest of the service modules.
_default_service: Optional[MemoryIndexService] = None


def get_memory_index_service() -> MemoryIndexService:
    """Return a process-wide MemoryIndexService."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryIndexService()
    return _default_service


def reset_memory_index_service() -> None:
    """Reset the cached service (used by tests)."""
    global _default_service
    _default_service = None
