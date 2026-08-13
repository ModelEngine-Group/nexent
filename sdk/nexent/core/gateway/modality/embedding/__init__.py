"""Embedding adapters; importing this package registers Jina/DashScope/Siliconflow/OpenAI."""

from .adapter import (
    DashScopeEmbeddingAdapter,
    EmbeddingAdapter,
    EmbeddingRequest,
    JinaEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    SiliconflowEmbeddingAdapter,
)

__all__ = [
    "EmbeddingAdapter",
    "EmbeddingRequest",
    "JinaEmbeddingAdapter",
    "DashScopeEmbeddingAdapter",
    "SiliconflowEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
]
