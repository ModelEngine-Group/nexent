"""Multimodal adapter root ABC and model capability declaration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict

from .model_context import ModelContext


@dataclass
class ModelInfo:
    """Model capability declaration, replacing hardcoded URL sniffing.

    Attributes:
        model_id: The model identifier passed to the provider API.
        display_name: Human-readable name shown in the UI.
        provider: The normalized factory name (e.g. ``"openai"``).
        capabilities: Per-capability flags, e.g. ``{"image": True,
            "audio": False, "video": True}``.
    """

    model_id: str
    display_name: str
    provider: str
    capabilities: Dict[str, bool]


class MultimodalAdapter(ABC):
    """Root interface for every modality adapter.

    Subclasses set the class-level ``modality`` (``"llm"`` | ``"vlm"`` |
    ``"stt"`` | ``"tts"`` | ``"embedding"`` | ``"rerank"`` | ...) and
    ``factory`` (``"openai"`` | ``"ali"`` | ``"volc"`` | ...), then implement
    :meth:`invoke`, :meth:`health_check`, :meth:`get_model_info`.

    The root carries no wrapped-model state. Callers reach the model only
    through the uniform interface above - never by tunnelling into a wrapped
    instance's attributes.
    """

    modality: str
    factory: str

    def __init__(self, context: ModelContext) -> None:
        """Stores the construction context for the adapter.

        Args:
            context: The unified construction context for this adapter.
        """
        self._context = context

    @abstractmethod
    async def invoke(self, request: Any) -> Any:
        """Batch/synchronous entry point.

        LLM/VLM return a ChatMessage, Embedding returns a list of vectors,
        Rerank returns a list of dicts, TTS returns audio bytes, and STT
        returns a transcription dict.

        Args:
            request: The modality-specific request payload.

        Returns:
            The modality-specific response.
        """
        raise NotImplementedError

    async def stream(self, request: Any) -> AsyncIterator[Any]:
        """Streaming entry point.

        STT/TTS override this as an async generator.

        Args:
            request: The modality-specific request payload.

        Yields:
            Modality-specific stream chunks.

        Raises:
            NotImplementedError: If the adapter does not support streaming.
        """
        raise NotImplementedError(
            f"{self.modality} adapter does not support streaming"
        )

    @abstractmethod
    async def health_check(self) -> bool:
        """Unified health check.

        Replaces the three legacy method names (``check_connectivity`` /
        ``dimension_check`` / ``connectivity_check``).

        Returns:
            True if the model is reachable, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def get_model_info(self) -> ModelInfo:
        """Returns the capability declaration.

        Replaces analyze_audio_tool's ``getattr`` + URL sniffing.

        Returns:
            The model's capability declaration.
        """
        raise NotImplementedError
