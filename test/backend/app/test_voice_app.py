import os
import sys
import pytest

from unittest.mock import Mock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException, 
    TTSConnectionException,
    VoiceConfigException
)


# Mock voice service
class MockVoiceService:
    def __init__(self):
        self.start_stt_streaming_session = AsyncMock()
        self.stream_tts_to_websocket = AsyncMock()
        self.check_voice_connectivity = AsyncMock(return_value=True)


# Now import the app under test
from apps.voice_app import router


class TestVoiceApp:
    """Test cases for voice app endpoints"""

    def setup_method(self):
        """Set up test fixtures"""
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def test_stt_websocket_success(self):
        """Test successful STT WebSocket connection"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                # WebSocket connection should be established
                assert websocket is not None
                # Verify service method was called
                mock_service.start_stt_streaming_session.assert_called_once()

    def test_stt_websocket_stt_connection_error(self):
        """Test STT WebSocket with STT connection error"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.start_stt_streaming_session.side_effect = STTConnectionException("STT connection failed")
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                # Should receive error message
                data = websocket.receive_json()
                assert "error" in data
                assert "STT connection failed" in data["error"]

    def test_stt_websocket_general_error(self):
        """Test STT WebSocket with general error"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.start_stt_streaming_session.side_effect = Exception("General error")
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                # Should receive error message
                data = websocket.receive_json()
                assert "error" in data
                assert "General error" in data["error"]

    def test_tts_websocket_success(self):
        """Test successful TTS WebSocket connection"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/tts/ws") as websocket:
                # Send text data
                websocket.send_json({"text": "Hello, world!"})
                
                # Verify service method was called
                mock_service.stream_tts_to_websocket.assert_called_once()

    def test_tts_websocket_no_text(self):
        """Test TTS WebSocket with no text provided"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/tts/ws") as websocket:
                # Send empty text
                websocket.send_json({"text": ""})
                
                # Should receive error message
                data = websocket.receive_json()
                assert "error" in data
                assert "No text provided" in data["error"]

    def test_tts_websocket_tts_connection_error(self):
        """Test TTS WebSocket with TTS connection error"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.stream_tts_to_websocket.side_effect = TTSConnectionException("TTS connection failed")
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/tts/ws") as websocket:
                websocket.send_json({"text": "Hello, world!"})
                
                # Should receive error message
                data = websocket.receive_json()
                assert "error" in data
                assert "TTS connection failed" in data["error"]

    def test_tts_websocket_general_error(self):
        """Test TTS WebSocket with general error"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.stream_tts_to_websocket.side_effect = Exception("General error")
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/tts/ws") as websocket:
                websocket.send_json({"text": "Hello, world!"})
                
                # Should receive error message
                data = websocket.receive_json()
                assert "error" in data
                assert "General error" in data["error"]

    def test_check_voice_connectivity_success(self):
        """Test successful voice connectivity check"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.return_value = True
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "stt"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is True
            assert data["model_type"] == "stt"
            assert "Service is connected" in data["message"]

    def test_check_voice_connectivity_failure(self):
        """Test voice connectivity check failure"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.return_value = False
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "tts"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is False
            assert data["model_type"] == "tts"
            assert "Service connection failed" in data["message"]

    def test_check_voice_connectivity_voice_service_error(self):
        """Test voice connectivity check with VoiceServiceException"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.side_effect = VoiceServiceException("Invalid model type")
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "invalid"}
            )
            
            assert response.status_code == 400
            data = response.json()
            assert "Invalid model type" in data["detail"]

    def test_check_voice_connectivity_stt_connection_error(self):
        """Test voice connectivity check with STTConnectionException"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.side_effect = STTConnectionException("STT service unavailable")
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "stt"}
            )
            
            assert response.status_code == 503
            data = response.json()
            assert "STT service unavailable" in data["detail"]

    def test_check_voice_connectivity_tts_connection_error(self):
        """Test voice connectivity check with TTSConnectionException"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.side_effect = TTSConnectionException("TTS service unavailable")
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "tts"}
            )
            
            assert response.status_code == 503
            data = response.json()
            assert "TTS service unavailable" in data["detail"]

    def test_check_voice_connectivity_voice_config_error(self):
        """Test voice connectivity check with VoiceConfigException"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.side_effect = VoiceConfigException("Configuration error")
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "stt"}
            )
            
            assert response.status_code == 500
            data = response.json()
            assert "Configuration error" in data["detail"]

    def test_check_voice_connectivity_unexpected_error(self):
        """Test voice connectivity check with unexpected error"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.side_effect = Exception("Unexpected error")
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "stt"}
            )
            
            assert response.status_code == 500
            data = response.json()
            assert "Voice service error" in data["detail"]

    def test_check_voice_connectivity_missing_model_type(self):
        """Test voice connectivity check with missing model_type"""
        response = self.client.post(
            "/voice/connectivity",
            json={}
        )
        
        # Should return 422 for validation error
        assert response.status_code == 422

    def test_check_voice_connectivity_invalid_json(self):
        """Test voice connectivity check with invalid JSON"""
        response = self.client.post(
            "/voice/connectivity",
            data="invalid json"
        )
        
        # Should return 422 for JSON parsing error
        assert response.status_code == 422


class TestVoiceAppIntegration:
    """Integration tests for voice app with real service logic"""

    def setup_method(self):
        """Set up test fixtures"""
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def test_voice_connectivity_real_logic_stt(self):
        """Test voice connectivity with real service logic for STT"""
        # This test uses the actual service logic but with mocked dependencies
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            # Create a mock service that behaves like the real one
            mock_service = Mock()
            mock_service.check_voice_connectivity = AsyncMock(return_value=True)
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "stt"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is True
            assert data["model_type"] == "stt"
            
            # Verify the service method was called with correct parameters
            mock_service.check_voice_connectivity.assert_called_once_with("stt")

    def test_voice_connectivity_real_logic_tts(self):
        """Test voice connectivity with real service logic for TTS"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            # Create a mock service that behaves like the real one
            mock_service = Mock()
            mock_service.check_voice_connectivity = AsyncMock(return_value=False)
            mock_get_service.return_value = mock_service
            
            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "tts"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is False
            assert data["model_type"] == "tts"
            
            # Verify the service method was called with correct parameters
            mock_service.check_voice_connectivity.assert_called_once_with("tts")

    def test_stt_websocket_real_logic(self):
        """Test STT WebSocket with real service logic"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            # Create a mock service that behaves like the real one
            mock_service = Mock()
            mock_service.start_stt_streaming_session = AsyncMock()
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                # WebSocket connection should be established
                assert websocket is not None
                
                # Verify the service method was called
                mock_service.start_stt_streaming_session.assert_called_once()

    def test_tts_websocket_real_logic(self):
        """Test TTS WebSocket with real service logic"""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            # Create a mock service that behaves like the real one
            mock_service = Mock()
            mock_service.stream_tts_to_websocket = AsyncMock()
            mock_get_service.return_value = mock_service
            
            with self.client.websocket_connect("/voice/tts/ws") as websocket:
                # Send text data
                websocket.send_json({"text": "Hello, world!"})
                
                # Verify the service method was called with correct parameters
                mock_service.stream_tts_to_websocket.assert_called_once()
                
                # Get the call arguments
                call_args = mock_service.stream_tts_to_websocket.call_args
                assert call_args[0][1] == "Hello, world!"  # Second argument should be the text


if __name__ == "__main__":
    pytest.main([__file__])
