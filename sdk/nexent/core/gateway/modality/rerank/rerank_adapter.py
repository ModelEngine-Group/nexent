"""Rerank adapter root: request type + default-application helper."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

from ...model_context import ModelContext
from ...multimodal_adapter import MultimodalAdapter


@dataclass
class RerankRequest:
    """Rerank request.

    Attributes:
        query: The query to rerank documents against.
        documents: The documents to rerank.
        top_n: Optional limit on the number of returned documents.
    """

    query: str
    documents: List[str]
    top_n: Optional[int] = None


class RerankAdapter(MultimodalAdapter):
    """Rerank adapter root.

    Attributes:
        modality: ``"rerank"``.
    """

    modality = "rerank"

    @abstractmethod
    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        """Reranks ``request.documents`` for ``request.query``.

        Args:
            request: The rerank request containing the query and documents.

        Returns:
            The reranked result list.
        """


def _apply_defaults(context: ModelContext, base_url: str, model_name: str) -> ModelContext:
    """Return a context with default base_url/model applied when they are unset.

    Non-mutating: returns a shallow :func:`dataclasses.replace` copy so a
    shared (e.g. cached) context is never rewritten in place by one vendor's
    defaults.
    """
    if not context.base_url or not context.model_name:
        return replace(
            context,
            base_url=context.base_url or base_url,
            model_name=context.model_name or model_name,
        )
    return context
