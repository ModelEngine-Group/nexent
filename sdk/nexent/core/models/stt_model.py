"""
Base STT model interface for speech-to-text functionality.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseSTTModel(ABC):
    """
    Abstract base class for STT (Speech-to-Text) models.
    
    All STT implementations (e.g., Volcano Engine, Ali Cloud) must inherit from this class
    and implement the required abstract methods.
    """

    def __init__(self, audio_file_path: Optional[str] = None):
        """
        Initialize the base STT model.
        
        Args:
            audio_file_path: Path to test audio file for connectivity testing
        """
        self.audio_file_path = audio_file_path

    @abstractmethod
    def get_websocket_url(self) -> str:
        """
        Get the WebSocket URL for the STT service.
        
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
    async def recognize_file(self, audio_path: str) -> Dict[str, Any]:
        """
        Recognize speech from audio file.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Recognition result dict containing 'text' or 'error' key
        """
        pass

    @abstractmethod
    async def check_connectivity(self) -> bool:
        """
        Test if the connection to the remote STT service is normal.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def start_streaming_session(self, websocket) -> None:
        """
        Start a streaming session for real-time STT.
        
        Args:
            websocket: Client WebSocket connection
            
        Returns:
            None
        """
        pass

    def _is_stt_result_successful(self, result: Any) -> bool:
        """
        Check if STT result indicates a successful recognition.
        
        Args:
            result: STT processing result
            
        Returns:
            True if successful, False otherwise
        """
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
        """
        Extract error message from STT result.
        
        Args:
            result: STT processing result
            
        Returns:
            Error message string
        """
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
