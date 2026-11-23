"""LLM adapter root: request types + the transparent forward-to-model base."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List

from ...model_context import LLMContext
from ...multimodal_adapter import MultimodalAdapter


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
