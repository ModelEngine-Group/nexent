"""Modality adapter aggregation layer.

Re-exports the public adapter API and triggers registration of all built-in
adapters via the ``@register_adapter`` decorators on import.
"""

from .llm.llm_adapter import LLMAdapter, LLMRequest
from .llm.openai import OpenAILLMAdapter, OpenAILongContextLLMAdapter
from .vlm.modelengine import ModelEngineVLMAdapter
from .vlm.openai import OpenAIVLMAdapter
from .vlm.vlm_adapter import VLMAdapter, VLMRequest

from .embedding.dashscope import DashScopeEmbeddingAdapter
from .embedding.embedding_adapter import EmbeddingAdapter, EmbeddingRequest
from .embedding.jina import JinaEmbeddingAdapter
from .embedding.openai import OpenAICompatibleEmbeddingAdapter
from .embedding.siliconflow import SiliconflowEmbeddingAdapter
from .rerank.cohere import CohereRerankAdapter
from .rerank.jina import JinaRerankAdapter
from .rerank.openai import OpenAICompatibleRerankAdapter
from .rerank.rerank_adapter import RerankAdapter, RerankRequest

__all__: list[str] = [
    # LLM
    "LLMAdapter", "LLMRequest", "OpenAILLMAdapter", "OpenAILongContextLLMAdapter",
    # VLM
    "VLMAdapter", "VLMRequest", "OpenAIVLMAdapter", "ModelEngineVLMAdapter",
    # Embedding
    "EmbeddingAdapter", "EmbeddingRequest", "JinaEmbeddingAdapter",
    "DashScopeEmbeddingAdapter", "SiliconflowEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
    # Rerank
    "RerankAdapter", "RerankRequest", "OpenAICompatibleRerankAdapter",
    "JinaRerankAdapter", "CohereRerankAdapter",
]
