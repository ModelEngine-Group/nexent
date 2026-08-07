"""Embedding adapter.

Text embeddings use :meth:`get_embeddings` (str / List[str]); multimodal
embeddings use :meth:`get_multimodal_embeddings` (List[Dict]). Health check
unifies on :meth:`dimension_check` (replaces the legacy name for VLM/STT/TTS
which used ``check_connectivity``).
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Union

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin


@dataclass
class EmbeddingRequest:
    """Embedding request: text or multimodal inputs."""

    inputs: Union[str, List[str], List[Dict[str, Any]]]
    with_metadata: bool = False
    timeout: float = None
    retries: int = 3
    retry_timeout_step: float = 5.0


class EmbeddingAdapter(MultimodalAdapter):
    """Embedding adapter root (``modality`` = ``embedding`` or ``multi_embedding``)."""

    @abstractmethod
    async def invoke(self, request: EmbeddingRequest) -> Union[
        List[List[float]], Dict[str, Any]
    ]:
        """Return embedding vectors for ``request.inputs``."""


def _is_multimodal(inputs: Any) -> bool:
    return isinstance(inputs, list) and bool(inputs) and isinstance(inputs[0], dict)


@register_adapter("jina", "multi_embedding")
class JinaEmbeddingAdapter(EmbeddingAdapter, HttpTransportMixin):
    """Wraps :class:`JinaEmbedding`."""

    modality = "multi_embedding"
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
        from ..embedding_model import JinaEmbedding

        self._inner = JinaEmbedding(
            api_key=self._api_key,
            base_url=self._base_url,
            model_name=self._context.model_name,
            embedding_dim=self._context.embedding_dim or 1024,
            ssl_verify=self._ssl_verify,
            model_type="multimodal",
        )

    async def invoke(self, request: EmbeddingRequest):
        if self._inner is None:
            self._build_inner()
        if _is_multimodal(request.inputs):
            return await self._inner.get_multimodal_embeddings(
                request.inputs,
                with_metadata=request.with_metadata,
                timeout=request.timeout,
            )
        return await self._inner.get_embeddings(
            request.inputs,
            with_metadata=request.with_metadata,
            timeout=request.timeout,
        )

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        try:
            await self._inner.dimension_check(timeout=5.0)
            return True
        except Exception:
            return False

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"text": True, "multimodal": True},
        )


@register_adapter("dashscope", "multi_embedding")
class DashScopeEmbeddingAdapter(EmbeddingAdapter, HttpTransportMixin):
    """Wraps :class:`DashScopeMultimodalEmbedding`."""

    modality = "multi_embedding"
    factory = "dashscope"

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
        from ..embedding_model import DashScopeMultimodalEmbedding

        self._inner = DashScopeMultimodalEmbedding(
            api_key=self._api_key,
            base_url=self._base_url,
            model_name=self._context.model_name,
            embedding_dim=self._context.embedding_dim or 1024,
            ssl_verify=self._ssl_verify,
        )

    async def invoke(self, request: EmbeddingRequest):
        if self._inner is None:
            self._build_inner()
        if _is_multimodal(request.inputs):
            return await self._inner.get_multimodal_embeddings(
                request.inputs, with_metadata=request.with_metadata, timeout=request.timeout
            )
        return await self._inner.get_embeddings(
            request.inputs, with_metadata=request.with_metadata, timeout=request.timeout
        )

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        try:
            await self._inner.dimension_check(timeout=5.0)
            return True
        except Exception:
            return False

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"text": True, "multimodal": True},
        )


@register_adapter("siliconflow", "multi_embedding")
class SiliconflowEmbeddingAdapter(EmbeddingAdapter, HttpTransportMixin):
    """Wraps :class:`SiliconflowMultimodalEmbedding`."""

    modality = "multi_embedding"
    factory = "siliconflow"

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
        from ..embedding_model import SiliconflowMultimodalEmbedding

        self._inner = SiliconflowMultimodalEmbedding(
            api_key=self._api_key,
            base_url=self._base_url,
            model_name=self._context.model_name,
            embedding_dim=self._context.embedding_dim or 1024,
            ssl_verify=self._ssl_verify,
        )

    async def invoke(self, request: EmbeddingRequest):
        if self._inner is None:
            self._build_inner()
        if _is_multimodal(request.inputs):
            return await self._inner.get_multimodal_embeddings(
                request.inputs, with_metadata=request.with_metadata, timeout=request.timeout
            )
        return await self._inner.get_embeddings(
            request.inputs, with_metadata=request.with_metadata, timeout=request.timeout
        )

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        try:
            await self._inner.dimension_check(timeout=5.0)
            return True
        except Exception:
            return False

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"text": True, "multimodal": True},
        )


@register_adapter("openai", "embedding")
class OpenAICompatibleEmbeddingAdapter(EmbeddingAdapter, HttpTransportMixin):
    """Wraps :class:`OpenAICompatibleEmbedding` (text embeddings)."""

    modality = "embedding"
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
        from ..embedding_model import OpenAICompatibleEmbedding

        self._inner = OpenAICompatibleEmbedding(
            model_name=self._context.model_name,
            base_url=self._base_url,
            api_key=self._api_key,
            embedding_dim=self._context.embedding_dim or 1024,
            model_type=self._context.model_type or "embedding",
            ssl_verify=self._ssl_verify,
        )

    async def invoke(self, request: EmbeddingRequest):
        if self._inner is None:
            self._build_inner()
        return await self._inner.get_embeddings(
            request.inputs,
            with_metadata=request.with_metadata,
            timeout=request.timeout,
        )

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        try:
            await self._inner.dimension_check(timeout=5.0)
            return True
        except Exception:
            return False

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"text": True, "multimodal": False},
        )
