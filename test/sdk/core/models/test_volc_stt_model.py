"""
Unit tests for Volcano STT model.

Tests the VolcSTTModel and VolcSTTConfig classes.
"""
import pytest
import asyncio
import gzip
import json
from io import BytesIO
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

_mock_aiofiles = MagicMock()


class _MockAsyncContextManager:
    def __init__(self, mock_file):
        self.mock_file = mock_file

    async def __aenter__(self):
        return self.mock_file

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def _mock_aiofiles_open(*args, **kwargs):
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"mock_data")
    return _MockAsyncContextManager(mock_file)


_mock_aiofiles.open = _mock_aiofiles_open

_module_mocks = {
    "websockets": _mock_websockets,
    "aiofiles": _mock_aiofiles,
}

with patch.dict(_sys.modules, _module_mocks):
    from sdk.nexent.core.models.volc_stt_model import (
        VolcSTTModel,
        VolcSTTConfig,
        PROTOCOL_VERSION,
        DEFAULT_HEADER_SIZE,
        CLIENT_FULL_REQUEST,
        CLIENT_AUDIO_ONLY_REQUEST,
        SERVER_FULL_RESPONSE,
        SERVER_ACK,
        SERVER_ERROR_RESPONSE,
        NO_SEQUENCE,
        POS_SEQUENCE,
        NEG_SEQUENCE,
        NEG_WITH_SEQUENCE,
        JSON,
        GZIP,
        NO_COMPRESSION,
        wave,
        websockets,
        aiofiles,
    )


class TestVolcSTTConfig:
    """Tests for VolcSTTConfig."""

    def test_config_init_default_values(self):
        """Test config initialization with default values."""
        config = VolcSTTConfig(appid="test_appid", access_token="test_token")
        assert config.appid == "test_appid"
        assert config.access_token == "test_token"
        assert config.ws_url == "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
        assert config.uid == "streaming_asr_demo"
        assert config.format == "pcm"
        assert config.rate == 16000
        assert config.bits == 16
        assert config.channel == 1
        assert config.codec == "raw"
        assert config.seg_duration == 10
        assert config.mp3_seg_size == 1000
        assert config.resourceid == "volc.bigasr.sauc.duration"
        assert config.streaming is True
        assert config.compression is True

    def test_config_init_custom_values(self):
        """Test config initialization with custom values."""
        config = VolcSTTConfig(
            appid="custom_appid",
            access_token="custom_token",
            ws_url="wss://custom.url",
            uid="custom_uid",
            format="wav",
            rate=8000,
            bits=8,
            channel=2,
            codec="mp3",
            seg_duration=20,
            mp3_seg_size=2000,
            resourceid="custom.resource",
            streaming=False,
            compression=False,
        )
        assert config.appid == "custom_appid"
        assert config.access_token == "custom_token"
        assert config.ws_url == "wss://custom.url"
        assert config.uid == "custom_uid"
        assert config.format == "wav"
        assert config.rate == 8000
        assert config.bits == 8
        assert config.channel == 2
        assert config.codec == "mp3"
        assert config.seg_duration == 20
        assert config.mp3_seg_size == 2000
        assert config.resourceid == "custom.resource"
        assert config.streaming is False
        assert config.compression is False


class TestVolcSTTModelProtocolConstants:
    """Tests for protocol constants."""

    def test_protocol_version(self):
        """Test protocol version constant."""
        assert PROTOCOL_VERSION == 0b0001

    def test_default_header_size(self):
        """Test default header size constant."""
        assert DEFAULT_HEADER_SIZE == 0b0001

    def test_client_message_types(self):
        """Test client message type constants."""
        assert CLIENT_FULL_REQUEST == 0b0001
        assert CLIENT_AUDIO_ONLY_REQUEST == 0b0010

    def test_server_message_types(self):
        """Test server message type constants."""
        assert SERVER_FULL_RESPONSE == 0b1001
        assert SERVER_ACK == 0b1011
        assert SERVER_ERROR_RESPONSE == 0b1111

    def test_message_type_specific_flags(self):
        """Test message type specific flag constants."""
        assert NO_SEQUENCE == 0b0000
        assert POS_SEQUENCE == 0b0001
        assert NEG_SEQUENCE == 0b0010
        assert NEG_WITH_SEQUENCE == 0b0011

    def test_message_serialization(self):
        """Test message serialization constants."""
        assert JSON == 0b0001

    def test_message_compression(self):
        """Test message compression constants."""
        assert GZIP == 0b0001
        assert NO_COMPRESSION == 0b0000


class TestVolcSTTModelHeaderGeneration:
    """Tests for header generation methods."""

    def test_generate_header_default(self):
        """Test header generation with default parameters."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = model.generate_header()
        assert len(header) == 4
        assert (header[0] >> 4) == PROTOCOL_VERSION
        assert (header[0] & 0x0f) == DEFAULT_HEADER_SIZE
        assert (header[1] >> 4) == CLIENT_FULL_REQUEST

    def test_generate_header_custom_message_type(self):
        """Test header generation with custom message type."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = model.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST)
        assert (header[1] >> 4) == CLIENT_AUDIO_ONLY_REQUEST

    def test_generate_header_no_compression(self):
        """Test header generation without compression."""
        config = VolcSTTConfig(appid="test", access_token="test", compression=False)
        model = VolcSTTModel(config)
        header = model.generate_header()
        compression_type = header[2] & 0x0f
        assert compression_type == NO_COMPRESSION

    def test_generate_header_with_compression(self):
        """Test header generation with compression enabled."""
        config = VolcSTTConfig(appid="test", access_token="test", compression=True)
        model = VolcSTTModel(config)
        header = model.generate_header()
        compression_type = header[2] & 0x0f
        assert compression_type == GZIP

    def test_generate_header_custom_flags(self):
        """Test header generation with custom flags."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = model.generate_header(message_type_specific_flags=POS_SEQUENCE)
        flags = header[1] & 0x0f
        assert flags == POS_SEQUENCE


class TestVolcSTTModelBeforePayload:
    """Tests for before_payload generation."""

    def test_generate_before_payload_positive(self):
        """Test payload prefix generation with positive sequence."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        prefix = model.generate_before_payload(sequence=5)
        assert len(prefix) == 4
        assert int.from_bytes(prefix, "big", signed=True) == 5

    def test_generate_before_payload_negative(self):
        """Test payload prefix generation with negative sequence."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        prefix = model.generate_before_payload(sequence=-10)
        assert len(prefix) == 4
        assert int.from_bytes(prefix, "big", signed=True) == -10


class TestVolcSTTModelResponseParsing:
    """Tests for response parsing."""

    def test_parse_response_server_ack(self):
        """Test parsing SERVER_ACK response."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = bytearray([0x11, 0xB0, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload_size_bytes = (8).to_bytes(4, "big", signed=False)
        extra_data = b"\x00" * 8
        response = bytes(header) + seq_bytes + payload_size_bytes + extra_data
        result = model.parse_response(response)
        assert result["seq"] == 1

    def test_parse_response_server_full_response_with_sequence(self):
        """Test parsing SERVER_FULL_RESPONSE with sequence flag."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = bytearray([0x11, 0x91, 0x11, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload_size_bytes = (len(b'{"result":{"text":"hello"}}')).to_bytes(4, "big", signed=False)
        payload = gzip.compress(b'{"result":{"text":"hello"}}')
        response = bytes(header) + seq_bytes + payload_size_bytes + payload
        result = model.parse_response(response)
        assert result["payload_sequence"] == 1
        assert "is_last_package" in result

    def test_parse_response_server_error(self):
        """Test parsing SERVER_ERROR_RESPONSE."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = bytearray([0x11, 0xF0, 0x00, 0x00])
        code_bytes = (1001).to_bytes(4, "big", signed=False)
        payload_size_bytes = (8).to_bytes(4, "big", signed=False)
        extra_data = b"\x00" * 8
        response = bytes(header) + code_bytes + payload_size_bytes + extra_data
        result = model.parse_response(response)
        assert result["code"] == 1001

    def test_parse_response_unknown_message_type(self):
        """Test parsing response with unknown message type."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        header = bytearray([0x11, 0x00, 0x10, 0x00])
        response = bytes(header)
        result = model.parse_response(response)
        assert result["is_last_package"] is False


class TestVolcSTTModelWavProcessing:
    """Tests for WAV file processing."""

    def test_read_wav_info(self):
        """Test reading WAV file information."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        buffer = BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)
        wav_data = buffer.getvalue()
        nchannels, sampwidth, framerate, nframes, wave_bytes = model.read_wav_info(wav_data)
        assert nchannels == 1
        assert sampwidth == 2
        assert framerate == 16000
        assert nframes == 16000

    def test_slice_data(self):
        """Test data slicing."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        data = b"0123456789"
        chunks = list(model.slice_data(data, 3))
        assert len(chunks) == 4
        assert chunks[0] == (b"012", False)
        assert chunks[1] == (b"345", False)
        assert chunks[2] == (b"678", False)
        assert chunks[3] == (b"9", True)


class TestVolcSTTModelConstructRequest:
    """Tests for request construction."""

    def test_construct_request(self):
        """Test constructing request parameters."""
        config = VolcSTTConfig(appid="test_appid", access_token="test_token", uid="test_user")
        model = VolcSTTModel(config)
        req = model.construct_request("test_reqid")
        assert "user" in req
        assert req["user"]["uid"] == "test_user"
        assert "audio" in req
        assert req["audio"]["format"] == "pcm"
        assert "request" in req
        assert req["request"]["model_name"] == "bigmodel"


class TestVolcSTTModelAuthHeaders:
    """Tests for authentication headers."""

    def test_get_auth_headers_with_token_and_appid(self):
        """Test getting auth headers with both token and appid."""
        config = VolcSTTConfig(appid="test_appid", access_token="test_token")
        model = VolcSTTModel(config)
        headers = model.get_auth_headers()
        assert "X-Api-Resource-Id" in headers
        assert headers["X-Api-Resource-Id"] == "volc.bigasr.sauc.duration"
        assert "X-Api-Access-Key" in headers
        assert headers["X-Api-Access-Key"] == "test_token"
        assert "X-Api-App-Key" in headers
        assert headers["X-Api-App-Key"] == "test_appid"
        assert "X-Api-Connect-Id" in headers

    def test_get_auth_headers_without_token(self):
        """Test getting auth headers without access token."""
        config = VolcSTTConfig(appid="test_appid", access_token="")
        model = VolcSTTModel(config)
        headers = model.get_auth_headers()
        assert "X-Api-Access-Key" not in headers

    def test_get_websocket_url(self):
        """Test getting WebSocket URL."""
        config = VolcSTTConfig(appid="test", access_token="test", ws_url="wss://custom.url")
        model = VolcSTTModel(config)
        assert model.get_websocket_url() == "wss://custom.url"


class TestVolcSTTModelIntegration:
    """Integration tests for VolcSTTModel async methods."""

    @pytest.mark.asyncio
    async def test_process_audio_data_connection_error(self):
        """Test process_audio_data with connection error."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        async def raise_error():
            raise _MockConnectionClosedError(1000, "Connection closed abnormally")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = raise_error
        mock_ws.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)
        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.process_audio_data(b"test_audio_data", 1000)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_websocket_exception(self):
        """Test process_audio_data with WebSocket exception."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)
        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.process_audio_data(b"test_audio_data", 1000)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_file_pcm(self):
        """Test processing PCM audio file."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        pcm_data = b"\x00\x01" * 1600
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        async def raise_error():
            raise _MockConnectionClosedError(1000, "Connection closed abnormally")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = raise_error
        mock_ws.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                volc_model = VolcSTTModel(config)
                volc_model.config.format = "pcm"
                result = await volc_model.process_audio_file("/test/file.pcm")
                assert "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_file_wav(self):
        """Test processing WAV audio file."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        buffer = BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x01" * 16000)
        wav_data = buffer.getvalue()

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=wav_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        async def raise_error():
            raise _MockConnectionClosedError(1000, "Connection closed")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = raise_error

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                volc_model = VolcSTTModel(config)
                volc_model.config.format = "wav"
                result = await volc_model.process_audio_file("/test/file.wav")
                assert "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_file_unsupported_format(self):
        """Test processing audio file with unsupported format."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        config.format = "flac"
        with pytest.raises(Exception, match="Unsupported format"):
            await model.process_audio_file("/test/file.flac")

    @pytest.mark.asyncio
    async def test_recognize_file(self):
        """Test recognize_file delegates to process_audio_file."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        pcm_data = b"\x00\x01" * 1600
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        async def raise_error():
            raise _MockConnectionClosedError(1000, "Connection closed")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = raise_error

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                result = await model.recognize_file("/test/file.pcm")
                assert "error" in result

    @pytest.mark.asyncio
    async def test_check_connectivity_no_file_path(self):
        """Test connectivity check without audio file path."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)
        result = await model.check_connectivity()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_with_file(self):
        """Test connectivity check with audio file path."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config, audio_file_path="/test/file.pcm")

        pcm_data = b"\x00\x01" * 1600
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        async def raise_error():
            raise _MockConnectionClosedError(1000, "Connection closed")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = raise_error

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                result = await model.check_connectivity()
                assert result is False


class TestVolcSTTModelAdditional:
    """Additional tests for edge cases and full coverage."""

    @pytest.mark.asyncio
    async def test_process_audio_data_success(self):
        """Test process_audio_data with successful WebSocket communication."""
        config = VolcSTTConfig(appid="test", access_token="test", compression=False)
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0xB0, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload_size_bytes = (8).to_bytes(4, "big", signed=False)
        response_data = bytes(header) + seq_bytes + payload_size_bytes + b"\x00" * 8

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response_data])
        mock_ws.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.process_audio_data(b"test_audio" * 100, 1000)
            assert result is not None

    @pytest.mark.asyncio
    async def test_process_audio_data_no_streaming(self):
        """Test process_audio_data without streaming delay."""
        config = VolcSTTConfig(appid="test", access_token="test", streaming=False, compression=False)
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0xB0, 0x00, 0x00])
        seq_bytes = (1).to_bytes(4, "big", signed=True)
        payload_size_bytes = (8).to_bytes(4, "big", signed=False)
        response_data = bytes(header) + seq_bytes + payload_size_bytes + b"\x00" * 8

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response_data, response_data, response_data])
        mock_ws.response_headers = {}

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.process_audio_data(b"short", 1000)
            assert result is not None

    @pytest.mark.asyncio
    async def test_process_audio_file_mp3(self):
        """Test processing MP3 audio file."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        mp3_data = b"fake_mp3_data" * 100
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=mp3_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        async def raise_error():
            raise _MockConnectionClosedError(1000, "Connection closed")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = raise_error

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                volc_model = VolcSTTModel(config)
                volc_model.config.format = "mp3"
                result = await volc_model.process_audio_file("/test/file.mp3")
                assert "error" in result

    def test_parse_response_full_response_no_sequence(self):
        """Test parsing SERVER_FULL_RESPONSE without sequence flag but with last package flag."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0x92, 0x10, 0x00])
        payload_data = b'{"result":{"text":"hello"}}'
        payload_size_bytes = len(payload_data).to_bytes(4, "big", signed=False)
        response = bytes(header) + payload_size_bytes + payload_data

        result = model.parse_response(response)
        assert result["is_last_package"] is True
        assert "payload_msg" in result

    def test_parse_response_with_gzip_compression(self):
        """Test parsing response with GZIP compression."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0x90, 0x11, 0x00])
        payload_data = b'{"result":{"text":"compressed"}}'
        compressed_data = gzip.compress(payload_data)
        payload_size_bytes = len(compressed_data).to_bytes(4, "big", signed=False)
        response = bytes(header) + payload_size_bytes + compressed_data

        result = model.parse_response(response)
        assert result["payload_msg"]["result"]["text"] == "compressed"

    def test_parse_response_thrift_serialization(self):
        """Test parsing response with non-JSON serialization."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0x90, 0x30, 0x00])
        payload_data = b"thrift_data"
        payload_size_bytes = len(payload_data).to_bytes(4, "big", signed=False)
        response = bytes(header) + payload_size_bytes + payload_data

        result = model.parse_response(response)
        assert "payload_msg" in result

    def test_generate_header_explicit_compression(self):
        """Test header generation with explicit compression type."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        header = model.generate_header(compression_type=GZIP)
        compression_type = header[2] & 0x0f
        assert compression_type == GZIP

        header = model.generate_header(compression_type=NO_COMPRESSION)
        compression_type = header[2] & 0x0f
        assert compression_type == NO_COMPRESSION

    def test_parse_response_server_ack_no_extra_data(self):
        """Test parsing SERVER_ACK without extra payload data."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0xB0, 0x00, 0x00])
        seq_bytes = (5).to_bytes(4, "big", signed=True)
        response = bytes(header) + seq_bytes + b"\x00" * 4

        result = model.parse_response(response)
        assert result["seq"] == 5
        assert result.get("payload_size", 0) == 0

    def test_parse_response_server_error_full(self):
        """Test parsing SERVER_ERROR_RESPONSE with full payload."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        header = bytearray([0x11, 0xF0, 0x10, 0x00])
        code_bytes = (2000).to_bytes(4, "big", signed=False)
        payload_size_bytes = (16).to_bytes(4, "big", signed=False)
        error_data = b'{"error": "test error"}'
        response = bytes(header) + code_bytes + payload_size_bytes + error_data

        result = model.parse_response(response)
        assert result["code"] == 2000
        assert result["payload_size"] == 16

    def test_slice_data_exact_division(self):
        """Test data slicing when data divides evenly into chunks."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        data = b"123456"
        chunks = list(model.slice_data(data, 2))
        assert len(chunks) == 3
        assert chunks[0] == (b"12", False)
        assert chunks[1] == (b"34", False)
        assert chunks[2] == (b"56", True)

    def test_slice_data_empty(self):
        """Test data slicing with empty data."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        chunks = list(model.slice_data(b"", 3))
        assert len(chunks) == 1
        assert chunks[0] == (b"", True)

    def test_slice_data_single_chunk(self):
        """Test data slicing when data is smaller than chunk size."""
        config = VolcSTTConfig(appid="test", access_token="test")
        model = VolcSTTModel(config)

        data = b"abc"
        chunks = list(model.slice_data(data, 10))
        assert len(chunks) == 1
        assert chunks[0] == (b"abc", True)


class TestVolcSTTModelStreamingSession:
    """Tests for streaming session methods - skipped due to complex loops."""

    @pytest.mark.skip(reason="process_streaming_audio has complex infinite loop - tested via integration")
    async def test_start_streaming_session(self):
        """Test start_streaming_session."""
        pass

    @pytest.mark.skip(reason="process_streaming_audio has complex infinite loop - tested via integration")
    async def test_process_streaming_audio(self):
        """Test process_streaming_audio."""
        pass
