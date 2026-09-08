"""Embedding model metadata and client factory for the memory system.

This module provides:

- ``EmbeddingModelInfo``: a value object that carries embedding model
  configuration (name, repo, dimension, base URL, API key). It also exposes
  ``get_index_name()`` which derives the deterministic Elasticsearch index
  name following the convention from the Memory SPEC::

      mem_{model_repo}_{model_name}_{dimension}
      mem_{model_name}_{dimension}            # when model_repo is absent

- ``get_embedding_client()``: builds an ``OpenAICompatibleEmbeddingAdapter``
  from the caller-supplied configuration.

The SDK never talks to Elasticsearch directly. All vector writes go through
the backend layer (``memory_index_service``). This module is therefore purely
a data-transformation and lifecycle-management helper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..core.gateway import EmbeddingContext
from ..core.gateway.modality import OpenAICompatibleEmbeddingAdapter


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
# Embedding client factory                                                     #
# --------------------------------------------------------------------------- #


def get_embedding_client(
    model_name: str,
    dimension: int,
    base_url: str,
    api_key: str,
    model_repo: Optional[str] = None,
    ssl_verify: bool = True,
) -> OpenAICompatibleEmbeddingAdapter:
    """Return an ``OpenAICompatibleEmbeddingAdapter`` instance.

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
        A newly created ``OpenAICompatibleEmbeddingAdapter`` instance.
    """
    # Form the fully-qualified model name the API expects.
    full_model_name = f"{model_repo}/{model_name}" if model_repo else model_name
    return OpenAICompatibleEmbeddingAdapter(
        EmbeddingContext(
            model_name=full_model_name,
            base_url=base_url,
            api_key=api_key,
            modality="embedding",
            factory="openai",
            embedding_dim=dimension,
            ssl_verify=ssl_verify,
        )
    )
