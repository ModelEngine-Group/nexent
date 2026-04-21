"""
Unit tests for Ali STT model.

Tests the AliSTTModel and AliSTTConfig classes.
"""
import pytest
import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch
import wave

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
    from sdk.nexent.core.models.ali_stt_model import (
        AliSTTModel,
        AliSTTConfig,
        TranscriptionResult,
    )


class TestAliSTTConfig:
    """Test AliSTTConfig data model."""

    def test_config_default_values(self):
        """Test AliSTTConfig with default values."""
        config = AliSTTConfig(api_key="test_key")
        assert config.api_key == "test_key"
        assert config.model == "qwen3-asr-flash-realtime"
        assert config.language == "zh"
        assert config.ws_url is None
        assert config.format == "pcm"
        assert config.rate == 16000
        assert config.channel == 1
        assert config.seg_duration == 100
        assert config.timeout == 60
        assert config.enable_vad is True
        assert config.vad_threshold == 0.5
        assert config.vad_silence_duration_ms == 2000

    def test_config_custom_values(self):
        """Test AliSTTConfig with custom values."""
        config = AliSTTConfig(
            api_key="custom_key",
            model="custom-model",
            language="en",
            ws_url="wss://custom.example.com",
            format="wav",
            rate=48000,
            enable_vad=False,
            vad_threshold=0.7,
        )
        assert config.api_key == "custom_key"
        assert config.model == "custom-model"
        assert config.language == "en"
        assert config.ws_url == "wss://custom.example.com"
        assert config.format == "wav"
        assert config.rate == 48000
        assert config.enable_vad is False
        assert config.vad_threshold == 0.7


class TestTranscriptionResult:
    """Test TranscriptionResult class."""

    def test_init_default_values(self):
        """Test TranscriptionResult with default values."""
        result = TranscriptionResult()
        assert result.text == ""
        assert result.is_final is False
        assert result.error is None
        assert result.vad is None

    def test_init_custom_values(self):
        """Test TranscriptionResult with custom values."""
        result = TranscriptionResult()
        result.text = "Hello world"
        result.is_final = True
        result.error = "Test error"
        result.vad = "started"
        assert result.text == "Hello world"
        assert result.is_final is True
        assert result.error == "Test error"
        assert result.vad == "started"


class TestAliSTTModel:
    """Test AliSTTModel class."""

    @pytest.fixture
    def ali_config(self):
        """Create a test Ali STT configuration."""
        config = AliSTTConfig(api_key="test_key", language="zh")
        config.workspace_id = None
        return config

    @pytest.fixture
    def ali_model(self, ali_config):
        """Create a test Ali STT model instance."""
        return AliSTTModel(ali_config, "/path/to/test/audio.pcm")

    def test_init(self, ali_config):
        """Test AliSTTModel initialization."""
        model = AliSTTModel(ali_config, "/path/to/test.pcm")
        assert model.config == ali_config
        assert model.audio_file_path == "/path/to/test.pcm"
        assert isinstance(model._current_result, TranscriptionResult)

    def test_init_without_audio_path(self, ali_config):
        """Test AliSTTModel initialization without audio path."""
        model = AliSTTModel(ali_config)
        assert model.audio_file_path is None

    def test_get_websocket_url_default(self, ali_model):
        """Test get_websocket_url with default config."""
        url = ali_model.get_websocket_url()
        assert "dashscope.aliyuncs.com" in url
        assert "qwen3-asr-flash-realtime" in url

    def test_get_websocket_url_custom(self, ali_model):
        """Test get_websocket_url with custom ws_url."""
        ali_model.config.ws_url = "wss://custom.example.com"
        url = ali_model.get_websocket_url()
        assert url == "wss://custom.example.com?model=qwen3-asr-flash-realtime"

    def test_get_auth_headers_basic(self, ali_model):
        """Test get_auth_headers with basic config."""
        headers = ali_model.get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_key"
        assert "OpenAI-Beta" in headers
        assert headers["OpenAI-Beta"] == "realtime=v1"

    def test_generate_event_id(self, ali_model):
        """Test generate_event_id returns valid UUID."""
        event_id = ali_model.generate_event_id()
        assert event_id.startswith("event_")
        assert len(event_id) == len("event_") + 16

    def test_construct_session_update_with_vad(self, ali_model):
        """Test construct_session_update with VAD enabled."""
        ali_model.config.enable_vad = True
        ali_model.config.vad_threshold = 0.6
        ali_model.config.vad_silence_duration_ms = 3000
        session = ali_model.construct_session_update()

        assert session["type"] == "session.update"
        assert "event_id" in session
        assert "session" in session
        assert session["session"]["modalities"] == ["text"]
        assert "turn_detection" in session["session"]
        assert session["session"]["turn_detection"]["type"] == "server_vad"
        assert session["session"]["turn_detection"]["threshold"] == 0.6
        assert session["session"]["turn_detection"]["silence_duration_ms"] == 3000

    def test_construct_session_update_without_vad(self, ali_model):
        """Test construct_session_update with VAD disabled."""
        ali_model.config.enable_vad = False
        session = ali_model.construct_session_update()

        assert session["type"] == "session.update"
        assert "session" in session
        assert session["session"]["turn_detection"] is None

    def test_construct_audio_append_event(self, ali_model):
        """Test construct_audio_append_event."""
        audio_data = b"test_audio_data"
        event = ali_model.construct_audio_append_event(audio_data)

        assert event["type"] == "input_audio_buffer.append"
        assert "event_id" in event
        assert "audio" in event
        decoded = base64.b64decode(event["audio"])
        assert decoded == audio_data

    def test_construct_audio_commit_event(self, ali_model):
        """Test construct_audio_commit_event."""
        event = ali_model.construct_audio_commit_event()
        assert event["type"] == "input_audio_buffer.commit"
        assert "event_id" in event

    def test_construct_session_finish_event(self, ali_model):
        """Test construct_session_finish_event."""
        event = ali_model.construct_session_finish_event()
        assert event["type"] == "session.finish"
        assert "event_id" in event

    def test_parse_response_session_created(self, ali_model):
        """Test parse_response with session.created event."""
        response = {"type": "session.created", "session": {"id": "sess_123"}}
        result = ali_model.parse_response(response)
        assert result["event"] == "session.created"
        assert result["session_id"] == "sess_123"

    def test_parse_response_session_updated(self, ali_model):
        """Test parse_response with session.updated event."""
        response = {"type": "session.updated", "session": {"id": "sess_456"}}
        result = ali_model.parse_response(response)
        assert result["event"] == "session.updated"
        assert result["session_id"] == "sess_456"

    def test_parse_response_transcription_completed(self, ali_model):
        """Test parse_response with transcription completed."""
        response = {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Hello"}
        result = ali_model.parse_response(response)
        assert result["is_last_package"] is True
        assert result["text"] == "Hello"

    def test_parse_response_transcription_text(self, ali_model):
        """Test parse_response with transcription text."""
        response = {"type": "conversation.item.input_audio_transcription.text", "text": "World"}
        result = ali_model.parse_response(response)
        assert result["text"] == "World"

    def test_parse_response_vad_started(self, ali_model):
        """Test parse_response with VAD started."""
        response = {"type": "input_audio_buffer.speech_started"}
        result = ali_model.parse_response(response)
        assert result["vad"] == "started"

    def test_parse_response_vad_stopped(self, ali_model):
        """Test parse_response with VAD stopped."""
        response = {"type": "input_audio_buffer.speech_stopped"}
        result = ali_model.parse_response(response)
        assert result["vad"] == "stopped"

    def test_parse_response_session_finished(self, ali_model):
        """Test parse_response with session finished."""
        response = {"type": "session.finished", "transcript": "Final text"}
        result = ali_model.parse_response(response)
        assert result["finished"] is True
        assert result["transcript"] == "Final text"

    def test_parse_response_error(self, ali_model):
        """Test parse_response with error."""
        response = {"type": "error", "message": "Service error"}
        result = ali_model.parse_response(response)
        assert result["error"] == "Service error"

    def test_parse_response_string_input(self, ali_model):
        """Test parse_response with string input."""
        response_str = '{"type": "session.created", "session": {"id": "sess_789"}}'
        result = ali_model.parse_response(response_str)
        assert result["event"] == "session.created"
        assert result["session_id"] == "sess_789"

    def test_parse_response_invalid_json(self, ali_model):
        """Test parse_response with invalid JSON."""
        result = ali_model.parse_response("not valid json")
        assert result["event"] == "unknown"
        assert "raw" in result

    def test_parse_response_non_dict(self, ali_model):
        """Test parse_response with non-dict input."""
        result = ali_model.parse_response([1, 2, 3])
        assert result["event"] == "unknown"

    def test_read_wav_info(self, ali_model):
        """Test read_wav_info static method."""
        mock_wav_fp = MagicMock()
        mock_wav_fp.getparams.return_value = (2, 2, 44100, 100)
        mock_wav_fp.readframes.return_value = b'\x00\x00' * 200
        mock_wav_fp.__enter__ = MagicMock(return_value=mock_wav_fp)
        mock_wav_fp.__exit__ = MagicMock(return_value=None)

        with patch.object(wave, "open", return_value=mock_wav_fp):
            wav_data = b"fake_wav_data"
            nchannels, sampwidth, framerate, nframes, wave_bytes = AliSTTModel.read_wav_info(wav_data)
            assert nchannels == 2
            assert sampwidth == 2
            assert framerate == 44100
            assert nframes == 100
            assert len(wave_bytes) == 400

    def test_slice_data(self, ali_model):
        """Test slice_data static method."""
        data = b'0123456789'
        chunk_size = 3

        chunks = list(AliSTTModel.slice_data(data, chunk_size))

        assert len(chunks) == 4
        assert chunks[0] == (b'012', False)
        assert chunks[1] == (b'345', False)
        assert chunks[2] == (b'678', False)
        assert chunks[3] == (b'9', True)

    def test_slice_data_exact_chunks(self, ali_model):
        """Test slice_data with data dividing evenly into chunks."""
        data = b'123456'
        chunks = list(AliSTTModel.slice_data(data, 2))
        assert len(chunks) == 3
        assert chunks[0] == (b'12', False)
        assert chunks[1] == (b'34', False)
        assert chunks[2] == (b'56', True)

    def test_slice_data_empty(self, ali_model):
        """Test slice_data with empty data."""
        chunks = list(AliSTTModel.slice_data(b'', 3))
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_process_audio_file_wav(self, ali_model):
        """Test process_audio_file with WAV format."""
        wav_data = b"fake_wav_data" * 100

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=wav_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        mock_wav_info = (1, 2, 16000, 1600, b'\x00\x00' * 1600)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file), \
             patch.object(ali_model, 'read_wav_info', return_value=mock_wav_info), \
             patch.object(ali_model, 'process_audio_data', return_value={"text": "test"}) as mock_process:
            ali_model.config.format = "wav"
            result = await ali_model.process_audio_file("/test/file.wav")
            assert result is not None
            mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_audio_file_pcm_with_header(self, ali_model):
        """Test process_audio_file with PCM format containing WAV header."""
        pcm_data = b'RIFF' + b'\x00\x00\x00\x00' + b'WAVE' + b'\x00' * 20

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        mock_wav_info = (1, 2, 16000, 100, b'\x00\x00' * 100)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file), \
             patch.object(ali_model, 'read_wav_info', return_value=mock_wav_info), \
             patch.object(ali_model, 'process_audio_data', return_value={"text": "test"}) as mock_process:
            ali_model.config.format = "pcm"
            result = await ali_model.process_audio_file("/test/file.pcm")
            assert result is not None
            mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_audio_file_pcm_raw(self, ali_model):
        """Test process_audio_file with raw PCM format."""
        pcm_data = b'\x00\x01' * 1600

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file), \
             patch.object(ali_model, 'process_audio_data', return_value={"text": "test"}) as mock_process:
            ali_model.config.format = "pcm"
            result = await ali_model.process_audio_file("/test/file.pcm")
            assert result is not None

    @pytest.mark.asyncio
    async def test_process_audio_file_unsupported_format(self, ali_model):
        """Test process_audio_file with unsupported format."""
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=b"data")
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            ali_model.config.format = "unsupported"
            with pytest.raises(Exception, match="Unsupported format"):
                await ali_model.process_audio_file("/test/file.unsupported")

    @pytest.mark.asyncio
    async def test_recognize_file(self, ali_model):
        """Test recognize_file method."""
        expected_result = {"text": "test transcription"}

        with patch.object(ali_model, 'process_audio_file', return_value=expected_result) as mock_process:
            result = await ali_model.recognize_file("/test/audio.pcm")
            assert result == expected_result
            mock_process.assert_called_once_with("/test/audio.pcm")

    @pytest.mark.asyncio
    async def test_check_connectivity_success(self, ali_model):
        """Test check_connectivity with successful connection."""
        success_result = {"text": "test"}

        with patch.object(ali_model, 'process_audio_file', return_value=success_result):
            result = await ali_model.check_connectivity()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_failure(self, ali_model):
        """Test check_connectivity with connection failure."""
        error_result = {"error": "Connection failed"}

        with patch.object(ali_model, 'process_audio_file', return_value=error_result):
            result = await ali_model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_exception(self, ali_model):
        """Test check_connectivity with exception."""
        with patch.object(ali_model, 'process_audio_file', side_effect=Exception("Network error")):
            result = await ali_model.check_connectivity()
            assert result is False

    def test_is_stt_result_successful_valid(self, ali_model):
        """Test _is_stt_result_successful with valid result."""
        assert ali_model._is_stt_result_successful({"text": "Hello"}) is True

    def test_is_stt_result_successful_error(self, ali_model):
        """Test _is_stt_result_successful with error result."""
        assert ali_model._is_stt_result_successful({"error": "failed"}) is False

    def test_is_stt_result_successful_empty(self, ali_model):
        """Test _is_stt_result_successful with empty result."""
        assert ali_model._is_stt_result_successful({}) is False

    def test_extract_stt_error_message_direct(self, ali_model):
        """Test _extract_stt_error_message with direct error."""
        msg = ali_model._extract_stt_error_message({"error": "Direct error"})
        assert msg == "Direct error"

    def test_extract_stt_error_message_empty(self, ali_model):
        """Test _extract_stt_error_message with empty error."""
        msg = ali_model._extract_stt_error_message({})
        assert "Unknown error" in msg
