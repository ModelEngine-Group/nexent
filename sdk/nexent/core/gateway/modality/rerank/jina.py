"""Jina AI rerank adapter."""

from __future__ import annotations

from ...model_context import ModelContext
from ...registry import register_adapter
from .openai import OpenAICompatibleRerankAdapter
from .rerank_adapter import _apply_defaults


@register_adapter("jina", "rerank")
class JinaRerankAdapter(OpenAICompatibleRerankAdapter):
    """Jina AI rerank — default base_url/model applied when the cfg omits them.

    Attributes:
        factory: ``"jina"``.
    """

    factory = "jina"

    def __init__(self, context: ModelContext) -> None:
        context = _apply_defaults(context, "https://api.jina.ai/v1/rerank", "jina-rerank-v2-base")
        super().__init__(context)
