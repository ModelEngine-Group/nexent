"""LLM adapter.

LLM is the CoreAgent primary reasoning model. smolagents reaches it through
``model.__call__()`` / ``model.client`` / ``model.model_id`` / ``model.temperature``
etc. Because ``__call__`` is a Python special method it bypasses
``__getattr__`` and must be forwarded explicitly; every other attribute is
auto-forwarded to ``_model`` via ``__getattr__`` for zero-maintenance smolagents
compat (new attributes added upstream keep working).

LLM is the *only* modality that keeps ``__getattr__`` — it is contract
compliance (smolagents treats the adapter as its Model), not a bypass of the
uniform :meth:`invoke` / :meth:`stream` interface.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List

from ...openai_llm import OpenAIModel
from ...openai_long_context_model import OpenAILongContextModel
from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin


@dataclass
class LLMRequest:
    """Batch LLM request: messages plus forward kwargs.

    Holds the conversation ``messages`` and the per-call forwarding ``kwargs``
    for an LLM invocation.
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
    """

    modality = "llm"

    def __init__(self, context: ModelContext) -> None:
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
        """Construct the wrapped existing-model instance on first use.

        Subclasses override to instantiate their vendor/model class per its
        real constructor signature, reading from :attr:`_context`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _build_model"
        )


@register_adapter("openai", "llm")
class OpenAILLMAdapter(LLMAdapter, HttpTransportMixin):
    """Wraps :class:`nexent.core.models.openai_llm.OpenAIModel`."""

    factory = "openai"

    def __init__(self, context: ModelContext) -> None:
        LLMAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )

    def _build_model(self) -> None:
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
        self._model = OpenAIModel(**kwargs)

    async def invoke(self, request: LLMRequest) -> Any:
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(
            self._model, request.messages, **request.kwargs
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[Any]:
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
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(self._model.check_connectivity)

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
    from :class:`OpenAILLMAdapter` unchanged; only ``_build_model`` and
    ``modality`` / capability differ.
    """

    modality = "llm_long_context"

    def _build_model(self) -> None:
        extras = self._context.extra
        self._model = OpenAILongContextModel(
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
