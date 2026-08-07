"""Adapter root ABC and model capability declaration.

Adapters *compose* (do not inherit) the existing, stable model classes — they
hold a reference to a wrapped instance (``_inner``) and forward calls. This
keeps ``OpenAIVLModel``/``AliSTTModel`` etc. untouched and test-covered.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict

from .context import ModelContext


@dataclass
class ModelInfo:
    """Model capability declaration, replacing hardcoded URL sniffing."""

    model_id: str
    display_name: str
    provider: str
    capabilities: Dict[str, bool]  # e.g. {"image": True, "audio": False, "video": True}


class MultimodalAdapter(ABC):
    """Root interface for every modality adapter.

    Subclasses set the class-level ``modality`` (``"llm"`` | ``"vlm"`` | ``"stt"``
    | ``"tts"`` | ``"embedding"`` | ``"rerank"`` | ``"realtime"`` | ...) and
    ``factory`` (``"openai"`` | ``"ali"`` | ``"volc"`` | ...), then implement
    :meth:`invoke`, :meth:`health_check`, :meth:`get_model_info`.
    """

    modality: str
    factory: str

    def __init__(self, context: ModelContext) -> None:
        self._context = context
        self._inner: Any = None  # wrapped existing model instance (lazy)

    @abstractmethod
    async def invoke(self, request: Any) -> Any:
        """Batch/synchronous entry point.

        LLM/VLM → ChatMessage, Embedding → List[vec], Rerank → List[dict],
        TTS → bytes, STT → Dict[str, Any].
        """
        raise NotImplementedError

    async def stream(self, request: Any) -> AsyncIterator[Any]:
        """Streaming entry point. STT/TTS/Realtime override as AsyncGenerator."""
        raise NotImplementedError(
            f"{self.modality} adapter does not support streaming"
        )

    @abstractmethod
    async def health_check(self) -> bool:
        """Unified health check, replacing the three legacy method names
        (``check_connectivity`` / ``dimension_check`` / ``connectivity_check``)."""
        raise NotImplementedError

    @abstractmethod
    def get_model_info(self) -> ModelInfo:
        """Return capability declaration, replacing analyze_audio_tool's
        ``getattr`` + URL sniffing."""
        raise NotImplementedError

    @property
    def info(self) -> dict:
        return {
            "modality": self.modality,
            "factory": self.factory,
            "model_name": self._context.model_name,
        }

    def _build_inner(self) -> None:
        """Construct the wrapped existing-model instance on first use.

        Subclasses override to instantiate their vendor/model class per its
        real constructor signature, reading from :attr:`_context`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _build_inner"
        )
