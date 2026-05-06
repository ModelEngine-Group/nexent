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
)


class MockVoiceService:
    """Mock voice service for testing."""

    def __init__(self):
        self.start_stt_streaming_session = AsyncMock()
        self.check_voice_connectivity = AsyncMock(return_value=True)


from apps.voice_app import voice_runtime_router, voice_config_router


class TestVoiceApp:
    """Test cases for voice app endpoints."""

    def setup_method(self):
        """Set up test fixtures."""
        self.app = FastAPI()
        self.app.include_router(voice_runtime_router)
        self.app.include_router(voice_config_router)
        self.client = TestClient(self.app)

    def test_stt_websocket_success(self):
        """Test successful STT WebSocket connection."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_get_service.return_value = mock_service

            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                websocket.send_json({"model": "qwen3-asr-flash-realtime"})
                assert websocket is not None

            mock_service.start_stt_streaming_session.assert_called_once()

    def test_stt_websocket_bytes_config(self):
        """Test STT WebSocket with bytes message containing config."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_get_service.return_value = mock_service

            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                import json
                config_bytes = json.dumps({"model": "qwen3-asr-flash-realtime"}).encode('utf-8')
                websocket.send_bytes(config_bytes)
                assert websocket is not None

            mock_service.start_stt_streaming_session.assert_called_once()

    def test_stt_websocket_bytes_config_parse_error(self):
        """Test STT WebSocket with invalid bytes config."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_get_service.return_value = mock_service

            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                websocket.send_bytes(b"invalid json")
                assert websocket is not None

            mock_service.start_stt_streaming_session.assert_called_once()

    def test_stt_websocket_stt_connection_error(self):
        """Test STT WebSocket with STT connection error."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.start_stt_streaming_session.side_effect = STTConnectionException("STT connection failed")
            mock_get_service.return_value = mock_service

            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                websocket.send_json({"model": "qwen3-asr-flash-realtime"})
                data = websocket.receive_json()
                assert "error" in data
                assert "STT connection failed" in data["error"]

    def test_stt_websocket_general_error(self):
        """Test STT WebSocket with general error."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.start_stt_streaming_session.side_effect = Exception("General error")
            mock_get_service.return_value = mock_service

            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                websocket.send_json({"model": "qwen3-asr-flash-realtime"})
                data = websocket.receive_json()
                assert "error" in data
                assert "General error" in data["error"]

    def test_check_voice_connectivity_success(self):
        """Test successful voice connectivity check."""
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
        """Test voice connectivity check failure."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = MockVoiceService()
            mock_service.check_voice_connectivity.return_value = False
            mock_get_service.return_value = mock_service

            response = self.client.post(
                "/voice/connectivity",
                json={"model_type": "stt"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["connected"] is False
            assert data["model_type"] == "stt"
            assert "Service connection failed" in data["message"]

    def test_check_voice_connectivity_voice_service_error(self):
        """Test voice connectivity check with VoiceServiceException."""
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
        """Test voice connectivity check with STTConnectionException."""
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

    def test_check_voice_connectivity_unexpected_error(self):
        """Test voice connectivity check with unexpected error."""
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
        """Test voice connectivity check with missing model_type."""
        response = self.client.post(
            "/voice/connectivity",
            json={}
        )

        assert response.status_code == 422

    def test_check_voice_connectivity_invalid_json(self):
        """Test voice connectivity check with invalid JSON."""
        response = self.client.post(
            "/voice/connectivity",
            data="invalid json"
        )

        assert response.status_code == 422


class TestVoiceAppIntegration:
    """Integration tests for voice app with real service logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.app = FastAPI()
        self.app.include_router(voice_runtime_router)
        self.app.include_router(voice_config_router)
        self.client = TestClient(self.app)

    def test_voice_connectivity_real_logic_stt(self):
        """Test voice connectivity with real service logic for STT."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
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

            mock_service.check_voice_connectivity.assert_called_once_with("stt")

    def test_stt_websocket_real_logic(self):
        """Test STT WebSocket with real service logic."""
        with patch('apps.voice_app.get_voice_service') as mock_get_service:
            mock_service = Mock()
            mock_service.start_stt_streaming_session = AsyncMock()
            mock_get_service.return_value = mock_service

            with self.client.websocket_connect("/voice/stt/ws") as websocket:
                websocket.send_json({"model": "qwen3-asr-flash-realtime"})
                assert websocket is not None

            mock_service.start_stt_streaming_session.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
