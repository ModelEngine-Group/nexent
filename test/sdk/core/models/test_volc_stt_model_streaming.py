"""
Unit tests for Volcano STT model streaming session methods.
These tests were added to improve coverage for process_streaming_audio and start_streaming_session.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import sys as _sys

_mock_websockets = MagicMock()
_mock_websockets.connect = MagicMock()
_mock_websockets.exceptions = MagicMock()


class _MockConnectionClosedError(Exception):
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
        super().__init__(reason)


_mock_websockets.exceptions.ConnectionClosedError = _MockConnectionClosedError
_mock_websockets.exceptions.WebSocketException = Exception
_mock_websockets.exceptions.ConnectionClosed = _MockConnectionClosedError


_module_mocks = {
    "websockets": _mock_websockets,
}

with patch.dict(_sys.modules, _module_mocks):
    from sdk.nexent.core.models.volc_stt_model import (
        VolcSTTModel,
        VolcSTTConfig,
    )


class TestVolcSTTModelStreamingSession:
    """Tests for streaming session methods."""

    @pytest.fixture
    def volc_config(self):
        config = VolcSTTConfig(appid="test_appid", access_token="test_token")
        return config

    @pytest.fixture
    def volc_model(self, volc_config):
        return VolcSTTModel(volc_config, "/path/to/test/audio.pcm")

    @pytest.mark.asyncio
    async def test_start_streaming_session_success(self, volc_model):
        """Test start_streaming_session successful initialization."""
        mock_ws_client = AsyncMock()
        mock_ws_client.send_json = AsyncMock()

        header = bytearray([0x11, 0xB0, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload_size_bytes = (8).to_bytes(4, "big", signed=False)
        response_data = bytes(header) + seq_bytes + payload_size_bytes + b"\x00" * 8

        mock_ws_server = AsyncMock()
        mock_ws_server.send = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            response_data,
            response_data,
            _MockConnectionClosedError(1000, "Closed")
        ])
        mock_ws_server.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_exception(self, volc_model):
        """Test start_streaming_session when process_streaming_audio raises exception."""
        mock_ws_client = AsyncMock()
        mock_ws_client.send_json = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_process_streaming_audio_client_disconnect_early(self, volc_model):
        """Test process_streaming_audio when client disconnects immediately."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            _MockConnectionClosedError(1000, "Client closed")
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.send = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            Exception("Server disconnected")
        ])
        mock_ws_server.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.process_streaming_audio(mock_ws_client, 1000)

    @pytest.mark.asyncio
    async def test_process_streaming_audio_empty_audio(self, volc_model):
        """Test process_streaming_audio with empty audio data."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"",  # Empty audio indicates end of stream
            _MockConnectionClosedError(1000, "Client closed")
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.send = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            _MockConnectionClosedError(1000, "Server closed")
        ])
        mock_ws_server.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.process_streaming_audio(mock_ws_client, 1000)

    @pytest.mark.asyncio
    async def test_process_streaming_audio_exception(self, volc_model):
        """Test process_streaming_audio when connection raises exception."""
        mock_ws_client = AsyncMock()
        mock_ws_client.send_json = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.process_streaming_audio(mock_ws_client, 1000)

    @pytest.mark.asyncio
    async def test_process_streaming_audio_server_connection_closed(self, volc_model):
        """Test process_streaming_audio when server connection is closed."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            _MockConnectionClosedError(1000, "Client closed")
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.send = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            _MockConnectionClosedError(1000, "Server closed")
        ])
        mock_ws_server.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.process_streaming_audio(mock_ws_client, 1000)

    @pytest.mark.asyncio
    async def test_process_streaming_audio_send_exception(self, volc_model):
        """Test process_streaming_audio when send to server fails."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            _MockConnectionClosedError(1000, "Client closed")
        ])
        mock_ws_client.send_json = AsyncMock()

        header = bytearray([0x11, 0xB0, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload_size_bytes = (8).to_bytes(4, "big", signed=False)
        response_data = bytes(header) + seq_bytes + payload_size_bytes + b"\x00" * 8

        mock_ws_server = AsyncMock()
        mock_ws_server.send = AsyncMock(side_effect=Exception("Send failed"))
        mock_ws_server.recv = AsyncMock(side_effect=[
            response_data,
            _MockConnectionClosedError(1000, "Server closed")
        ])
        mock_ws_server.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            await volc_model.process_streaming_audio(mock_ws_client, 1000)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
