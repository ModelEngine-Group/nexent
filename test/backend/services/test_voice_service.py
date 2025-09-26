import os
import sys
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
    TTSConnectionException,
    VoiceConfigException
)


# Mock only the external dependencies that we need to control
class MockSTTModel:
    def __init__(self, config, test_path):
        self.config = config
        self.test_path = test_path
        self.check_connectivity = AsyncMock(return_value=True)
        self.start_streaming_session = AsyncMock()


class MockTTSModel:
    def __init__(self, config):
        self.config = config
        self.check_connectivity = AsyncMock(return_value=True)
    
    async def generate_speech(self, text: str, stream: bool = False):
        """Mock implementation that returns appropriate data based on stream parameter"""
        if stream:
            # Return an async generator for streaming
            async def mock_audio_generator():
                yield b"mock_audio_chunk_1"
                yield b"mock_audio_chunk_2"
                yield b"mock_audio_chunk_3"
            return mock_audio_generator()
        else:
            # Return complete audio bytes for non-streaming
            return b"mock_complete_audio_data"


# Import the service under test
from services.voice_service import VoiceService, get_voice_service
import services.voice_service


def mock_voice_dependencies(func):
    """Decorator to apply all necessary mocks for voice service tests"""
    @patch('services.voice_service.TTSModel', MockTTSModel)
    @patch('services.voice_service.STTModel', MockSTTModel)
    @patch('consts.const.TEST_VOICE_PATH', '/test/path')
    @patch('consts.const.SPEED_RATIO', 1.0)
    @patch('consts.const.VOICE_TYPE', 'test_voice_type')
    @patch('consts.const.CLUSTER', 'test_cluster')
    @patch('consts.const.TOKEN', 'test_token')
    @patch('consts.const.APPID', 'test_appid')
    def wrapper(*args, **kwargs):
        # Reset the global voice service instance to ensure test isolation
        services.voice_service._voice_service_instance = None
        return func(*args, **kwargs)
    return wrapper


class TestVoiceService:
    """Test cases for VoiceService class"""

    @mock_voice_dependencies
    def test_start_stt_streaming_session_success(self):
        """Test successful STT streaming session start"""
        service = VoiceService()
        
        # Mock the STT model's start_streaming_session method
        service.stt_model.start_streaming_session = AsyncMock()
        
        # Mock WebSocket
        mock_websocket = Mock()
        
        # Test the method
        asyncio.run(service.start_stt_streaming_session(mock_websocket))
        
        # Verify the method was called
        service.stt_model.start_streaming_session.assert_called_once_with(mock_websocket)

    @mock_voice_dependencies
    def test_start_stt_streaming_session_stt_connection_error(self):
        """Test STT streaming session with STT connection error"""
        service = VoiceService()
        
        # Mock the STT model to raise STTConnectionException
        service.stt_model.start_streaming_session = AsyncMock(
            side_effect=STTConnectionException("STT connection failed")
        )
        
        # Mock WebSocket
        mock_websocket = Mock()
        
        # Test the method should raise the exception
        with pytest.raises(STTConnectionException):
            asyncio.run(service.start_stt_streaming_session(mock_websocket))

    @mock_voice_dependencies
    def test_start_stt_streaming_session_general_error(self):
        """Test STT streaming session with general error"""
        service = VoiceService()
        
        # Mock the STT model to raise a general exception
        service.stt_model.start_streaming_session = AsyncMock(
            side_effect=Exception("General error")
        )
        
        # Mock WebSocket
        mock_websocket = Mock()
        
        # Test the method should raise STTConnectionException (not VoiceServiceException)
        with pytest.raises(STTConnectionException):
            asyncio.run(service.start_stt_streaming_session(mock_websocket))

    @mock_voice_dependencies
    def test_generate_tts_speech_success(self):
        """Test successful TTS speech generation"""
        service = VoiceService()
        
        # Mock the TTS model's generate_speech method
        service.tts_model.generate_speech = AsyncMock(return_value=b"audio_data")
        
        # Test the method
        result = asyncio.run(service.generate_tts_speech("Hello, world!", stream=False))
        
        # Verify the method was called with correct parameters
        service.tts_model.generate_speech.assert_called_once_with("Hello, world!", stream=False)
        assert result == b"audio_data"

    @mock_voice_dependencies
    def test_generate_tts_speech_empty_text(self):
        """Test TTS speech generation with empty text"""
        service = VoiceService()
        
        # Test with empty text
        with pytest.raises(VoiceServiceException, match="No text provided for TTS generation"):
            asyncio.run(service.generate_tts_speech("", stream=False))
        
        # Test with None text
        with pytest.raises(VoiceServiceException, match="No text provided for TTS generation"):
            asyncio.run(service.generate_tts_speech(None, stream=False))

    @mock_voice_dependencies
    def test_generate_tts_speech_tts_connection_error(self):
        """Test TTS speech generation with TTS connection error"""
        service = VoiceService()
        
        # Mock the TTS model to raise TTSConnectionException
        service.tts_model.generate_speech = AsyncMock(
            side_effect=TTSConnectionException("TTS connection failed")
        )
        
        # Test the method should raise the exception
        with pytest.raises(TTSConnectionException):
            asyncio.run(service.generate_tts_speech("Hello, world!", stream=False))

    @mock_voice_dependencies
    def test_generate_tts_speech_general_error(self):
        """Test TTS speech generation with general error"""
        service = VoiceService()
        
        # Mock the TTS model to raise a general exception
        service.tts_model.generate_speech = AsyncMock(
            side_effect=Exception("General error")
        )
        
        # Test the method should raise TTSConnectionException
        with pytest.raises(TTSConnectionException):
            asyncio.run(service.generate_tts_speech("Hello, world!", stream=False))

    @mock_voice_dependencies
    def test_stream_tts_to_websocket_success(self):
        """Test successful TTS streaming to WebSocket"""
        service = VoiceService()
        
        # Mock the TTS model's generate_speech method directly to avoid real WebSocket connections
        async def mock_generate_speech(text: str, stream: bool = False):
            if stream:
                async def mock_audio_generator():
                    yield b"mock_audio_chunk_1"
                    yield b"mock_audio_chunk_2"
                    yield b"mock_audio_chunk_3"
                return mock_audio_generator()
            else:
                return b"mock_complete_audio_data"
        
        service.tts_model.generate_speech = mock_generate_speech
        
        # Mock WebSocket with client_state
        mock_websocket = Mock()
        mock_websocket.send_bytes = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.close = AsyncMock()
        
        # Mock client_state to be CONNECTED
        mock_client_state = Mock()
        mock_client_state.name = "CONNECTED"
        mock_websocket.client_state = mock_client_state
        
        # Test the method
        asyncio.run(service.stream_tts_to_websocket(mock_websocket, "Hello, world!"))
        
        assert mock_websocket.send_bytes.call_count == 3
        mock_websocket.send_json.assert_called_once_with({"status": "completed"})

    @mock_voice_dependencies
    def test_stream_tts_to_websocket_tts_connection_error(self):
        """Test TTS streaming to WebSocket with TTS connection error"""
        service = VoiceService()
        
        # Mock the TTS model to raise TTSConnectionException
        async def mock_generate_speech(text, stream=True):
            raise TTSConnectionException("TTS connection failed")
        
        service.tts_model.generate_speech = mock_generate_speech
        
        # Mock WebSocket
        mock_websocket = Mock()
        mock_websocket.send_bytes = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.close = AsyncMock()
        
        # Mock client_state
        mock_client_state = Mock()
        mock_client_state.name = "CONNECTED"
        mock_websocket.client_state = mock_client_state
        
        # Test the method should raise the exception
        with pytest.raises(TTSConnectionException):
            asyncio.run(service.stream_tts_to_websocket(mock_websocket, "Hello, world!"))

    @mock_voice_dependencies
    def test_stream_tts_to_websocket_general_error(self):
        """Test TTS streaming to WebSocket with general error"""
        service = VoiceService()
        
        # Mock the TTS model to raise a general exception
        async def mock_generate_speech(text, stream=True):
            raise Exception("General error")
        
        service.tts_model.generate_speech = mock_generate_speech
        
        # Mock WebSocket
        mock_websocket = Mock()
        mock_websocket.send_bytes = AsyncMock()
        mock_websocket.send_json = AsyncMock()
        mock_websocket.close = AsyncMock()
        
        # Mock client_state
        mock_client_state = Mock()
        mock_client_state.name = "CONNECTED"
        mock_websocket.client_state = mock_client_state
        
        # Test the method should raise TTSConnectionException
        with pytest.raises(TTSConnectionException):
            asyncio.run(service.stream_tts_to_websocket(mock_websocket, "Hello, world!"))

    @mock_voice_dependencies
    def test_check_voice_connectivity_stt_success(self):
        """Test voice connectivity check for STT model"""
        service = VoiceService()
        
        # Mock the STT model's check_connectivity method
        service.stt_model.check_connectivity = AsyncMock(return_value=True)
        service.tts_model.check_connectivity = AsyncMock(return_value=True)
        
        # Test STT connectivity
        result = asyncio.run(service.check_voice_connectivity("stt"))
        
        # Verify the method was called
        service.stt_model.check_connectivity.assert_called_once()
        assert result is True

    @mock_voice_dependencies
    def test_check_voice_connectivity_tts_success(self):
        """Test voice connectivity check for TTS model"""
        service = VoiceService()
        
        # Mock the TTS model's check_connectivity method
        service.stt_model.check_connectivity = AsyncMock(return_value=True)
        service.tts_model.check_connectivity = AsyncMock(return_value=True)
        
        # Test TTS connectivity
        result = asyncio.run(service.check_voice_connectivity("tts"))
        
        # Verify the method was called
        service.tts_model.check_connectivity.assert_called_once()
        assert result is True

    @mock_voice_dependencies
    def test_check_voice_connectivity_stt_failure(self):
        """Test voice connectivity check for STT model failure"""
        service = VoiceService()
        
        # Mock the STT model's check_connectivity method to return False
        service.stt_model.check_connectivity = AsyncMock(return_value=False)
        service.tts_model.check_connectivity = AsyncMock(return_value=True)
        
        # Test STT connectivity should raise STTConnectionException
        with pytest.raises(STTConnectionException):
            asyncio.run(service.check_voice_connectivity("stt"))
        
        # Verify the method was called
        service.stt_model.check_connectivity.assert_called_once()

    @mock_voice_dependencies
    def test_check_voice_connectivity_tts_failure(self):
        """Test voice connectivity check for TTS model failure"""
        service = VoiceService()
        
        # Mock the TTS model's check_connectivity method to return False
        service.stt_model.check_connectivity = AsyncMock(return_value=True)
        service.tts_model.check_connectivity = AsyncMock(return_value=False)
        
        # Test TTS connectivity should raise TTSConnectionException
        with pytest.raises(TTSConnectionException):
            asyncio.run(service.check_voice_connectivity("tts"))
        
        # Verify the method was called
        service.tts_model.check_connectivity.assert_called_once()

    @mock_voice_dependencies
    def test_check_voice_connectivity_invalid_model_type(self):
        """Test voice connectivity check with invalid model type"""
        service = VoiceService()
        
        # Test with invalid model type
        with pytest.raises(VoiceServiceException, match="Unknown model type"):
            asyncio.run(service.check_voice_connectivity("invalid"))

    @mock_voice_dependencies
    def test_check_voice_connectivity_stt_connection_error(self):
        """Test voice connectivity check with STT connection error"""
        service = VoiceService()
        
        # Mock the STT model to raise STTConnectionException
        service.stt_model.check_connectivity = AsyncMock(
            side_effect=STTConnectionException("STT connection failed")
        )
        
        # Test the method should raise the exception
        with pytest.raises(STTConnectionException):
            asyncio.run(service.check_voice_connectivity("stt"))

    @mock_voice_dependencies
    def test_check_voice_connectivity_tts_connection_error(self):
        """Test voice connectivity check with TTS connection error"""
        service = VoiceService()
        
        # Mock the TTS model to raise TTSConnectionException
        service.tts_model.check_connectivity = AsyncMock(
            side_effect=TTSConnectionException("TTS connection failed")
        )
        
        # Test the method should raise the exception
        with pytest.raises(TTSConnectionException):
            asyncio.run(service.check_voice_connectivity("tts"))

    @mock_voice_dependencies
    def test_check_voice_connectivity_general_error(self):
        """Test voice connectivity check with general error"""
        service = VoiceService()
        
        # Mock the STT model to raise a general exception
        service.stt_model.check_connectivity = AsyncMock(
            side_effect=Exception("General error")
        )
        
        # Test the method should raise STTConnectionException
        with pytest.raises(STTConnectionException):
            asyncio.run(service.check_voice_connectivity("stt"))


class TestVoiceServiceSingleton:
    """Test cases for VoiceService singleton pattern"""

    @mock_voice_dependencies
    def test_get_voice_service_singleton(self):
        """Test that get_voice_service returns a singleton instance"""
        # Get the service instance
        service1 = get_voice_service()
        service2 = get_voice_service()
        
        # Verify it's the same instance
        assert service1 is service2
        assert isinstance(service1, VoiceService)

    @mock_voice_dependencies
    def test_get_voice_service_initialization_error(self):
        """Test get_voice_service with initialization error"""
        # Reset the global instance to ensure we test the initialization path
        services.voice_service._voice_service_instance = None
        
        # Mock VoiceService constructor to raise an exception during initialization
        with patch.object(VoiceService, '__init__', side_effect=VoiceConfigException("Config error")):
            with pytest.raises(VoiceConfigException):
                get_voice_service()


if __name__ == "__main__":
    pytest.main([__file__])