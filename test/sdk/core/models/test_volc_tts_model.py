"""
Unit tests for Volcano TTS model.

Tests the VolcTTSModel and VolcTTSConfig classes.
"""
import gzip
import io
import os
import pytest
import types
from unittest.mock import AsyncMock, MagicMock, patch

import sys as _sys

_models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../sdk/nexent/core/models"))
_core_dir = os.path.dirname(_models_dir)
_nexent_dir = os.path.dirname(_core_dir)

_sdk_nexent_pkg = types.ModuleType("sdk.nexent")
_sdk_nexent_pkg.__path__ = [_nexent_dir]
_sdk_nexent_core_pkg = types.ModuleType("sdk.nexent.core")
_sdk_nexent_core_pkg.__path__ = [_core_dir]
_sdk_nexent_models_pkg = types.ModuleType("sdk.nexent.core.models")
_sdk_nexent_models_pkg.__path__ = [_models_dir]

_sys.modules["sdk.nexent"] = _sdk_nexent_pkg
_sys.modules["sdk.nexent.core"] = _sdk_nexent_core_pkg
_sys.modules["sdk.nexent.core.models"] = _sdk_nexent_models_pkg

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

_mock_aiofiles = MagicMock()

_module_mocks = {
    "websockets": _mock_websockets,
    "aiofiles": _mock_aiofiles,
}

with patch.dict(_sys.modules, _module_mocks):
    from sdk.nexent.core.models.volc_tts_model import (
        VolcTTSModel,
        VolcTTSConfig,
        BaseTTSModel,
    )
    _volc_tts_module = _sys.modules[VolcTTSModel.__module__]

_volc_tts_module.websockets = _mock_websockets


class TestVolcTTSConfig:
    """Tests for VolcTTSConfig."""

    def test_config_init_default_values(self):
        """Test config initialization with default values."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        assert config.appid == "test_appid"
        assert config.token == "test_token"
        assert config.speed_ratio == 1.0
        assert config.ws_url == "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
        assert config.host == "openspeech.bytedance.com"
        assert config.encoding == "mp3"
        assert config.volume_ratio == 1.0
        assert config.pitch_ratio == 1.0
        assert config.cluster == "volcano_tts"
        assert config.resource_id == "seed-tts-2.0"
        assert config.voice_type == "zh_female_vv_uranus_bigtts"

    def test_config_init_custom_values(self):
        """Test config initialization with custom values."""
        config = VolcTTSConfig(
            appid="custom_appid",
            token="custom_token",
            speed_ratio=2.0,
            ws_url="wss://custom.url",
            host="custom.host.com",
            encoding="wav",
            volume_ratio=0.8,
            pitch_ratio=0.5,
            cluster="custom_cluster",
            resource_id="custom_resource",
            voice_type="custom_voice",
        )
        assert config.appid == "custom_appid"
        assert config.token == "custom_token"
        assert config.speed_ratio == 2.0
        assert config.ws_url == "wss://custom.url"
        assert config.host == "custom.host.com"
        assert config.encoding == "wav"
        assert config.volume_ratio == 0.8
        assert config.pitch_ratio == 0.5
        assert config.cluster == "custom_cluster"
        assert config.resource_id == "custom_resource"
        assert config.voice_type == "custom_voice"

    def test_api_url_property(self):
        """Test that api_url property returns ws_url."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        assert config.api_url == config.ws_url
        custom_ws_url = "wss://custom.tts.url"
        config.ws_url = custom_ws_url
        assert config.api_url == custom_ws_url


class TestVolcTTSModelProtocolConstants:
    """Tests for protocol constants."""

    def test_message_types(self):
        """Test MESSAGE_TYPES constant mapping."""
        assert VolcTTSModel.MESSAGE_TYPES == {
            11: "audio-only server response",
            12: "frontend server response",
            15: "error message from server",
        }

    def test_message_type_specific_flags(self):
        """Test MESSAGE_TYPE_SPECIFIC_FLAGS constant mapping."""
        assert VolcTTSModel.MESSAGE_TYPE_SPECIFIC_FLAGS == {
            0: "no sequence number",
            1: "sequence number > 0",
            2: "last message from server (seq < 0)",
            3: "sequence number < 0",
        }

    def test_message_serialization_methods(self):
        """Test MESSAGE_SERIALIZATION_METHODS constant mapping."""
        assert VolcTTSModel.MESSAGE_SERIALIZATION_METHODS == {
            0: "no serialization",
            1: "JSON",
            15: "custom type",
        }

    def test_message_compressions(self):
        """Test MESSAGE_COMPRESSIONS constant mapping."""
        assert VolcTTSModel.MESSAGE_COMPRESSIONS == {
            0: "no compression",
            1: "gzip",
            15: "custom compression method",
        }

    def test_default_header(self):
        """Test DEFAULT_HEADER constant value."""
        assert VolcTTSModel.DEFAULT_HEADER == bytearray([0x11, 0x10, 0x11, 0x00])


class TestVolcTTSModelHeaderGeneration:
    """Tests for header generation methods."""

    def test_get_websocket_url(self):
        """Test get_websocket_url returns config api_url."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        assert model.get_websocket_url() == config.api_url

    def test_get_websocket_url_custom(self):
        """Test get_websocket_url with custom ws_url."""
        custom_url = "wss://custom.tts.service/api/v1/tts/ws_binary"
        config = VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
            ws_url=custom_url,
        )
        model = VolcTTSModel(config)
        assert model.get_websocket_url() == custom_url


class TestVolcTTSModelAuthHeaders:
    """Tests for authentication headers."""

    def test_get_auth_headers(self):
        """Test get_auth_headers returns correct headers."""
        config = VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
            resource_id="test_resource",
        )
        model = VolcTTSModel(config)
        headers = model.get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer; test_token"
        assert "X-Api-App-Id" in headers
        assert headers["X-Api-App-Id"] == "test_appid"
        assert "X-Api-Access-Key" in headers
        assert headers["X-Api-Access-Key"] == "test_token"
        assert "X-Api-Resource-Id" in headers
        assert headers["X-Api-Resource-Id"] == "test_resource"

    def test_get_auth_headers_custom_values(self):
        """Test get_auth_headers with custom config values."""
        config = VolcTTSConfig(
            appid="custom_appid",
            token="custom_token",
            speed_ratio=1.0,
            resource_id="custom_resource_id",
        )
        model = VolcTTSModel(config)
        headers = model.get_auth_headers()
        assert headers["Authorization"] == "Bearer; custom_token"
        assert headers["X-Api-App-Id"] == "custom_appid"
        assert headers["X-Api-Access-Key"] == "custom_token"
        assert headers["X-Api-Resource-Id"] == "custom_resource_id"


class TestVolcTTSModelRequestPreparation:
    """Tests for request preparation."""

    def test_prepare_request_submit(self):
        """Test _prepare_request with default submit operation."""
        config = VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
            cluster="test_cluster",
            resource_id="test_resource",
            voice_type="test_voice",
            encoding="mp3",
            volume_ratio=1.0,
            pitch_ratio=1.0,
        )
        model = VolcTTSModel(config)
        request = model._prepare_request("Hello world")
        assert isinstance(request, bytes)
        assert len(request) > 0
        header = request[:4]
        assert header == bytes(VolcTTSModel.DEFAULT_HEADER)

    def test_prepare_request_custom_operation(self):
        """Test _prepare_request with custom operation."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        request = model._prepare_request("Test text", operation="custom_op")
        assert isinstance(request, bytes)
        assert len(request) > 0

    def test_prepare_request_gzip_compressed(self):
        """Test that request payload is gzip compressed."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        request = model._prepare_request("Test text")
        payload_length = int.from_bytes(request[4:8], "big")
        payload = request[8:]
        assert len(payload) == payload_length
        decompressed = gzip.decompress(payload)
        assert b"Test text" in decompressed

    def test_prepare_request_includes_uuid(self):
        """Test that request includes a UUID in reqid field."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        request1 = model._prepare_request("Hello")
        request2 = model._prepare_request("Hello")
        decompressed1 = gzip.decompress(request1[8:]).decode("utf-8")
        decompressed2 = gzip.decompress(request2[8:]).decode("utf-8")
        assert '"reqid"' in decompressed1
        assert '"reqid"' in decompressed2

    def test_prepare_request_structure(self):
        """Test request JSON structure contains required fields."""
        config = VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.5,
            cluster="my_cluster",
            resource_id="my_resource",
            voice_type="my_voice",
            encoding="wav",
            volume_ratio=0.8,
            pitch_ratio=0.9,
        )
        model = VolcTTSModel(config)
        request = model._prepare_request("Sample text")
        payload = gzip.decompress(request[8:]).decode("utf-8")
        import json
        parsed = json.loads(payload)
        assert "app" in parsed
        assert parsed["app"]["appid"] == "test_appid"
        assert parsed["app"]["token"] == "test_token"
        assert parsed["app"]["cluster"] == "my_cluster"
        assert parsed["app"]["resource_id"] == "my_resource"
        assert "user" in parsed
        assert "audio" in parsed
        assert parsed["audio"]["voice_type"] == "my_voice"
        assert parsed["audio"]["encoding"] == "wav"
        assert parsed["audio"]["speed_ratio"] == 1.5
        assert parsed["audio"]["volume_ratio"] == 0.8
        assert parsed["audio"]["pitch_ratio"] == 0.9
        assert "request" in parsed
        assert parsed["request"]["text"] == "Sample text"
        assert parsed["request"]["text_type"] == "plain"


class TestVolcTTSModelResponseParsing:
    """Tests for response parsing."""

    def _make_audio_response(self, message_type_specific_flags, sequence_number, audio_data=b"audio_chunk"):
        header = bytearray([
            0x10 | (message_type_specific_flags & 0x0f),
            0xb0 | 0x00,
            0x00,
            0x00,
        ])
        header[0] = (1 << 4) | 1
        header[1] = (0xb << 4) | message_type_specific_flags
        seq_bytes = sequence_number.to_bytes(4, "big", signed=True)
        header_size_bytes = len(seq_bytes) + len(audio_data) + 4
        header_size_prefix = header_size_bytes.to_bytes(4, "big")
        return bytes(header) + seq_bytes + header_size_prefix + audio_data

    def _make_response_bytes(self, byte0, byte1, payload_data):
        header = bytearray([byte0, byte1, 0x00, 0x00])
        return bytes(header) + payload_data

    def test_parse_response_audio_type_flag_0_no_seq(self):
        """Test parsing audio-only response with flag 0 (no sequence)."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        done, chunk = model._parse_response(bytes([0x10, 0xb0, 0x00, 0x00]) + b"\x00" * 8)
        assert done is False
        assert chunk is None

    def test_parse_response_audio_type_with_positive_sequence(self):
        """Test parsing audio-only response with positive sequence number."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes = (5).to_bytes(4, "big", signed=True)
        audio_data = b"test_audio_data"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload
        done, chunk = model._parse_response(response)
        assert done is False
        assert chunk == audio_data

    def test_parse_response_audio_type_with_negative_sequence(self):
        """Test parsing audio-only response with negative sequence number (last message)."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xb2, 0x00, 0x00])
        seq_bytes = (-1).to_bytes(4, "big", signed=True)
        audio_data = b"final_audio_chunk"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload
        done, chunk = model._parse_response(response)
        assert done is True
        assert chunk == audio_data

    def test_parse_response_audio_type_flag_3_negative_seq_with_num(self):
        """Test parsing audio-only response with flag 3 (sequence number < 0)."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xb3, 0x00, 0x00])
        seq_bytes = (-3).to_bytes(4, "big", signed=True)
        audio_data = b"chunk_data"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload
        done, chunk = model._parse_response(response)
        assert done is True
        assert chunk == audio_data

    def test_parse_response_audio_with_buffer(self):
        """Test that audio chunks are written to buffer."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        audio_data = b"buffered_audio"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload
        buffer = io.BytesIO()
        done, chunk = model._parse_response(response, buffer)
        assert done is False
        assert buffer.getvalue() == audio_data

    def test_parse_response_frontend_type(self):
        """Test parsing frontend server response (message type 0xc)."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xc0, 0x00, 0x00])
        response = bytes(header) + b"\x00" * 8
        done, chunk = model._parse_response(response)
        assert done is True
        assert chunk is None

    def test_parse_response_frontend_type_with_flags(self):
        """Test parsing frontend server response with various flags."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        for flag in [0, 1, 2, 3]:
            header = bytearray([0x11, (0xc << 4) | flag, 0x00, 0x00])
            response = bytes(header) + b"\x00" * 8
            done, chunk = model._parse_response(response)
            assert done is True

    def test_parse_response_error_type(self):
        """Test parsing error message from server (message type 0xf)."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xf0, 0x00, 0x00])
        code_bytes = (1001).to_bytes(4, "big", signed=False)
        error_msg = b"Test error message"
        payload = code_bytes + (len(error_msg)).to_bytes(4, "big") + error_msg
        response = bytes(header) + payload
        with pytest.raises(Exception, match="Volc TTS Error 1001"):
            model._parse_response(response)

    def test_parse_response_error_type_with_compression(self):
        """Test parsing error message with gzip compression."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xf0, 0x01, 0x00])
        code_bytes = (2000).to_bytes(4, "big", signed=False)
        error_msg = b"Compressed error"
        compressed_msg = gzip.compress(error_msg)
        payload = code_bytes + (len(compressed_msg)).to_bytes(4, "big") + compressed_msg
        response = bytes(header) + payload
        with pytest.raises(Exception, match="Volc TTS Error 2000"):
            model._parse_response(response)

    def test_parse_response_unknown_type(self):
        """Test parsing response with unknown message type returns done=True."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xd0, 0x00, 0x00])
        response = bytes(header) + b"\x00" * 8
        done, chunk = model._parse_response(response)
        assert done is True
        assert chunk is None

    def test_parse_response_header_extraction(self):
        """Test that protocol version and header size are correctly extracted."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        audio_data = b"test"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload
        done, chunk = model._parse_response(response)
        assert done is False


class TestVolcTTSModelGenerateSpeechNonStreaming:
    """Tests for non-streaming generate_speech."""

    @pytest.fixture
    def volc_config(self):
        return VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
        )

    @pytest.fixture
    def volc_model(self, volc_config):
        return VolcTTSModel(volc_config)

    def _make_audio_response_bytes(self, sequences, audio_chunks):
        responses = []
        for i, (seq, audio) in enumerate(zip(sequences, audio_chunks)):
            header = bytearray([0x11, 0xb0, 0x00, 0x00])
            header[1] = (0xb << 4) | 0x2
            seq_bytes = seq.to_bytes(4, "big", signed=True)
            payload = seq_bytes + (len(audio)).to_bytes(4, "big") + audio
            responses.append(bytes(header) + payload)
        return responses

    @pytest.mark.asyncio
    async def test_generate_speech_non_streaming_success(self, volc_model):
        """Test non-streaming generate_speech with successful response."""
        header = bytearray([0x11, 0xb2, 0x00, 0x00])
        seq_bytes = (-1).to_bytes(4, "big", signed=True)
        audio_data = b"final_audio_data"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await volc_model.generate_speech("Hello world", stream=False)
            assert isinstance(result, bytes)
            assert result == audio_data

    @pytest.mark.asyncio
    async def test_generate_speech_non_streaming_multiple_chunks(self, volc_model):
        """Test non-streaming generate_speech collecting multiple chunks into buffer."""
        header1 = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes1 = (1).to_bytes(4, "big", signed=True)
        audio1 = b"chunk1_"
        payload1 = seq_bytes1 + (len(audio1)).to_bytes(4, "big") + audio1
        resp1 = bytes(header1) + payload1

        header2 = bytearray([0x11, 0xb2, 0x00, 0x00])
        seq_bytes2 = (-1).to_bytes(4, "big", signed=True)
        audio2 = b"chunk2_final"
        payload2 = seq_bytes2 + (len(audio2)).to_bytes(4, "big") + audio2
        resp2 = bytes(header2) + payload2

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[resp1, resp2])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await volc_model.generate_speech("Hello world", stream=False)
            assert isinstance(result, bytes)
            assert result == b"chunk1_chunk2_final"

    @pytest.mark.asyncio
    async def test_generate_speech_non_streaming_connection_error(self, volc_model):
        """Test non-streaming generate_speech with connection error."""
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(Exception, match="Connection failed"):
                await volc_model.generate_speech("Hello", stream=False)


class TestVolcTTSModelGenerateSpeechStreaming:
    """Tests for streaming generate_speech."""

    @pytest.fixture
    def volc_config(self):
        return VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
        )

    @pytest.fixture
    def volc_model(self, volc_config):
        return VolcTTSModel(volc_config)

    @pytest.mark.asyncio
    async def test_generate_speech_streaming_success(self, volc_model):
        """Test streaming generate_speech yields audio chunks."""
        header1 = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes1 = (1).to_bytes(4, "big", signed=True)
        audio1 = b"stream_chunk_1"
        payload1 = seq_bytes1 + (len(audio1)).to_bytes(4, "big") + audio1
        resp1 = bytes(header1) + payload1

        header2 = bytearray([0x11, 0xb2, 0x00, 0x00])
        seq_bytes2 = (-1).to_bytes(4, "big", signed=True)
        audio2 = b"stream_chunk_2"
        payload2 = seq_bytes2 + (len(audio2)).to_bytes(4, "big") + audio2
        resp2 = bytes(header2) + payload2

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[resp1, resp2])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            generator = await volc_model.generate_speech("Hello world", stream=True)
            chunks = []
            async for chunk in generator:
                chunks.append(chunk)
            assert len(chunks) == 2
            assert chunks[0] == audio1
            assert chunks[1] == audio2

    def test_parse_response_no_sequence_flag(self, volc_model):
        """Test _parse_response with no sequence (flag 0) returns done=True, chunk=None.

        When message_type_specific_flags == 0, the parse returns (False, None)
        which causes done=True in streaming, ending the loop.
        """
        header = bytearray([0x11, 0xb0, 0x00, 0x00])
        response = bytes(header) + b"\x00" * 8

        done, chunk = volc_model._parse_response(response)
        assert done is False
        assert chunk is None

    @pytest.mark.asyncio
    async def test_generate_speech_streaming_connection_error(self, volc_model):
        """Test streaming generate_speech with connection error."""
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            generator = await volc_model.generate_speech("Hello", stream=True)
            chunks = []
            with pytest.raises(Exception, match="Connection failed"):
                async for chunk in generator:
                    chunks.append(chunk)

    @pytest.mark.asyncio
    async def test_generate_speech_streaming_error_response(self, volc_model):
        """Test streaming generate_speech handles error response."""
        header = bytearray([0x11, 0xf0, 0x00, 0x00])
        code_bytes = (3000).to_bytes(4, "big", signed=False)
        error_msg = b"Server error"
        payload = code_bytes + (len(error_msg)).to_bytes(4, "big") + error_msg
        response = bytes(header) + payload

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            generator = await volc_model.generate_speech("Hello", stream=True)
            with pytest.raises(Exception, match="Volc TTS Error 3000"):
                async for chunk in generator:
                    pass


class TestVolcTTSModelCheckConnectivity:
    """Tests for check_connectivity method."""

    @pytest.fixture
    def volc_config(self):
        return VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
        )

    @pytest.fixture
    def volc_model(self, volc_config):
        return VolcTTSModel(volc_config, audio_file_path="/test/audio.mp3")

    @pytest.mark.asyncio
    async def test_check_connectivity_success(self, volc_model):
        """Test check_connectivity returns True on successful audio generation."""
        header = bytearray([0x11, 0xb2, 0x00, 0x00])
        seq_bytes = (-1).to_bytes(4, "big", signed=True)
        audio_data = b"valid_audio_data"
        payload = seq_bytes + (len(audio_data)).to_bytes(4, "big") + audio_data
        response = bytes(header) + payload

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await volc_model.check_connectivity()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_empty_audio(self, volc_model):
        """Test check_connectivity returns False when audio is empty."""
        header = bytearray([0x11, 0xb0, 0x00, 0x00])
        response = bytes(header) + b"\x00" * 8

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await volc_model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_connection_error(self, volc_model):
        """Test check_connectivity returns False on connection error."""
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await volc_model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_no_audio_file_path(self):
        """Test check_connectivity with no audio_file_path (uses generate_speech)."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        header = bytearray([0x11, 0xb0, 0x00, 0x00])
        response = bytes(header) + b"\x00" * 8

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.check_connectivity()
            assert result is False


class TestVolcTTSModelBaseClassInheritance:
    """Tests for base class method inheritance."""

    def test_model_inherits_from_base_tts_model(self):
        """Test that VolcTTSModel inherits from BaseTTSModel."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        assert isinstance(model, BaseTTSModel)

    def test_is_tts_result_successful_bytes(self):
        """Test _is_tts_result_successful with bytes input."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        assert model._is_tts_result_successful(b"audio_data") is True
        assert model._is_tts_result_successful(b"") is False

    def test_is_tts_result_successful_dict(self):
        """Test _is_tts_result_successful with dict input."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        assert model._is_tts_result_successful({"audio": "data"}) is True
        assert model._is_tts_result_successful({"text": "result"}) is True
        assert model._is_tts_result_successful({"error": "fail"}) is False
        assert model._is_tts_result_successful({}) is False

    def test_is_tts_result_successful_invalid_types(self):
        """Test _is_tts_result_successful with invalid types."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        assert model._is_tts_result_successful("string") is False
        assert model._is_tts_result_successful(None) is False
        assert model._is_tts_result_successful(123) is False
        assert model._is_tts_result_successful([]) is False

    def test_extract_tts_error_message(self):
        """Test _extract_tts_error_message method."""
        config = VolcTTSConfig(appid="test_appid", token="test_token", speed_ratio=1.0)
        model = VolcTTSModel(config)
        assert model._extract_tts_error_message({"error": "test_error"}) == "test_error"
        assert model._extract_tts_error_message({"message": "msg_error"}) == "msg_error"
        result = model._extract_tts_error_message({"code": 500})
        assert "Unknown error" in result


class TestVolcTTSModelEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.fixture
    def volc_config(self):
        return VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
        )

    @pytest.fixture
    def volc_model(self, volc_config):
        return VolcTTSModel(volc_config)

    def test_parse_response_empty_payload(self, volc_model):
        """Test parsing response with empty payload after header."""
        header = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload = seq_bytes + (0).to_bytes(4, "big")
        response = bytes(header) + payload
        done, chunk = volc_model._parse_response(response)
        assert done is False
        assert chunk == b""

    def test_parse_response_very_large_audio_chunk(self, volc_model):
        """Test parsing response with large audio chunk."""
        header = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        large_audio = b"x" * 10000
        payload = seq_bytes + (len(large_audio)).to_bytes(4, "big") + large_audio
        response = bytes(header) + payload
        done, chunk = volc_model._parse_response(response)
        assert done is False
        assert chunk == large_audio

    def test_prepare_request_empty_text(self, volc_model):
        """Test _prepare_request with empty text."""
        request = volc_model._prepare_request("")
        assert isinstance(request, bytes)
        assert len(request) > 0

    def test_prepare_request_unicode_text(self, volc_model):
        """Test _prepare_request with unicode text."""
        unicode_text = "Hello world with unicode: \u4e2d\u6587 \u043f\u0440\u0438\u0432\u0435\u0442"
        request = volc_model._prepare_request(unicode_text)
        assert isinstance(request, bytes)
        payload = gzip.decompress(request[8:])
        payload_str = payload.decode("utf-8")
        assert "Hello world with unicode" in payload_str
        assert "\\u4e2d\\u6587" in payload_str or "中文" in payload_str
        assert "\\u043f\\u0440\\u0438\\u0432\\u0435\\u0442" in payload_str or "привет" in payload_str

    def test_prepare_request_long_text(self, volc_model):
        """Test _prepare_request with long text."""
        long_text = "A" * 10000
        request = volc_model._prepare_request(long_text)
        assert isinstance(request, bytes)
        assert len(request) > 0

    def test_config_cluster_and_resource_id(self):
        """Test config with cluster and resource_id fields."""
        config = VolcTTSConfig(
            appid="test_appid",
            token="test_token",
            speed_ratio=1.0,
            cluster="speech_tts",
            resource_id="my-tts-resource",
        )
        model = VolcTTSModel(config)
        headers = model.get_auth_headers()
        assert headers["X-Api-Resource-Id"] == "my-tts-resource"

    @pytest.mark.asyncio
    async def test_generate_speech_non_streaming_with_error_response(self, volc_model):
        """Test non-streaming generate_speech handles error response."""
        header = bytearray([0x11, 0xf0, 0x00, 0x00])
        code_bytes = (4000).to_bytes(4, "big", signed=False)
        error_msg = b"Server error occurred"
        payload = code_bytes + (len(error_msg)).to_bytes(4, "big") + error_msg
        response = bytes(header) + payload

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(Exception, match="Volc TTS Error 4000"):
                await volc_model.generate_speech("Hello", stream=False)

    @pytest.mark.asyncio
    async def test_generate_speech_streaming_frontend_response_stops(self, volc_model):
        """Test streaming stops when frontend response (type 0xc) is received."""
        header = bytearray([0x11, 0xc0, 0x00, 0x00])
        response = bytes(header) + b"\x00" * 8

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            generator = await volc_model.generate_speech("Hello", stream=True)
            chunks = []
            async for chunk in generator:
                chunks.append(chunk)
            assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_generate_speech_non_streaming_mixed_frontend_and_audio(self, volc_model):
        """Test non-streaming handles mix of audio and frontend responses."""
        header1 = bytearray([0x11, 0xb1, 0x00, 0x00])
        seq_bytes1 = (1).to_bytes(4, "big", signed=True)
        audio1 = b"audio_"
        payload1 = seq_bytes1 + (len(audio1)).to_bytes(4, "big") + audio1
        resp1 = bytes(header1) + payload1

        header2 = bytearray([0x11, 0xc0, 0x00, 0x00])
        resp2 = bytes(header2) + b"\x00" * 8

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[resp1, resp2])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await volc_model.generate_speech("Hello", stream=False)
            assert isinstance(result, bytes)
            assert result == audio1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
