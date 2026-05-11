"""
Base TTS model interface for text-to-speech functionality.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union, AsyncGenerator


class BaseTTSModel(ABC):
    """
    Abstract base class for TTS (Text-to-Speech) models.

    All TTS implementations (e.g., Volcano Engine, Ali Cloud) must inherit from this class
    and implement the required abstract methods.
    """

    def __init__(self, audio_file_path: Optional[str] = None):
        """
        Initialize the base TTS model.

        Args:
            audio_file_path: Path to test audio file for connectivity testing
        """
        self.audio_file_path = audio_file_path

    @abstractmethod
    def get_websocket_url(self) -> str:
        """
        Get the WebSocket URL for the TTS service.

        Returns:
            WebSocket URL string
        """
        pass

    @abstractmethod
    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for the WebSocket connection.

        Returns:
            Headers dict with authentication information
        """
        pass

    @abstractmethod
    async def generate_speech(
        self,
        text: str,
        stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """
        Generate speech from text.

        Args:
            text: Input text to synthesize
            stream: If True, return an async generator of audio chunks.
                   If False, return complete audio bytes.

        Returns:
            Audio data either as complete bytes or streaming chunks
        """
        pass

    @abstractmethod
    async def check_connectivity(self) -> bool:
        """
        Test if the connection to the remote TTS service is normal.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    def _is_tts_result_successful(self, result: Any) -> bool:
        """
        Check if TTS result indicates a successful synthesis.

        Args:
            result: TTS processing result

        Returns:
            True if successful, False otherwise
        """
        if isinstance(result, bytes):
            return len(result) > 0
        if isinstance(result, dict):
            if 'error' in result:
                return False
            return 'audio' in result or 'text' in result or 'message' in result
        return False

    def _extract_tts_error_message(self, result: Any) -> str:
        """
        Extract error message from TTS result.

        Args:
            result: TTS processing result

        Returns:
            Error message string
        """
        if isinstance(result, dict):
            if 'error' in result:
                return str(result['error'])
            if 'message' in result:
                return str(result['message'])
        return f"Unknown error in result: {result}"
