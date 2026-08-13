"""LLM adapter — forwards to a wrapped OpenAIModel for smolagents compat."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List

from nexent.core.models import OpenAIModel, OpenAILongContextModel
from ...multimodal_adapter import ModelInfo, MultimodalAdapter
from ...model_context import LLMContext, LLMSampling
from ...registry import register_adapter
from ...transport import HttpTransportMixin


@dataclass
class LLMRequest:
    """Batch LLM request: messages plus forward kwargs.

    Attributes:
        messages: The conversation messages to send.
        kwargs: Per-call arguments forwarded to the wrapped model.
    """

    messages: List[Dict[str, Any]]
    kwargs: Dict[str, Any] = field(default_factory=dict)


class LLMAdapter(MultimodalAdapter):
    """LLM adapter root — the only modality that transparently forwards attributes.

    CoreAgent hands the adapter to smolagents as its ``model``; smolagents reaches
    for ``model.client`` / ``model.model_id`` / ``model.temperature`` /
    ``type(model).__name__`` as part of the Model contract. ``__call__`` is
    explicit (Python special methods bypass ``__getattr__``); every other
    attribute auto-forwards to ``_model``. This is contract compliance, not a
    bypass of the uniform interface.

    Attributes:
        modality: ``"llm"``.
        _model: The wrapped :class:`OpenAIModel` (or subclass), built lazily.
    """

    modality = "llm"

    def __init__(self, context: LLMContext) -> None:
        super().__init__(context)
        self._model: Any = None  # wrapped OpenAIModel, built lazily

    @abstractmethod
    async def invoke(self, request: LLMRequest) -> Any:
        """Return a smolagents ChatMessage for ``request.messages``.

        Args:
            request: The LLM request whose messages should be processed.

        Returns:
            A smolagents ``ChatMessage`` for ``request.messages``.
        """

    async def stream(self, request: LLMRequest) -> AsyncIterator[Any]:
        """Streaming is not supported by the LLM base adapter.

        Raises:
            NotImplementedError: Always; concrete subclasses override.
        """
        raise NotImplementedError(f"{self.modality} adapter does not support streaming")

    def __call__(self, messages: List[Dict[str, Any]], **kwargs) -> Any:
        """Forward ``__call__`` so CoreAgent can use the adapter as its model.

        Python special methods do not route through ``__getattr__``; attribute
        forwarding (``model.client`` / ``model.model_id`` / ...) is provided by
        :meth:`__getattr__`.

        Args:
            messages: The conversation messages to pass to the wrapped model.
            **kwargs: Additional arguments forwarded to the wrapped model.

        Returns:
            The wrapped model's output for the given messages.
        """
        if self._model is None:
            self._build_model()
        return self._model(messages, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attributes to the wrapped ``_model``.

        Satisfies the smolagents Model contract. ``_model`` and ``_context``
        are real instance attributes set in ``__init__``, so accessing them
        never recurses.

        Args:
            name: The attribute name to look up on the wrapped model.

        Returns:
            The value of ``name`` from the wrapped model.

        Raises:
            AttributeError: If the wrapped model does not expose ``name``.
        """
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        model = self.__dict__.get("_model")
        if model is not None:
            return getattr(model, name)
        raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")

    def _build_model(self) -> None:
        """Construct the wrapped model instance on first use."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement _build_model"
        )


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
        # Keep the existing OpenAIModel construction path so the adapter remains
        # compatible with smolagents and preserves existing model configuration.
        s = self._context.sampling or LLMSampling()
        kwargs = dict(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=self._context.timeout_seconds,
            extra_body=s.extra_body,
            max_output_tokens=s.max_output_tokens,
        )
        # Only override model defaults when the caller explicitly provides them.
        if s.temperature is not None:
            kwargs["temperature"] = s.temperature
        if s.top_p is not None:
            kwargs["top_p"] = s.top_p
        if s.stream is not None:
            kwargs["stream"] = s.stream
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
        """Probe the wrapped model's connectivity."""
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(self._model.check_connectivity)

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
        s = self._context.sampling or LLMSampling()
        self._model = OpenAILongContextModel(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            max_context_tokens=s.max_tokens if s.max_tokens is not None else 128000,
            truncation_strategy=s.truncation_strategy if s.truncation_strategy is not None else "start",
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=self._context.timeout_seconds,
            extra_body=s.extra_body,
            max_output_tokens=s.max_output_tokens,
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
