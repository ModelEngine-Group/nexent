"""Memory policies defining layer hierarchy and access rules.

This module defines the policies governing memory access, storage
permissions, and hierarchy rules. It implements the three-layer memory
architecture without committing to any specific storage backend - the
SDK stays backend-agnostic, and persistence decisions are made by the
backend layer that invokes these policies:

- Tenant layer: Tenant-level long-term memory
- User layer: User-level long-term memory
- Agent layer: Agent-level short-term memory

Per the Nexent architecture, tenant/user long-term memory is always
injected in full (no vector search), while agent short-term memory is
retrieved via vector similarity.
"""

from __future__ import annotations

import logging
from typing import List, Set

from .models import MemoryLayer, MemoryType


logger = logging.getLogger("memory_policy")


class MemoryAccessPolicy:
    """Policy governing which memory layers can be read/written by whom.

    This policy implements the access control rules defined in the memory design:
    - Agents can ONLY write to agent short-term memory
    - Tenant/user long-term memory is read-only for agents (managed manually or by Dreaming)
    - All layers can be read based on scope filtering
    """

    # Layers that agents can write to (via store_memory tool)
    AGENT_WRITEABLE_LAYERS: Set[MemoryLayer] = {MemoryLayer.AGENT}
    AGENT_WRITEABLE_TYPES: Set[MemoryType] = {MemoryType.SHORT_TERM}

    # Layers that agents can read from (via search_memory tool)
    AGENT_READABLE_LAYERS: Set[MemoryLayer] = {MemoryLayer.TENANT, MemoryLayer.USER, MemoryLayer.AGENT}
    AGENT_READABLE_TYPES: Set[MemoryType] = {MemoryType.SHORT_TERM, MemoryType.LONG_TERM}

    # Layers managed by Dreaming (Deep Sleep promotion)
    DREAMING_WRITEABLE_LAYERS: Set[MemoryLayer] = {MemoryLayer.USER}
    DREAMING_WRITEABLE_TYPES: Set[MemoryType] = {MemoryType.LONG_TERM}

    @classmethod
    def can_agent_write(cls, layer: MemoryLayer, memory_type: MemoryType) -> bool:
        """Check if an agent can write to the specified layer/type.

        Agents are only allowed to write to agent short-term memory.

        Args:
            layer: The memory layer.
            memory_type: The memory type within the layer.

        Returns:
            True if agents can write, False otherwise.
        """
        return layer in cls.AGENT_WRITEABLE_LAYERS and memory_type in cls.AGENT_WRITEABLE_TYPES

    @classmethod
    def can_agent_read(cls, layer: MemoryLayer, memory_type: MemoryType) -> bool:
        """Check if an agent can read from the specified layer/type.

        Args:
            layer: The memory layer.
            memory_type: The memory type within the layer.

        Returns:
            True if agents can read, False otherwise.
        """
        return layer in cls.AGENT_READABLE_LAYERS and memory_type in cls.AGENT_READABLE_TYPES

    @classmethod
    def can_dreaming_write(cls, layer: MemoryLayer, memory_type: MemoryType) -> bool:
        """Check if Dreaming can write to the specified layer/type.

        Dreaming can promote memories to user long-term memory.

        Args:
            layer: The memory layer.
            memory_type: The memory type within the layer.

        Returns:
            True if Dreaming can write, False otherwise.
        """
        return layer in cls.DREAMING_WRITEABLE_LAYERS and memory_type in cls.DREAMING_WRITEABLE_TYPES

    @classmethod
    def get_default_search_layers(cls) -> List[MemoryLayer]:
        """Get the default layers to search for agent memory operations.

        Returns:
            List of layers that should be searched by default.
        """
        return [MemoryLayer.TENANT, MemoryLayer.USER, MemoryLayer.AGENT]


class MemoryStoragePolicy:
    """Policy governing memory storage and retention rules."""

    # Maximum number of store operations per agent run
    MAX_STORES_PER_RUN: int = 3

    # Layers that the backend stores with a vector index.
    # The SDK does not perform the indexing; it only signals to the
    # backend that vector retrieval will be needed for these layers.
    VECTOR_INDEXED_LAYERS: Set[MemoryLayer] = {MemoryLayer.AGENT}

    # Layers whose contents are loaded as full context (no vector search).
    PG_ONLY_LAYERS: Set[MemoryLayer] = {MemoryLayer.TENANT, MemoryLayer.USER}

    @classmethod
    def requires_vector_index(cls, layer: MemoryLayer) -> bool:
        """Check if a layer requires vector indexing by the backend.

        Agent short-term memory requires vector indexing so the backend
        can perform similarity retrieval. Tenant/user long-term memory
        is loaded in full and does not require a vector index.

        Args:
            layer: The memory layer.

        Returns:
            True if vector indexing is required, False otherwise.
        """
        return layer in cls.VECTOR_INDEXED_LAYERS

    @classmethod
    def get_storage_layers_for_layer(cls, layer: MemoryLayer) -> List[MemoryLayer]:
        """Get all storage layers required for a given layer.

        Agent memory requires both PostgreSQL and Elasticsearch.
        Tenant/user memory only requires PostgreSQL.

        Args:
            layer: The memory layer.

        Returns:
            List of storage layers needed.
        """
        if layer in cls.VECTOR_INDEXED_LAYERS:
            return [MemoryLayer.AGENT]  # Both PG and ES
        return [layer]  # PG only


class MemoryRetrievalPolicy:
    """Policy governing memory retrieval behavior."""

    # Default number of results to return
    DEFAULT_TOP_K: int = 5

    # Maximum number of results
    MAX_TOP_K: int = 100

    # Default similarity threshold
    DEFAULT_THRESHOLD: float = 0.65

    # Layers that use full-context injection (no vector search)
    FULL_CONTEXT_LAYERS: Set[MemoryLayer] = {MemoryLayer.TENANT, MemoryLayer.USER}

    # Layers that use vector search
    VECTOR_SEARCH_LAYERS: Set[MemoryLayer] = {MemoryLayer.AGENT}

    @classmethod
    def uses_full_context(cls, layer: MemoryLayer) -> bool:
        """Check if a layer uses full-context injection.

        Tenant and user long-term memory are always injected in full
        without vector search filtering.

        Args:
            layer: The memory layer.

        Returns:
            True if full-context injection is used, False otherwise.
        """
        return layer in cls.FULL_CONTEXT_LAYERS

    @classmethod
    def uses_full_context_for_layer(cls, layer) -> bool:
        """String-friendly variant of :py:meth:`uses_full_context`.

        Accepts either a :class:`MemoryLayer` enum or a raw string value so
        service-layer callers that already have a string layer name don't
        need to import the enum.
        """
        try:
            layer_enum = layer if isinstance(layer, MemoryLayer) else MemoryLayer(layer)
        except ValueError:
            return False
        return cls.uses_full_context(layer_enum)

    @classmethod
    def uses_vector_search(cls, layer: MemoryLayer) -> bool:
        """Check if a layer uses vector search.

        Agent short-term memory uses vector similarity search.

        Args:
            layer: The memory layer.

        Returns:
            True if vector search is used, False otherwise.
        """
        return layer in cls.VECTOR_SEARCH_LAYERS

    @classmethod
    def validate_top_k(cls, top_k: int) -> int:
        """Validate and clamp the top_k value.

        Args:
            top_k: Requested number of results.

        Returns:
            Clamped top_k value within valid range.
        """
        if top_k <= 0:
            return cls.DEFAULT_TOP_K
        return min(top_k, cls.MAX_TOP_K)
