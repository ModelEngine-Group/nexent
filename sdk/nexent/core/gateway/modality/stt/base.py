"""STT adapter root, request types, and shared result container."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from ...multimodal_adapter import MultimodalAdapter

@dataclass
class STTRequest:
    """Batch STT request: transcribe a whole audio file.

    Attributes:
        audio_path: Path to the audio file to transcribe.
    """

    audio_path: str


@dataclass
class STTStreamRequest:
    """Real-time STT request over an existing websocket.

    Attributes:
        websocket: The client websocket to receive audio from and send results to.
        config_received: Ali-specific flag (ignored by Volc).
    """

    websocket: Any
    config_received: bool = True  # Ali-specific; ignored by Volc


class STTAdapter(MultimodalAdapter):
    """STT adapter root; carries shared result-inspection helpers for concrete adapters.

    Attributes:
        modality: ``"stt"``.
    """

    modality = "stt"

    @abstractmethod
    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        """Transcribe an audio file to text.

        Args:
            request: The STT request containing the audio file path.

        Returns:
            A dict shaped ``{"text": ..., "raw": ...}``.
        """

    @abstractmethod
    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        """Stream real-time transcription over the client websocket.

        Args:
            request: The streaming STT request carrying the client websocket.
        """

    def _is_stt_result_successful(self, result: Any) -> bool:
        """Check if STT result indicates a successful recognition."""
        if not isinstance(result, dict) or not result:
            return False

        if 'error' in result:
            return False

        if 'code' in result and result['code'] != 1000:
            return False

        if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
            if 'error' in result['payload_msg']:
                return False

        return True

    def _extract_stt_error_message(self, result: Any) -> str:
        """Extract error message from STT result."""
        if not isinstance(result, dict):
            return f"Invalid result type: {type(result)}"

        if 'error' in result:
            return str(result['error'])

        if 'code' in result and result['code'] != 1000:
            error_msg = f"STT service error code: {result['code']}"
            if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
                if 'error' in result['payload_msg']:
                    error_msg += f" - {result['payload_msg']['error']}"
            return error_msg

        if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
            if 'error' in result['payload_msg']:
                return str(result['payload_msg']['error'])

        return f"Unknown error in result: {result}"


class TranscriptionResult:
    """Container for transcription results.

    Attributes:
        text: Accumulated transcription text.
        is_final: Whether the final result has been received.
        error: Optional error message.
        vad: Optional VAD event marker.
    """

    def __init__(self):
        self.text: str = ""
        self.is_final: bool = False
        self.error: Optional[str] = None
        self.vad: Optional[str] = None

