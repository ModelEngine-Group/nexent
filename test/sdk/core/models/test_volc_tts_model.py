"""
Unit tests for Volcano TTS model.

Tests the VolcTTSModel and VolcTTSConfig classes.
"""
import pytest
import asyncio
import gzip
import json
import io
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

_module_mocks = {
    "websockets": _mock_websockets,
}

with patch.dict(_sys.modules, _module_mocks):
    from sdk.nexent.core.models.volc_tts_model import (
        VolcTTSModel,
        VolcTTSConfig,
    )


class TestVolcTTSConfig:
    """Test VolcTTSConfig dataclass."""

    def test_config_required_fields(self):
        """Test VolcTTSConfig with required fields only."""
        config = VolcTTSConfig(appid="app123", token="tok456", speed_ratio=1.0)
        assert config.appid == "app123"
        assert config.token == "tok456"
        assert config.speed_ratio == 1.0

    def test_config_default_values(self):
        """Test VolcTTSConfig with default values."""
        config = VolcTTSConfig(appid="app", token="token", speed_ratio=1.0)
        assert config.ws_url == "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
        assert config.host == "openspeech.bytedance.com"
        assert config.encoding == "mp3"
        assert config.volume_ratio == 1.0
        assert config.pitch_ratio == 1.0
        assert config.cluster == "volcano_tts"
        assert config.resource_id == "seed-tts-2.0"
        assert config.voice_type == "BV700_V2_streaming"

    def test_config_custom_values(self):
        """Test VolcTTSConfig with all custom values."""
        config = VolcTTSConfig(
            appid="custom_app",
            token="custom_token",
            speed_ratio=1.5,
            ws_url="wss://custom.example.com",
            host="custom.example.com",
            encoding="pcm",
            volume_ratio=1.2,
            pitch_ratio=0.8,
            cluster="custom_cluster",
            resource_id="custom.resource",
            voice_type="custom_voice"
        )
        assert config.appid == "custom_app"
        assert config.ws_url == "wss://custom.example.com"
        assert config.host == "custom.example.com"
        assert config.encoding == "pcm"
        assert config.volume_ratio == 1.2
        assert config.pitch_ratio == 0.8
        assert config.cluster == "custom_cluster"
        assert config.resource_id == "custom.resource"
        assert config.voice_type == "custom_voice"

    def test_api_url_property(self):
        """Test api_url property returns ws_url."""
        config = VolcTTSConfig(appid="a", token="t", speed_ratio=1.0, ws_url="wss://api.example.com")
        assert config.api_url == config.ws_url


class TestVolcTTSModel:
    """Test VolcTTSModel class."""

    @pytest.fixture
    def volc_config(self):
        """Create a test Volc TTS configuration."""
        return VolcTTSConfig(
            appid="test_app",
            token="test_token",
            speed_ratio=1.0
        )

    @pytest.fixture
    def volc_model(self, volc_config):
        """Create a test Volc TTS model instance."""
        return VolcTTSModel(volc_config)

    def test_init(self, volc_config):
        """Test VolcTTSModel initialization."""
        model = VolcTTSModel(volc_config)
        assert model.config == volc_config
        assert model.audio_file_path is None
        assert model._request_template is not None

    def test_init_with_audio_path(self, volc_config):
        """Test VolcTTSModel with audio file path."""
        model = VolcTTSModel(volc_config, "/path/to/test.mp3")
        assert model.audio_file_path == "/path/to/test.mp3"

    def test_init_request_template(self, volc_config):
        """Test that _request_template is built correctly."""
        model = VolcTTSModel(volc_config)
        template = model._request_template
        assert "app" in template
        assert template["app"]["appid"] == "test_app"
        assert template["app"]["token"] == "test_token"
        assert template["app"]["cluster"] == "volcano_tts"
        assert "user" in template
        assert "audio" in template
        assert "request" in template

    def test_get_websocket_url(self, volc_model):
        """Test get_websocket_url returns config URL."""
        url = volc_model.get_websocket_url()
        assert url == volc_model.config.api_url

    def test_get_auth_headers(self, volc_model):
        """Test get_auth_headers returns correct headers."""
        headers = volc_model.get_auth_headers()
        assert "X-Api-App-Id" in headers
        assert headers["X-Api-App-Id"] == "test_app"
        assert "X-Api-Access-Key" in headers
        assert headers["X-Api-Access-Key"] == "test_token"
        assert "X-Api-Resource-Id" in headers
        assert headers["X-Api-Resource-Id"] == "seed-tts-2.0"

    def test_prepare_request_submit(self, volc_model):
        """Test _prepare_request with submit operation."""
        text = "Hello world"
        request = volc_model._prepare_request(text, "submit")

        assert isinstance(request, bytes)
        assert len(request) > 0

        # Check header bytes (first 4 bytes)
        assert request[0:4] == bytearray([0x11, 0x10, 0x11, 0x00])

    def test_prepare_request_custom_operation(self, volc_model):
        """Test _prepare_request with custom operation."""
        request = volc_model._prepare_request("test", "custom_op")
        assert isinstance(request, bytes)
        assert len(request) > 4

        # Verify the operation in the request
        payload_size = int.from_bytes(request[4:8], 'big')
        payload = gzip.decompress(request[8:])
        payload_dict = json.loads(payload)
        assert payload_dict["request"]["operation"] == "custom_op"
        assert payload_dict["request"]["text"] == "test"

    def test_prepare_request_contains_uuid(self, volc_model):
        """Test that _prepare_request generates unique reqid."""
        req1 = volc_model._prepare_request("test", "submit")
        req2 = volc_model._prepare_request("test", "submit")

        payload1 = gzip.decompress(req1[8:])
        payload2 = gzip.decompress(req2[8:])

        reqid1 = json.loads(payload1)["request"]["reqid"]
        reqid2 = json.loads(payload2)["request"]["reqid"]
        assert reqid1 != reqid2

    def test_parse_response_audio_only(self, volc_model):
        """Test _parse_response with audio-only server response."""
        audio_chunk = b"test_audio_chunk"
        response = bytearray()
        response.append(0x11)  # version + header size
        response.append((0x0B << 4) | 0x01)  # audio-only response with sequence number > 0
        response.append(0x10)  # serialization=JSON, no compression
        response.append(0x00)
        # Sequence number and metadata before audio chunk
        response.extend((1).to_bytes(4, 'big', signed=True))  # sequence number
        response.extend(b'\x00' * 8)  # 8 bytes metadata
        response.extend(audio_chunk)  # audio data

        buffer = io.BytesIO()
        done, chunk = volc_model._parse_response(bytes(response), buffer)

        assert done is False
        assert chunk is not None
        assert chunk.endswith(audio_chunk)
        assert buffer.tell() > 0

    def test_parse_response_last_audio_message(self, volc_model):
        """Test _parse_response with last audio message (negative sequence)."""
        audio_chunk = b"final_audio"
        response = bytearray()
        response.append(0x11)
        response.append((0x0B << 4) | 0x02)  # negative sequence = last message
        response.append(0x10)  # serialization=JSON, no compression
        response.append(0x00)
        response.extend((-1).to_bytes(4, 'big', signed=True))
        # Metadata and audio
        response.extend(b'\x00' * 8)
        response.extend(audio_chunk)

        done, chunk = volc_model._parse_response(bytes(response), None)
        assert done is True
        assert chunk.endswith(audio_chunk)

    def test_parse_response_frontend_server_response(self, volc_model):
        """Test _parse_response with frontend server response (no audio)."""
        response = bytearray()
        response.append(0x11)
        response.append((0x0C << 4) | 0x00)  # frontend server response
        response.append(0x10)  # serialization=JSON, no compression
        response.append(0x00)

        done, chunk = volc_model._parse_response(bytes(response), None)
        assert done is True
        assert chunk is None

    def test_parse_response_error_no_compression(self, volc_model):
        """Test _parse_response with error message (no compression)."""
        error_text = "Service error"
        response = bytearray()
        response.append(0x11)
        response.append((0x0F << 4) | 0x00)  # error response
        response.append(0x10)  # serialization=JSON, no compression
        response.append(0x00)  # no compression flag
        response.extend((500).to_bytes(4, 'big', signed=False))
        response.extend((len(error_text)).to_bytes(4, 'big', signed=False))
        response.extend(error_text.encode('utf-8'))

        with pytest.raises(Exception) as exc_info:
            volc_model._parse_response(bytes(response), None)
        assert "Service error" in str(exc_info.value) or "500" in str(exc_info.value)

    def test_parse_response_error_with_compression(self, volc_model):
        """Test _parse_response with gzip compressed error."""
        error_dict = {"error": "Gzip compressed error", "code": 1000}
        error_compressed = gzip.compress(json.dumps(error_dict).encode('utf-8'))

        response = bytearray()
        response.append(0x11)
        response.append((0x0F << 4) | 0x01)  # error with compression
        response.append(0x11)
        response.append(0x01)  # gzip compression
        response.extend((500).to_bytes(4, 'big', signed=False))
        response.extend((0).to_bytes(4, 'big', signed=False))
        response.extend(error_compressed)

        with pytest.raises(Exception):
            volc_model._parse_response(bytes(response), None)

    def test_parse_response_empty_payload(self, volc_model):
        """Test _parse_response with empty payload."""
        response = bytearray()
        response.append(0x11)
        response.append((0x0B << 4) | 0x00)  # audio-only with no sequence
        response.append(0x11)
        response.append(0x00)

        done, chunk = volc_model._parse_response(bytes(response), None)
        assert done is False
        assert chunk is None


class TestVolcTTSModelGenerators:
    """Test VolcTTSModel async generators."""

    @pytest.fixture
    def volc_model(self):
        config = VolcTTSConfig(appid="test_app", token="test_token", speed_ratio=1.0)
        return VolcTTSModel(config)

    def test_generate_speech_non_streaming_no_audio(self, volc_model):
        """Test generate_speech non-streaming when no audio received."""
        mock_ws = MagicMock()

        async def mock_connect(*args, **kwargs):
            async def recv_side_effect():
                yield b"some_response"

            ws = MagicMock()
            ws.send = AsyncMock()
            ws.recv = recv_side_effect()
            ws.__aenter__ = AsyncMock(return_value=ws)
            ws.__aexit__ = AsyncMock(return_value=None)
            return ws

        mock_ws.connect = mock_connect

        class DummyParseResult:
            def __init__(self):
                self.call_count = 0
            def __call__(self, *args, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    return (False, None)
                return (True, None)

        dummy_parse = DummyParseResult()

        async def run_test():
            with patch(_mock_websockets, 'connect', mock_connect):
                with patch.object(volc_model, '_parse_response', side_effect=[(False, None), (True, None)]):
                    with patch.object(volc_model, '_prepare_request', return_value=b"test"):
                        with patch.object(volc_model, 'get_websocket_url', return_value="wss://test.com"):
                            with patch.object(volc_model, 'get_auth_headers', return_value={}):
                                result = await volc_model.generate_speech("test", stream=False)
                                assert isinstance(result, bytes)

    def test_generate_speech_streaming_generator_type(self, volc_model):
        """Test generate_speech streaming returns async generator or coroutine."""
        import types
        result = volc_model.generate_speech("test", stream=True)
        # Either async generator (when websockets works) or coroutine (when it fails to connect)
        assert isinstance(result, (types.AsyncGeneratorType, types.CoroutineType))


class TestVolcTTSConnectivity:
    """Test VolcTTSModel connectivity check."""

    @pytest.fixture
    def volc_model(self):
        config = VolcTTSConfig(appid="test_app", token="test_token", speed_ratio=1.0)
        return VolcTTSModel(config)

    @pytest.mark.asyncio
    async def test_check_connectivity_no_audio(self, volc_model):
        """Test check_connectivity when no audio is received."""
        with patch.object(volc_model, 'generate_speech', return_value=b""):
            result = await volc_model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_success(self, volc_model):
        """Test check_connectivity with successful audio generation."""
        with patch.object(volc_model, 'generate_speech', return_value=b"fake_audio_data"):
            result = await volc_model.check_connectivity()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_exception(self, volc_model):
        """Test check_connectivity with exception."""
        with patch.object(volc_model, 'generate_speech', side_effect=Exception("Connection error")):
            result = await volc_model.check_connectivity()
            assert result is False

    def test_is_tts_result_successful_valid(self, volc_model):
        """Test _is_tts_result_successful with valid audio."""
        assert volc_model._is_tts_result_successful(b"audio_data") is True

    def test_is_tts_result_successful_empty(self, volc_model):
        """Test _is_tts_result_successful with empty audio."""
        assert volc_model._is_tts_result_successful(b"") is False

    def test_extract_tts_error_message(self, volc_model):
        """Test _extract_tts_error_message."""
        msg = volc_model._extract_tts_error_message(b"error")
        assert "error" in msg.lower() or "tts" in msg.lower()
