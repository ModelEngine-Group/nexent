"""LLM adapter.

LLM is the CoreAgent primary reasoning model. smolagents reaches it through
``model.__call__()`` / ``model.client`` / ``model.model_id`` / ``model.temperature``
etc. Because ``__call__`` is a Python special method it bypasses
``__getattr__`` and must be forwarded explicitly; every other attribute is
auto-forwarded to ``_inner`` via ``__getattr__`` for zero-maintenance smolagents
compat (new attributes added upstream keep working).
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin


@dataclass
class LLMRequest:
    """Batch LLM request: messages + forward kwargs."""

    messages: List[Dict[str, Any]]
    kwargs: Dict[str, Any] = field(default_factory=dict)


class LLMAdapter(MultimodalAdapter):
    """LLM adapter root. Forwards ``__call__`` explicitly + ``__getattr__`` fallback."""

    modality = "llm"

    @abstractmethod
    async def invoke(self, request: LLMRequest) -> Any:
        """Return a smolagents ChatMessage for ``request.messages``."""

    async def stream(self, request: LLMRequest) -> AsyncIterator[Any]:
        raise NotImplementedError(f"{self.modality} adapter does not support streaming")

    def __call__(self, messages: List[Dict[str, Any]], **kwargs) -> Any:
        """Explicitly forward ``__call__`` so CoreAgent can use the adapter as its model.

        Python special methods do not route through ``__getattr__``.
        Attribute forwarding (``model.client`` / ``model.model_id`` / ...) is
        inherited from :class:`MultimodalAdapter.__getattr__`.
        """
        if self._inner is None:
            self._build_inner()
        return self._inner(messages, **kwargs)


@register_adapter("openai", "llm")
class OpenAILLMAdapter(LLMAdapter, HttpTransportMixin):
    """Wraps :class:`nexent.core.models.openai_llm.OpenAIModel`."""

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
        from ...openai_llm import OpenAIModel

        # model_id / api_base / api_key are consumed by smolagents
        # OpenAIServerModel via **kwargs forwarding; observer / ssl_verify /
        # model_factory / display_name / timeout_seconds are named on OpenAIModel.
        # Per-call-site tuning (temperature/top_p/max_output_tokens/stream) is
        # carried in context.extra so switching call sites is behavior-preserving.
        extras = self._context.extra
        kwargs = dict(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=extras.get("timeout_seconds"),
            extra_body=extras.get("extra_body"),
            max_output_tokens=extras.get("max_output_tokens"),
        )
        # Only forward sampling/stream params when the call site set them, so
        # OpenAIModel defaults apply otherwise.
        for opt in ("temperature", "top_p", "stream"):
            if extras.get(opt) is not None:
                kwargs[opt] = extras.get(opt)
        self._inner = OpenAIModel(**kwargs)

    async def invoke(self, request: LLMRequest) -> Any:
        if self._inner is None:
            self._build_inner()
        return await asyncio.to_thread(
            self._inner, request.messages, **request.kwargs
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[Any]:
        if self._inner is None:
            self._build_inner()
        completion_kwargs = {
            "model": self._inner.model_id,
            "messages": request.messages,
            "stream": True,
            **request.kwargs,
        }
        return await self._inner.client.chat.completions.create(**completion_kwargs)

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        return await asyncio.to_thread(self._inner.check_connectivity)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={
                "text": True,
                "tool_calling": True,
                "long_context": False,
            },
        )


@register_adapter("openai", "llm_long_context")
class OpenAILongContextLLMAdapter(OpenAILLMAdapter):
    """Wraps :class:`OpenAILongContextModel` (which subclasses ``OpenAIModel``).

    Mirrors the ``OpenAILongContextModel → OpenAIModel`` inheritance: reuses
    ``__call__`` / ``__getattr__`` / ``invoke`` / ``stream`` / ``health_check``
    from :class:`OpenAILLMAdapter` unchanged; only ``_build_inner`` and
    ``modality`` / capability differ.
    """

    modality = "llm_long_context"

    def _build_inner(self) -> None:
        from ...openai_long_context_model import OpenAILongContextModel

        extras = self._context.extra
        self._inner = OpenAILongContextModel(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            max_context_tokens=extras.get("max_tokens", 128000),
            truncation_strategy=extras.get("truncation_strategy", "start"),
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=extras.get("timeout_seconds"),
            extra_body=extras.get("extra_body"),
            max_output_tokens=extras.get("max_output_tokens"),
        )

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={
                "text": True,
                "tool_calling": True,
                "long_context": True,
            },
        )
