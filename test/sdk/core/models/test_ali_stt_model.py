"""
Unit tests for Ali STT model.

Tests the AliSTTModel and AliSTTConfig classes.
"""
import pytest
import asyncio
import base64
import json
import sys as _sys
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
import wave

# Create a mock ConnectionClosed exception that matches the websockets library interface
class _MockConnectionClosed(Exception):
    """Mock for websockets.exceptions.ConnectionClosed."""
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
        super().__init__(reason)

# Create a mock websockets module
_mock_websockets = MagicMock()
_mock_websockets.connect = MagicMock()
_mock_websockets.exceptions = MagicMock()
_mock_websockets.exceptions.ConnectionClosed = _MockConnectionClosed
_mock_websockets.exceptions.ConnectionClosedError = _MockConnectionClosed
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
            ws_url="wss://host/ws",
            format="wav",
            rate=48000,
            enable_vad=False,
            vad_threshold=0.7,
        )
        assert config.api_key == "custom_key"
        assert config.model == "custom-model"
        assert config.language == "en"
        assert config.ws_url == "wss://host/ws"
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
        assert url.startswith("wss://")
        assert "qwen3-asr-flash-realtime" in url

    def test_get_websocket_url_custom(self, ali_model):
        """Test get_websocket_url with custom ws_url."""
        ali_model.config.ws_url = "wss://host"
        url = ali_model.get_websocket_url()
        assert url.startswith("wss://host")
        assert "model=" in url

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
    async def test_process_audio_data_intermediate_transcription(self, ali_model):
        """Test process_audio_data with intermediate transcription text (not final)."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "Partial"})
        response3 = json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Final"})
        response4 = json.dumps({"type": "session.finished", "transcript": "Final"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3, response4])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_with_callback(self, ali_model):
        """Test process_audio_data with on_result callback."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Transcribed"})
        response3 = json.dumps({"type": "session.finished", "transcript": "Transcribed"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        callback_results = []
        async def on_result(text):
            callback_results.append(text)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000, on_result=on_result)

        assert "text" in result
        assert len(callback_results) > 0

    @pytest.mark.asyncio
    async def test_process_audio_data_callback_intermediate_only(self, ali_model):
        """Test process_audio_data with callback for intermediate results only."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "Partial result"})
        response3 = json.dumps({"type": "session.finished", "transcript": "Final"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        callback_results = []
        async def on_result(text):
            callback_results.append(text)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000, on_result=on_result)

        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_return_empty_text(self, ali_model):
        """Test process_audio_data returns empty text when no transcription."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "session.finished", "transcript": ""})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "text" in result
        assert result.get("text", "") == ""

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
    async def test_process_audio_data_error_from_result(self, ali_model):
        """Test process_audio_data with error in result."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "error", "message": "Service error"}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "error" in result

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


class TestAliSTTModelAsync:
    """Test async methods in AliSTTModel."""

    @pytest.fixture
    def ali_config(self):
        """Create a test Ali STT configuration."""
        config = AliSTTConfig(api_key="test_key", language="zh")
        return config

    @pytest.fixture
    def ali_model(self, ali_config):
        """Create a test Ali STT model instance."""
        return AliSTTModel(ali_config, "/path/to/test/audio.pcm")

    @pytest.mark.asyncio
    async def test_handle_stt_event_error(self, ali_model):
        """Test _handle_stt_event with error event."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "error", "error": "Test error"},
            mock_ws,
            transcription_texts
        )
        assert result is True
        mock_ws.send_json.assert_called_once_with({"error": "Test error"})

    @pytest.mark.asyncio
    async def test_handle_stt_event_speech_started(self, ali_model):
        """Test _handle_stt_event with speech_started event."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "input_audio_buffer.speech_started"},
            mock_ws,
            transcription_texts
        )
        assert result is False
        mock_ws.send_json.assert_called_once_with({"vad": "started"})

    @pytest.mark.asyncio
    async def test_handle_stt_event_speech_stopped(self, ali_model):
        """Test _handle_stt_event with speech_stopped event."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "input_audio_buffer.speech_stopped"},
            mock_ws,
            transcription_texts
        )
        assert result is False
        mock_ws.send_json.assert_called_once_with({"vad": "stopped"})

    @pytest.mark.asyncio
    async def test_handle_stt_event_transcription_text(self, ali_model):
        """Test _handle_stt_event with transcription text."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "conversation.item.input_audio_transcription.text", "text": "Hello"},
            mock_ws,
            transcription_texts
        )
        assert result is False
        assert "Hello" in transcription_texts
        mock_ws.send_json.assert_called_once_with({"text": "Hello", "is_final": False})

    @pytest.mark.asyncio
    async def test_handle_stt_event_transcription_completed(self, ali_model):
        """Test _handle_stt_event with transcription completed."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "conversation.item.input_audio_transcription.completed", "text": "World"},
            mock_ws,
            transcription_texts
        )
        assert result is False
        assert "World" in transcription_texts
        mock_ws.send_json.assert_called_once_with({"text": "World", "is_final": True})

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_finished(self, ali_model):
        """Test _handle_stt_event with session finished."""
        mock_ws = AsyncMock()
        transcription_texts = ["First", "Second"]
        result = await ali_model._handle_stt_event(
            {"event": "session.finished", "transcript": "Combined text"},
            mock_ws,
            transcription_texts
        )
        assert result is True
        mock_ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_created(self, ali_model):
        """Test _handle_stt_event with session.created."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "session.created"},
            mock_ws,
            transcription_texts
        )
        assert result is False
        mock_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_stt_event_unhandled(self, ali_model):
        """Test _handle_stt_event with unhandled event type."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "unknown.event"},
            mock_ws,
            transcription_texts
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_send_exception(self, ali_model):
        """Test _handle_stt_event when send_json raises exception."""
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = Exception("Connection error")
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "error", "error": "Test"},
            mock_ws,
            transcription_texts
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_stt_event_transcription_text_empty_text(self, ali_model):
        """Test _handle_stt_event with empty transcription text."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "conversation.item.input_audio_transcription.text", "text": ""},
            mock_ws,
            transcription_texts
        )
        assert result is False
        assert transcription_texts == []

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_updated(self, ali_model):
        """Test _handle_stt_event with session.updated event."""
        mock_ws = AsyncMock()
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "session.updated"},
            mock_ws,
            transcription_texts
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_speech_started_send_exception(self, ali_model):
        """Test _handle_stt_event with speech_started and send exception."""
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = Exception("Connection error")
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "input_audio_buffer.speech_started"},
            mock_ws,
            transcription_texts
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_speech_stopped_send_exception(self, ali_model):
        """Test _handle_stt_event with speech_stopped and send exception."""
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = Exception("Connection error")
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "input_audio_buffer.speech_stopped"},
            mock_ws,
            transcription_texts
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_transcription_completed_send_exception(self, ali_model):
        """Test _handle_stt_event with transcription completed and send exception."""
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = Exception("Connection error")
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "conversation.item.input_audio_transcription.completed", "text": "Test"},
            mock_ws,
            transcription_texts
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_finished_no_transcript(self, ali_model):
        """Test _handle_stt_event with session finished but no transcript."""
        mock_ws = AsyncMock()
        transcription_texts = ["Previous", "Texts"]
        result = await ali_model._handle_stt_event(
            {"event": "session.finished", "transcript": ""},
            mock_ws,
            transcription_texts
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_finished_send_exception(self, ali_model):
        """Test _handle_stt_event with session finished and send exception."""
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = Exception("Connection error")
        transcription_texts = []
        result = await ali_model._handle_stt_event(
            {"event": "session.finished", "transcript": "Final text"},
            mock_ws,
            transcription_texts
        )
        assert result is True


class TestAliSTTModelProcessAudioData:
    """Test process_audio_data method in AliSTTModel."""

    @pytest.fixture
    def ali_config(self):
        """Create a test Ali STT configuration."""
        config = AliSTTConfig(api_key="test_key", language="zh")
        return config

    @pytest.fixture
    def ali_model(self, ali_config):
        """Create a test Ali STT model instance."""
        return AliSTTModel(ali_config, "/path/to/test/audio.pcm")

    @pytest.mark.asyncio
    async def test_process_audio_data_success(self, ali_model):
        """Test process_audio_data with successful WebSocket communication."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Hello world"})
        response3 = json.dumps({"type": "session.finished", "transcript": "Hello world"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_error_response(self, ali_model):
        """Test process_audio_data with error response."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "error", "message": "Service error"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_intermediate_transcription(self, ali_model):
        """Test process_audio_data with intermediate transcription results."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "Partial"})
        response3 = json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Final"})
        response4 = json.dumps({"type": "session.finished", "transcript": "Final"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3, response4])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_timeout(self, ali_model):
        """Test process_audio_data with timeout."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, asyncio.TimeoutError()])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data", 1000)

        assert "text" in result or "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_websocket_exception(self, ali_model):
        """Test process_audio_data when WebSocket raises exception."""
        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data", 1000)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_empty_transcription(self, ali_model):
        """Test process_audio_data with empty transcription."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "session.finished", "transcript": ""})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data", 1000)

        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_vad_disabled_commit(self, ali_model):
        """Test process_audio_data with VAD disabled triggers commit."""
        ali_model.config.enable_vad = False
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "session.finished", "transcript": "Test"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert mock_ws.send.call_count >= 4


class TestAliSTTModelStreamingSession:
    """Test start_streaming_session method in AliSTTModel."""

    @pytest.fixture
    def ali_config(self):
        """Create a test Ali STT configuration."""
        config = AliSTTConfig(api_key="test_key", language="zh")
        return config

    @pytest.fixture
    def ali_model(self, ali_config):
        """Create a test Ali STT model instance."""
        return AliSTTModel(ali_config, "/path/to/test/audio.pcm")

    @pytest.mark.asyncio
    async def test_start_streaming_session_basic(self, ali_model):
        """Test start_streaming_session with basic communication."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            json.dumps({"type": "input_audio_buffer.speech_stopped"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_client_disconnect_before_audio(self, ali_model):
        """Test when client disconnects before sending audio."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            _MockConnectionClosed(1000, "Client closed")
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_with_transcription(self, ali_model):
        """Test start_streaming_session with transcription results."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "Hello"}),
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "text": "Hello world"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_with_error(self, ali_model):
        """Test start_streaming_session with error response from STT."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "error", "error": "Service error"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_buffer_committed(self, ali_model):
        """Test start_streaming_session with input_audio_buffer.committed event."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            json.dumps({"type": "input_audio_buffer.committed"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_with_item_content(self, ali_model):
        """Test start_streaming_session with transcription in item content."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({
                "type": "conversation.item.input_audio_transcription.text",
                "item": {"content": [{"transcript": "Transcribed from content"}]}
            }),
            asyncio.TimeoutError(),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_client_exception(self, ali_model):
        """Test when client raises exception during audio receive."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            Exception("Unexpected error"),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_stt_server_exception(self, ali_model):
        """Test when STT server raises exception."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            Exception("STT server error"),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_general_exception(self, ali_model):
        """Test with general exception during connection."""
        mock_ws_client = AsyncMock()
        mock_ws_client.send_json = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_server_connection_closed(self, ali_model):
        """Test when STT server connection is closed."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            _MockConnectionClosed(1000, "Server closed"),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_client_disconnect(self, ali_model):
        """Test when client disconnects during streaming."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            _MockConnectionClosed(1000, "Client closed")
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)


class TestAliSTTModelAdditionalCoverage:
    """Additional tests for full coverage."""

    @pytest.fixture
    def ali_config(self):
        """Create a test Ali STT configuration."""
        config = AliSTTConfig(api_key="test_key", language="zh")
        return config

    @pytest.fixture
    def ali_model(self, ali_config):
        """Create a test Ali STT model instance."""
        return AliSTTModel(ali_config, "/path/to/test/audio.pcm")

    @pytest.mark.asyncio
    async def test_check_connectivity_exception_with_traceback(self, ali_model):
        """Test check_connectivity with exception and traceback logging."""
        with patch.object(ali_model, 'process_audio_file', side_effect=Exception("Test error")):
            result = await ali_model.check_connectivity()
            assert result is False

    def test_extract_stt_error_message_with_payload_error(self, ali_model):
        """Test _extract_stt_error_message with payload error."""
        result = {
            'code': 1001,
            'payload_msg': {'error': 'Payload error message'}
        }
        msg = ali_model._extract_stt_error_message(result)
        assert "STT service error code: 1001" in msg
        assert "Payload error message" in msg

    def test_extract_stt_error_message_invalid_type(self, ali_model):
        """Test _extract_stt_error_message with invalid type."""
        msg = ali_model._extract_stt_error_message("not a dict")
        assert "Invalid result type" in msg

    def test_is_stt_result_successful_with_payload_error(self, ali_model):
        """Test _is_stt_result_successful with payload error."""
        result = {
            'payload_msg': {'error': 'Test error'}
        }
        assert ali_model._is_stt_result_successful(result) is False

    def test_is_stt_result_successful_with_error_code(self, ali_model):
        """Test _is_stt_result_successful with error code."""
        result = {'code': 2000}
        assert ali_model._is_stt_result_successful(result) is False

    def test_is_stt_result_successful_non_dict(self, ali_model):
        """Test _is_stt_result_successful with non-dict."""
        assert ali_model._is_stt_result_successful("string") is False
        assert ali_model._is_stt_result_successful(None) is False

    def test_parse_response_unknown_event_with_additional_fields(self, ali_model):
        """Test parse_response with unknown event - extra fields are not copied to result."""
        response = {
            "type": "unknown.event",
            "extra_field": "value",
            "another_field": 123
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "unknown.event"
        assert "extra_field" not in result


class TestAliSTTModelEdgeCases:
    """Edge case tests for complete coverage."""

    @pytest.fixture
    def ali_config(self):
        """Create a test Ali STT configuration."""
        return AliSTTConfig(api_key="test_key", language="zh")

    @pytest.fixture
    def ali_model(self, ali_config):
        """Create a test Ali STT model instance."""
        return AliSTTModel(ali_config, "/path/to/test/audio.pcm")

    def test_config_all_parameters(self, ali_config):
        """Test AliSTTConfig with all parameters."""
        config = AliSTTConfig(
            api_key="key123",
            model="qwen3-asr",
            language="en",
            ws_url="wss://host/ws",
            format="wav",
            rate=48000,
            channel=2,
            seg_duration=150,
            timeout=120,
            enable_vad=False,
            vad_threshold=0.8,
            vad_silence_duration_ms=3000,
        )
        assert config.api_key == "key123"
        assert config.model == "qwen3-asr"
        assert config.language == "en"
        assert config.ws_url == "wss://host/ws"
        assert config.format == "wav"
        assert config.rate == 48000
        assert config.channel == 2
        assert config.seg_duration == 150
        assert config.timeout == 120
        assert config.enable_vad is False
        assert config.vad_threshold == 0.8
        assert config.vad_silence_duration_ms == 3000

    def test_get_websocket_url_with_custom_ws_url_and_model(self, ali_model):
        """Test get_websocket_url with custom ws_url and model."""
        ali_model.config.ws_url = "wss://host/stt"
        ali_model.config.model = "custom-model"
        url = ali_model.get_websocket_url()
        assert url.startswith("wss://host")
        assert "custom-model" in url

    def test_construct_session_update_with_custom_vad_settings(self, ali_model):
        """Test construct_session_update with custom VAD settings."""
        ali_model.config.enable_vad = True
        ali_model.config.vad_threshold = 0.3
        ali_model.config.vad_silence_duration_ms = 5000
        session = ali_model.construct_session_update()
        assert session["session"]["turn_detection"]["threshold"] == 0.3
        assert session["session"]["turn_detection"]["silence_duration_ms"] == 5000

    def test_construct_session_update_with_custom_format_and_rate(self, ali_model):
        """Test construct_session_update with custom format and rate."""
        ali_model.config.format = "wav"
        ali_model.config.rate = 44100
        ali_model.config.model = "custom-model"
        ali_model.config.language = "en"
        session = ali_model.construct_session_update()
        assert session["session"]["input_audio_format"] == "wav"
        assert session["session"]["sample_rate"] == 44100
        assert session["session"]["input_audio_transcription"]["model"] == "custom-model"
        assert session["session"]["input_audio_transcription"]["language"] == "en"

    def test_construct_audio_append_event_with_empty_data(self, ali_model):
        """Test construct_audio_append_event with empty data."""
        event = ali_model.construct_audio_append_event(b"")
        assert event["type"] == "input_audio_buffer.append"
        assert event["audio"] == ""

    def test_generate_event_id_uniqueness(self, ali_model):
        """Test generate_event_id generates unique IDs."""
        ids = [ali_model.generate_event_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_parse_response_with_empty_text(self, ali_model):
        """Test parse_response with empty text field."""
        response = {
            "type": "conversation.item.input_audio_transcription.text",
            "text": ""
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "conversation.item.input_audio_transcription.text"
        assert result["text"] == ""

    def test_parse_response_conversation_item_created(self, ali_model):
        """Test parse_response with conversation.item.created event."""
        response = {"type": "conversation.item.created"}
        result = ali_model.parse_response(response)
        assert result["event"] == "conversation.item.created"

    @pytest.mark.asyncio
    async def test_process_audio_data_multiple_intermediate_results(self, ali_model):
        """Test process_audio_data with multiple intermediate transcription results."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "First"})
        response3 = json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "Second"})
        response4 = json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "Final"})
        response5 = json.dumps({"type": "session.finished", "transcript": "Final"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3, response4, response5])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_with_error_after_initial(self, ali_model):
        """Test process_audio_data where error comes after session created."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "error", "message": "Service error occurred"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)

        assert "error" in result
        assert "Service error" in result["error"]

    @pytest.mark.asyncio
    async def test_start_streaming_session_multiple_audio_chunks(self, ali_model):
        """Test start_streaming_session with multiple audio chunks."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data_1",
            b"audio_data_2",
            b"audio_data_3",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            json.dumps({"type": "input_audio_buffer.speech_stopped"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            json.dumps({"type": "input_audio_buffer.committed"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_send_json_exception(self, ali_model):
        """Test start_streaming_session when send_json raises exception."""
        mock_ws_client = AsyncMock()
        mock_ws_client.send_json = AsyncMock(side_effect=Exception("Send failed"))
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_start_streaming_session_completed_with_empty_transcription(self, ali_model):
        """Test start_streaming_session transcription completed with empty text."""
        mock_ws_client = AsyncMock()
        mock_ws_client.receive_bytes = AsyncMock(side_effect=[
            b"audio_data",
            asyncio.TimeoutError(),
        ])
        mock_ws_client.send_json = AsyncMock()

        mock_ws_server = AsyncMock()
        mock_ws_server.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created", "session": {"id": "sess_123"}}),
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "input_audio_buffer.speech_started"}),
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "text": ""}),
        ])
        mock_ws_server.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws_server)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            await ali_model.start_streaming_session(mock_ws_client)

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_finished_with_combined_text(self, ali_model):
        """Test _handle_stt_event session finished uses combined transcription."""
        mock_ws = AsyncMock()
        transcription_texts = ["First part", "Second part"]
        result = await ali_model._handle_stt_event(
            {"event": "session.finished", "transcript": ""},
            mock_ws,
            transcription_texts
        )
        assert result is True
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert "First part Second part" in call_args["text"]

    @pytest.mark.asyncio
    async def test_check_connectivity_success_with_text_result(self, ali_model):
        """Test check_connectivity with text result."""
        with patch.object(ali_model, 'process_audio_file', return_value={"text": "Transcribed text"}):
            result = await ali_model.check_connectivity()
            assert result is True

    def test_is_stt_result_successful_with_only_text(self, ali_model):
        """Test _is_stt_result_successful with only text key."""
        assert ali_model._is_stt_result_successful({"text": "Hello"}) is True

    def test_is_stt_result_successful_with_empty_text(self, ali_model):
        """Test _is_stt_result_successful with empty text."""
        assert ali_model._is_stt_result_successful({"text": ""}) is True

    @pytest.mark.asyncio
    async def test_process_audio_file_pcm_with_wav_header(self, ali_model):
        """Test process_audio_file with PCM file that has WAV header."""
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

        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "session.finished", "transcript": "Transcribed"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                ali_model.config.format = "pcm"
                result = await ali_model.process_audio_file("/test/file.pcm")
                assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_file_pcm_raw(self, ali_model):
        """Test process_audio_file with raw PCM file (no WAV header)."""
        pcm_data = b"\x00\x01" * 16000

        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=pcm_data)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=None)

        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "session.finished", "transcript": "Transcribed"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_aiofiles, "open", return_value=mock_file):
            with patch.object(_mock_websockets, "connect", return_value=mock_connect):
                ali_model.config.format = "pcm"
                result = await ali_model.process_audio_file("/test/file.pcm")
                assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_timeout_during_receive(self, ali_model):
        """Test process_audio_data with timeout during receive loop."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "session.finished", "transcript": "Final"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, asyncio.TimeoutError()])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000)
            assert "text" in result

    @pytest.mark.asyncio
    async def test_process_audio_data_with_intermediate_callback(self, ali_model):
        """Test process_audio_data with intermediate transcription callback."""
        response1 = json.dumps({"type": "session.created", "session": {"id": "sess_123"}})
        response2 = json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "Partial"})
        response3 = json.dumps({"type": "session.finished", "transcript": "Final"})

        callback_results = []
        async def on_result(text):
            callback_results.append(text)

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response1, response2, response3])
        mock_ws.send = AsyncMock()

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await ali_model.process_audio_data(b"audio_data" * 100, 1000, on_result=on_result)
            assert "text" in result
            assert len(callback_results) > 0

    def test_parse_response_with_item_content_transcript(self, ali_model):
        """Test parse_response with item.content structure - falls back to empty text."""
        response = {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "",
            "item": {
                "content": [
                    {"transcript": "Transcribed from item content"}
                ]
            }
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "conversation.item.input_audio_transcription.completed"
        assert result["text"] == ""

    def test_parse_response_with_stash_field(self, ali_model):
        """Test parse_response with stash field - falls back to empty text."""
        response = {
            "type": "conversation.item.input_audio_transcription.text",
            "text": "",
            "stash": "Stashed text content"
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "conversation.item.input_audio_transcription.text"
        assert result["text"] == ""

    def test_parse_response_session_created_with_full_session(self, ali_model):
        """Test parse_response with session.created including full session info."""
        response = {
            "type": "session.created",
            "session": {
                "id": "sess_abc123",
                "status": "incomplete",
                " modalities": ["text", "audio"]
            }
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "session.created"
        assert result["session_id"] == "sess_abc123"

    def test_parse_response_session_updated(self, ali_model):
        """Test parse_response with session.updated."""
        response = {
            "type": "session.updated",
            "session": {
                "id": "sess_xyz789",
                "status": "completed"
            }
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "session.updated"
        assert result["session_id"] == "sess_xyz789"

    def test_parse_response_input_audio_buffer_speech_started(self, ali_model):
        """Test parse_response with input_audio_buffer.speech_started."""
        response = {"type": "input_audio_buffer.speech_started"}
        result = ali_model.parse_response(response)
        assert result["event"] == "input_audio_buffer.speech_started"
        assert result["vad"] == "started"

    def test_parse_response_input_audio_buffer_speech_stopped(self, ali_model):
        """Test parse_response with input_audio_buffer.speech_stopped."""
        response = {"type": "input_audio_buffer.speech_stopped"}
        result = ali_model.parse_response(response)
        assert result["event"] == "input_audio_buffer.speech_stopped"
        assert result["vad"] == "stopped"

    def test_parse_response_session_finished(self, ali_model):
        """Test parse_response with session.finished."""
        response = {
            "type": "session.finished",
            "transcript": "Final transcription text"
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "session.finished"
        assert result["finished"] is True
        assert result["transcript"] == "Final transcription text"

    def test_parse_response_error(self, ali_model):
        """Test parse_response with error event."""
        response = {
            "type": "error",
            "message": "Invalid audio format"
        }
        result = ali_model.parse_response(response)
        assert result["event"] == "error"
        assert result["error"] == "Invalid audio format"

    def test_parse_response_unknown_event(self, ali_model):
        """Test parse_response with unknown event type."""
        response = {"type": "unknown.custom.event", "data": "test"}
        result = ali_model.parse_response(response)
        assert result["event"] == "unknown.custom.event"
        assert "raw" not in result

    def test_parse_response_non_dict_input(self, ali_model):
        """Test parse_response with non-dict input."""
        result = ali_model.parse_response(12345)
        assert result["event"] == "unknown"

    def test_parse_response_invalid_json_string(self, ali_model):
        """Test parse_response with invalid JSON string."""
        result = ali_model.parse_response("not valid json {")
        assert result["event"] == "unknown"
        assert "raw" in result

    @pytest.mark.asyncio
    async def test_handle_stt_event_error_send_exception(self, ali_model):
        """Test _handle_stt_event error event when send fails."""
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock(side_effect=Exception("Connection lost"))

        result = await ali_model._handle_stt_event(
            {"event": "error", "error": "Test error"},
            mock_ws,
            []
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_stt_event_speech_started_send_exception(self, ali_model):
        """Test _handle_stt_event speech_started when send fails."""
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock(side_effect=Exception("Connection lost"))

        result = await ali_model._handle_stt_event(
            {"event": "input_audio_buffer.speech_started"},
            mock_ws,
            []
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_speech_stopped_send_exception(self, ali_model):
        """Test _handle_stt_event speech_stopped when send fails."""
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock(side_effect=Exception("Connection lost"))

        result = await ali_model._handle_stt_event(
            {"event": "input_audio_buffer.speech_stopped"},
            mock_ws,
            []
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_transcription_text_empty(self, ali_model):
        """Test _handle_stt_event with empty transcription text - sends empty result."""
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        result = await ali_model._handle_stt_event(
            {"event": "conversation.item.input_audio_transcription.text", "text": ""},
            mock_ws,
            []
        )
        assert result is False
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["text"] == ""
        assert call_args["is_final"] is False

    @pytest.mark.asyncio
    async def test_handle_stt_event_session_finished_empty_transcript(self, ali_model):
        """Test _handle_stt_event session.finished with empty transcript."""
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()

        transcription_texts = ["First", "Second"]
        result = await ali_model._handle_stt_event(
            {"event": "session.finished", "transcript": ""},
            mock_ws,
            transcription_texts
        )
        assert result is True
        mock_ws.send_json.assert_called_once()
        assert "First Second" in mock_ws.send_json.call_args[0][0]["text"]

    def test_slice_data_with_exact_division(self, ali_model):
        """Test slice_data with data that divides evenly."""
        data = b"1234567890"
        chunks = list(ali_model.slice_data(data, 5))
        assert len(chunks) == 2
        assert chunks[0] == (b"12345", False)
        assert chunks[1] == (b"67890", True)

    def test_slice_data_single_chunk(self, ali_model):
        """Test slice_data with data smaller than chunk size."""
        data = b"abc"
        chunks = list(ali_model.slice_data(data, 10))
        assert len(chunks) == 1
        assert chunks[0] == (b"abc", True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
