"""Embedding model registry for memory operations.

This module manages embedding models for the memory system. It maintains a cache
of embedding models indexed by their name. The Elasticsearch index naming
follows the pattern: mem_{model_repo}_{model_name}_{dimension}.

This index naming convention is preserved from the existing implementation
to ensure backward compatibility with previously stored memories.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..core.models.embedding_model import OpenAICompatibleEmbedding
from .models import MemoryConfig


logger = logging.getLogger("memory_embedding_registry")


def _sanitize_index_component(value: str) -> str:
    """Convert arbitrary text into an Elasticsearch-safe index component."""
    return re.sub(r"[^a-z0-9_.-]", "_", value.lower())


@dataclass
class EmbeddingModelInfo:
    """Information about a registered embedding model."""
    model_name: str
    model_repo: Optional[str]
    dimension: int
    base_url: str
    api_key: str
    ssl_verify: bool = True

    def get_index_name(self) -> str:
        """Generate the Elasticsearch index name for this model.

        Pattern: mem_{model_repo}_{model_name}_{dimension}
        """
        safe_repo = _sanitize_index_component(self.model_repo or "")
        safe_name = _sanitize_index_component(self.model_name)

        if safe_repo:
            return f"mem_{safe_repo}_{safe_name}_{self.dimension}"
        return f"mem_{safe_name}_{self.dimension}"


class EmbeddingModelRegistry:
    """Registry of embedding models used by the memory system.

    Models are indexed by their unique key (name + dimension).
    The Elasticsearch index name is derived from the model configuration.
    """

    def __init__(self):
        self._models: Dict[str, EmbeddingModelInfo] = {}
        self._instances: Dict[str, OpenAICompatibleEmbedding] = {}

    def _make_key(self, model_name: str, dimension: int) -> str:
        """Create a unique key for the model cache."""
        return f"{model_name}:{dimension}"

    def register(
        self,
        model_name: str,
        dimension: int,
        base_url: str,
        api_key: str,
        model_repo: Optional[str] = None,
        ssl_verify: bool = True,
    ) -> EmbeddingModelInfo:
        """Register an embedding model.

        Args:
            model_name: Name of the embedding model.
            dimension: Embedding vector dimension.
            base_url: Base URL for the embedding API.
            api_key: API key for authentication.
            model_repo: Optional model repository (vendor name).
            ssl_verify: Whether to verify SSL certificates.

        Returns:
            The registered EmbeddingModelInfo.
        """
        key = self._make_key(model_name, dimension)
        model_info = EmbeddingModelInfo(
            model_name=model_name,
            model_repo=model_repo,
            dimension=dimension,
            base_url=base_url,
            api_key=api_key,
            ssl_verify=ssl_verify,
        )
        self._models[key] = model_info
        logger.debug(f"Registered embedding model: {model_info.get_index_name()}")
        return model_info

    def get(
        self,
        model_name: str,
        dimension: int,
    ) -> Optional[EmbeddingModelInfo]:
        """Get a registered embedding model by name and dimension.

        Args:
            model_name: Name of the embedding model.
            dimension: Embedding vector dimension.

        Returns:
            EmbeddingModelInfo if found, None otherwise.
        """
        key = self._make_key(model_name, dimension)
        return self._models.get(key)

    def get_instance(
        self,
        model_name: str,
        dimension: int,
        base_url: str,
        api_key: str,
        model_repo: Optional[str] = None,
        ssl_verify: bool = True,
    ) -> OpenAICompatibleEmbedding:
        """Get or create an embedding model instance.

        This method reuses instances when possible to avoid re-initialization.

        Args:
            model_name: Name of the embedding model.
            dimension: Embedding vector dimension.
            base_url: Base URL for the embedding API.
            api_key: API key for authentication.
            model_repo: Optional model repository.
            ssl_verify: Whether to verify SSL certificates.

        Returns:
            An OpenAICompatibleEmbedding instance.
        """
        key = self._make_key(model_name, dimension)
        if key not in self._instances:
            self._instances[key] = OpenAICompatibleEmbedding(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                embedding_dim=dimension,
                ssl_verify=ssl_verify,
            )
        return self._instances[key]

    def list_index_names(self) -> List[str]:
        """List all registered Elasticsearch index names.

        Returns:
            List of index names following the mem_{...}_{dimension} pattern.
        """
        return [model_info.get_index_name() for model_info in self._models.values()]

    def get_index_name(
        self,
        model_name: str,
        model_repo: Optional[str],
        dimension: int,
    ) -> str:
        """Get the Elasticsearch index name for a given model configuration.

        This method follows the same naming convention as the existing
        implementation: mem_{model_repo}_{model_name}_{dimension} or
        mem_{model_name}_{dimension}.

        Args:
            model_name: Name of the embedding model.
            model_repo: Optional model repository.
            dimension: Embedding vector dimension.

        Returns:
            The Elasticsearch index name.
        """
        safe_repo = _sanitize_index_component(model_repo or "")
        safe_name = _sanitize_index_component(model_name)

        if safe_repo:
            return f"mem_{safe_repo}_{safe_name}_{dimension}"
        return f"mem_{safe_name}_{dimension}"

    def clear(self) -> None:
        """Clear all registered models."""
        self._models.clear()
        self._instances.clear()
        logger.debug("Cleared embedding model registry")


# Global registry instance
_embedding_registry: Optional[EmbeddingModelRegistry] = None


def get_embedding_registry() -> EmbeddingModelRegistry:
    """Get the global embedding model registry.

    Returns:
        The global EmbeddingModelRegistry instance.
    """
    global _embedding_registry
    if _embedding_registry is None:
        _embedding_registry = EmbeddingModelRegistry()
    return _embedding_registry


def reset_embedding_registry() -> None:
    """Reset the global embedding model registry."""
    global _embedding_registry
    if _embedding_registry is not None:
        _embedding_registry.clear()
    _embedding_registry = None
