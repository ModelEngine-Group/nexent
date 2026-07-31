"""Embedding model metadata and client cache for the memory system.

This module provides:

- ``EmbeddingModelInfo``: a value object that carries embedding model
  configuration (name, repo, dimension, base URL, API key). It also exposes
  ``get_index_name()`` which derives the deterministic Elasticsearch index
  name following the convention from the Memory SPEC::

      mem_{model_repo}_{model_name}_{dimension}
      mem_{model_name}_{dimension}            # when model_repo is absent

- ``get_embedding_client()``: a process-wide cache that reuses
  ``OpenAICompatibleEmbedding`` instances keyed by ``(model_name, dimension)``.
  Creating an HTTP client per memory write would add unnecessary latency;
  caching a single instance per model avoids that while keeping the SDK
  layer stateless.

The SDK never talks to Elasticsearch directly. All vector writes go through
the backend layer (``memory_index_service``). This module is therefore purely
a data-transformation and lifecycle-management helper.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from ..core.models.embedding_model import OpenAICompatibleEmbedding

logger = logging.getLogger("memory_embedding_model")


def _sanitize_index_component(value: str) -> str:
    """Convert arbitrary text into an Elasticsearch-safe index component."""
    return re.sub(r"[^a-z0-9_.-]", "_", value.lower())


@dataclass
class EmbeddingModelInfo:
    """Immutable metadata about an embedding model used for memory vectorisation.

    Attributes:
        model_name: Canonical name of the embedding model (e.g. ``text-embedding-3-small``).
        dimension: Vector dimensionality produced by the model.
        base_url: Base URL for the embedding API endpoint.
        api_key: API key for authentication.
        model_repo: Optional vendor / repository name (e.g. ``openai``, ``local``).
            Included in the ES index name when present.
        ssl_verify: Whether to verify SSL certificates (default ``True``).
    """

    model_name: str
    dimension: int
    base_url: str
    api_key: str
    model_repo: Optional[str] = None
    ssl_verify: bool = True

    def get_index_name(self) -> str:
        """Derive the Elasticsearch index name for this model.

        Pattern: ``mem_{model_repo}_{model_name}_{dimension}``
        If ``model_repo`` is absent: ``mem_{model_name}_{dimension}``

        This is the convention described in SPEC §5.2 (Functional Design):
        switching an embedding model retires the old index automatically because
        new writes carry a different ``es_index_name``.
        """
        safe_repo = _sanitize_index_component(self.model_repo or "")
        safe_name = _sanitize_index_component(self.model_name)

        if safe_repo:
            return f"mem_{safe_repo}_{safe_name}_{self.dimension}"
        return f"mem_{safe_name}_{self.dimension}"


# --------------------------------------------------------------------------- #
# Process-wide HTTP client cache                                               #
# --------------------------------------------------------------------------- #
# Key = "model_name:dimension", Value = OpenAICompatibleEmbedding instance.
_embedding_client_cache: dict[str, OpenAICompatibleEmbedding] = {}


def get_embedding_client(
    model_name: str,
    dimension: int,
    base_url: str,
    api_key: str,
    model_repo: Optional[str] = None,
    ssl_verify: bool = True,
) -> OpenAICompatibleEmbedding:
    """Return a cached ``OpenAICompatibleEmbedding`` instance.

    Instances are cached by ``(model_repo, model_name, dimension)`` so that
    repeated memory writes within the same process reuse the underlying HTTP
    client and connection pool.

    When ``model_repo`` is provided (e.g. ``"BAAI"``), the fully-qualified
    name ``"BAAI/bge-m3"`` is passed to the API. Some providers (e.g.
    SiliconFlow) require the vendor prefix in the request body.

    Args:
        model_name: Name of the embedding model.
        dimension: Vector dimensionality.
        base_url: Base URL for the embedding API.
        api_key: API key for authentication.
        model_repo: Optional model repository (vendor name). Prepended as
            ``{model_repo}/{model_name}`` in the API request body.
        ssl_verify: Whether to verify SSL certificates.

    Returns:
        A cached (or newly created) ``OpenAICompatibleEmbedding`` instance.
    """
    cache_key = f"{model_repo or ''}:{model_name}:{dimension}"
    if cache_key not in _embedding_client_cache:
        # Form the fully-qualified model name the API expects.
        full_model_name = f"{model_repo}/{model_name}" if model_repo else model_name
        _embedding_client_cache[cache_key] = OpenAICompatibleEmbedding(
            model_name=full_model_name,
            base_url=base_url,
            api_key=api_key,
            embedding_dim=dimension,
            ssl_verify=ssl_verify,
        )
        logger.debug(
            "Created and cached embedding client for model=%s dim=%d",
            full_model_name,
            dimension,
        )
    return _embedding_client_cache[cache_key]


def reset_embedding_client_cache() -> None:
    """Clear all cached embedding client instances.

    Call this in test teardown to ensure test isolation.
    """
    _embedding_client_cache.clear()
    logger.debug("Cleared embedding client cache")
