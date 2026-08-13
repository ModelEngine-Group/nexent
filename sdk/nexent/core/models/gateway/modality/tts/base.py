"""TTS adapter root, request type, and shared result helpers."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from ...multimodal_adapter import MultimodalAdapter

@dataclass
class TTSRequest:
    """TTS request: synthesize ``text`` to audio.

    ``stream`` selects streaming vs. non-streaming output; ``voice`` and
    ``speed_ratio`` optionally tune the synthesis.

    Attributes:
        text: The text to synthesize.
        stream: Whether to yield audio chunks as they are generated.
        voice: Optional voice id override.
        speed_ratio: Speech rate multiplier (1.0 = normal).
    """

    text: str
    stream: bool = False
    voice: Optional[str] = None
    speed_ratio: float = 1.0


class TTSAdapter(MultimodalAdapter):
    """TTS adapter root; carries shared result-inspection helpers for concrete adapters.

    Attributes:
        modality: ``"tts"``.
    """

    modality = "tts"

    @abstractmethod
    async def invoke(self, request: TTSRequest) -> bytes:
        """Synthesize the full audio for a request.

        Args:
            request: The TTS request to synthesize.

        Returns:
            The complete audio as bytes.
        """

    @abstractmethod
    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """Synthesize speech as a stream of audio chunks.

        Args:
            request: The TTS request to synthesize.

        Yields:
            Audio chunks as they are generated.
        """

    def _is_tts_result_successful(self, result: Any) -> bool:
        """Check whether a TTS result indicates successful synthesis.

        Args:
            result: The TTS result to inspect.

        Returns:
            True if the result represents synthesized audio.
        """
        if isinstance(result, bytes):
            return len(result) > 0
        if isinstance(result, dict):
            if 'error' in result:
                return False
            return 'audio' in result or 'text' in result or 'message' in result
        return False

    def _extract_tts_error_message(self, result: Any) -> str:
        """Extract an error message from a TTS result.

        Args:
            result: The TTS result to inspect.

        Returns:
            The error message string, or a fallback message if none is found.
        """
        if isinstance(result, dict):
            if 'error' in result:
                return str(result['error'])
            if 'message' in result:
                return str(result['message'])
        return f"Unknown error in result: {result}"

