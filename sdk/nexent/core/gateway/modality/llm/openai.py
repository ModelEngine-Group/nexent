"""OpenAI LLM adapters: standard + long-context."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from nexent.core.models import OpenAILongContextModel, OpenAIModel

from ...model_context import LLMContext
from ...multimodal_adapter import ModelInfo
from ...registry import register_adapter
from ...transport import HttpTransportMixin
from .llm_adapter import LLMAdapter, LLMRequest


@register_adapter("openai", "llm")
class OpenAILLMAdapter(LLMAdapter, HttpTransportMixin):
    """Wraps :class:`nexent.core.models.openai_llm.OpenAIModel`.

    Attributes:
        modality: ``"llm"``.
        factory: ``"openai"``.
    """

    factory = "openai"

    def __init__(self, context: LLMContext) -> None:
        LLMAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.timeout_seconds if context.timeout_seconds is not None else 30.0,
        )

    def _build_model(self) -> None:
        """Construct the wrapped :class:`OpenAIModel` on first use."""
        ctx = self._context
        kwargs = dict(
            observer=ctx.observer,
            model_id=ctx.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=ctx.display_name,
            timeout_seconds=ctx.timeout_seconds,
            extra_body=ctx.extra_body,
            max_output_tokens=ctx.max_output_tokens,
        )
        if ctx.temperature is not None:
            kwargs["temperature"] = ctx.temperature
        if ctx.top_p is not None:
            kwargs["top_p"] = ctx.top_p
        if ctx.stream is not None:
            kwargs["stream"] = ctx.stream
        self._model = OpenAIModel(**kwargs)

    async def invoke(self, request: LLMRequest) -> Any:
        """Return a smolagents ChatMessage, offloaded to a worker thread."""
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(
            self._model, request.messages, **request.kwargs
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[Any]:
        """Create a streaming completion using the wrapped OpenAI client."""
        if self._model is None:
            self._build_model()
        completion_kwargs = {
            "model": self._model.model_id,
            "messages": request.messages,
            "stream": True,
            **request.kwargs,
        }
        return await self._model.client.chat.completions.create(**completion_kwargs)

    async def health_check(self) -> bool:
        """Probe the wrapped model's connectivity.

        ``OpenAIModel.check_connectivity`` is itself a coroutine (it offloads
        the blocking SDK call to a thread internally), so it must be awaited
        directly — wrapping it in ``asyncio.to_thread`` would return the
        coroutine object un-awaited (truthy) and report success for every
        model, even one with an invalid API key.
        """
        if self._model is None:
            self._build_model()
        return await self._model.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` advertising text + tool_calling capabilities."""
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
    """Adapter for OpenAILongContextModel with long-context support.

    Reuses the standard OpenAI LLM adapter behavior and overrides only
    model construction and long-context metadata.

    Attributes:
        modality: ``"llm_long_context"`` (overrides the base ``"llm"``).
        factory: ``"openai"`` (inherited).
    """

    modality = "llm_long_context"

    def _build_model(self) -> None:
        """Construct the wrapped :class:`OpenAILongContextModel` on first use."""
        ctx = self._context
        self._model = OpenAILongContextModel(
            observer=ctx.observer,
            model_id=ctx.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            max_context_tokens=ctx.max_tokens if ctx.max_tokens is not None else 128000,
            truncation_strategy=ctx.truncation_strategy if ctx.truncation_strategy is not None else "start",
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=ctx.display_name,
            timeout_seconds=ctx.timeout_seconds,
            extra_body=ctx.extra_body,
            max_output_tokens=ctx.max_output_tokens,
        )

    def analyze_long_text(
        self,
        text_content: str,
        system_prompt: str,
        user_prompt: str,
    ):
        """Analyze long text via the wrapped long-context model.

        The gateway wrapper keeps the wrapped model unbuilt until first use,
        so build it lazily before delegating. ``AnalyzeTextFileTool`` calls
        this method directly on the adapter.

        Returns:
            tuple[ChatMessage, str]: Model response and truncation percentage.
        """
        if self._model is None:
            self._build_model()
        return self._model.analyze_long_text(
            text_content=text_content,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` advertising ``long_context=True``."""
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
