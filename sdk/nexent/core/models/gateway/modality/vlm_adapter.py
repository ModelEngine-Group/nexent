"""VLM (vision-language model) adapter.

Wraps :class:`OpenAIVLModel` (which subclasses ``OpenAIModel``). Image / audio /
video understanding all flow through ``analyze_image`` / ``analyze_audio`` /
``analyze_video``. ModelEngine's VLM protocol is identical to OpenAI's, so its
adapter reuses the same ``_inner`` class with a different ``factory`` tag.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, Optional, Union

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin

_METHOD_MAP = {"image": "analyze_image", "audio": "analyze_audio", "video": "analyze_video"}


@dataclass
class VLMRequest:
    """VLM understanding request."""

    media_type: str  # "image" | "audio" | "video"
    media_input: Union[str, BinaryIO]
    prompt: str = ""
    stream: bool = True
    kwargs: Optional[Dict[str, Any]] = None


class VLMAdapter(MultimodalAdapter):
    """VLM adapter root."""

    modality = "vlm"

    @abstractmethod
    async def invoke(self, request: VLMRequest) -> Any:
        """Analyze ``media_input`` with ``prompt`` → ChatMessage."""


@register_adapter("openai", "vlm")
class OpenAIVLMAdapter(VLMAdapter, HttpTransportMixin):
    """Wraps :class:`OpenAIVLModel`."""

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
        from ...openai_vlm import OpenAIVLModel

        # model_id / api_base / api_key forward via **kwargs to OpenAIServerModel.
        self._inner = OpenAIVLModel(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
        )

    async def invoke(self, request: VLMRequest) -> Any:
        if self._inner is None:
            self._build_inner()
        method = getattr(self._inner, _METHOD_MAP[request.media_type])
        call_kwargs = {"stream": request.stream}
        if request.prompt:
            call_kwargs["system_prompt"] = request.prompt
        if request.kwargs:
            call_kwargs.update(request.kwargs)
        return await asyncio.to_thread(method, request.media_input, **call_kwargs)

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        return await self._inner.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        caps = self._context.capabilities or {
            "image": True,
            "audio": True,
            "video": True,
        }
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities=caps,
        )


@register_adapter("modelengine", "vlm")
class ModelEngineVLMAdapter(OpenAIVLMAdapter):
    """ModelEngine VLM — protocol identical to OpenAI; only ``factory`` differs.

    Reuses :class:`OpenAIVLMAdapter`'s ``_build_inner`` / ``invoke`` /
    ``health_check`` / ``get_model_info`` unchanged.
    """

    factory = "modelengine"
