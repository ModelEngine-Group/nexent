"""Rerank adapter.

Health check unifies on :meth:`connectivity_check` (the legacy rerank name;
VLM/STT/TTS used ``check_connectivity``, embedding used ``dimension_check``).
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin


@dataclass
class RerankRequest:
    """Rerank request."""

    query: str
    documents: List[str]
    top_n: Optional[int] = None


class RerankAdapter(MultimodalAdapter):
    """Rerank adapter root."""

    modality = "rerank"

    @abstractmethod
    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        """Rerank ``request.documents`` for ``request.query`` → result list."""

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        return await self._inner.connectivity_check(timeout=5.0)


@register_adapter("openai", "rerank")
class OpenAICompatibleRerankAdapter(RerankAdapter, HttpTransportMixin):
    """Wraps :class:`OpenAICompatibleRerank`. URL-sniff dispatch (DashScope vs
    OpenAI-compatible request body) lives inside the wrapped class's
    ``_prepare_request``; the adapter is vendor-agnostic."""

    factory = "openai"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )

    def _build_inner(self) -> None:
        from ...rerank_model import OpenAICompatibleRerank

        self._inner = OpenAICompatibleRerank(
            model_name=self._context.model_name,
            base_url=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
        )

    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        if self._inner is None:
            self._build_inner()
        return await asyncio.to_thread(
            self._inner.rerank, request.query, request.documents, request.top_n
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"rerank": True},
        )


@register_adapter("jina", "rerank")
class JinaRerankAdapter(RerankAdapter, HttpTransportMixin):
    """Wraps :class:`JinaRerank`."""

    factory = "jina"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )

    def _build_inner(self) -> None:
        from ...rerank_model import JinaRerank

        self._inner = JinaRerank(
            api_key=self._api_key,
            base_url=self._base_url,
            model_name=self._context.model_name,
            ssl_verify=self._ssl_verify,
        )

    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        if self._inner is None:
            self._build_inner()
        return await asyncio.to_thread(
            self._inner.rerank, request.query, request.documents, request.top_n
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"rerank": True},
        )


@register_adapter("cohere", "rerank")
class CohereRerankAdapter(RerankAdapter, HttpTransportMixin):
    """Wraps :class:`CohereRerank`."""

    factory = "cohere"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )

    def _build_inner(self) -> None:
        from ...rerank_model import CohereRerank

        self._inner = CohereRerank(
            api_key=self._api_key,
            base_url=self._base_url,
            model_name=self._context.model_name,
            ssl_verify=self._ssl_verify,
        )

    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        if self._inner is None:
            self._build_inner()
        return await asyncio.to_thread(
            self._inner.rerank, request.query, request.documents, request.top_n
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"rerank": True},
        )
