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
        """
        if self._inner is None:
            self._build_inner()
        return self._inner(messages, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Fallback: forward unknown attributes to ``_inner``.

        ``_inner`` and ``_context`` are real instance attributes set in
        ``__init__``, so accessing them here never recurses. This covers
        ``model.client`` / ``model.model_id`` / ``model.temperature`` /
        ``model.safe_input_budget_snapshot`` and any future smolagents
        attribute — zero maintenance cost.
        """
        # Guard against the bootstrap window before __init__ sets _inner, and
        # avoid recursing on private dunder lookups.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        inner = self.__dict__.get("_inner")
        if inner is not None:
            return getattr(inner, name)
        raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")


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
        from ..openai_llm import OpenAIModel

        # model_id / api_base / api_key are consumed by smolagents
        # OpenAIServerModel via **kwargs forwarding; observer / ssl_verify /
        # model_factory / display_name / timeout_seconds are named on OpenAIModel.
        self._inner = OpenAIModel(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=self._context.extra.get("timeout_seconds"),
            extra_body=self._context.extra.get("extra_body"),
            max_output_tokens=self._context.extra.get("max_output_tokens"),
        )

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
        from ..openai_long_context_model import OpenAILongContextModel

        self._inner = OpenAILongContextModel(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            max_context_tokens=self._context.extra.get("max_tokens", 128000),
            truncation_strategy=self._context.extra.get(
                "truncation_strategy", "start"
            ),
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=self._context.extra.get("timeout_seconds"),
            extra_body=self._context.extra.get("extra_body"),
            max_output_tokens=self._context.extra.get("max_output_tokens"),
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
