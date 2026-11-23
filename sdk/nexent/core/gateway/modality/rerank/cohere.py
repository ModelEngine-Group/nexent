"""Cohere rerank adapter."""

from __future__ import annotations

from ...model_context import ModelContext
from ...registry import register_adapter
from .openai import OpenAICompatibleRerankAdapter
from .rerank_adapter import _apply_defaults


@register_adapter("cohere", "rerank")
class CohereRerankAdapter(OpenAICompatibleRerankAdapter):
    """Cohere rerank — default base_url/model applied when the cfg omits them.

    Attributes:
        factory: ``"cohere"``.
    """

    factory = "cohere"

    def __init__(self, context: ModelContext) -> None:
        context = _apply_defaults(context, "https://api.cohere.ai/v1/rerank", "rerank-multilingual-v3.0")
        super().__init__(context)
