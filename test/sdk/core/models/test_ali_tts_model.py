"""
Unit tests for Ali TTS model.

Tests the AliTTSModel and AliTTSConfig classes.
"""
import pytest
import asyncio
import base64
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Add SDK to path before imports
_current_dir = os.path.dirname(os.path.abspath(__file__))
_sdk_dir = os.path.abspath(os.path.join(_current_dir, "../../../sdk"))
if _sdk_dir not in sys.path:
    sys.path.insert(0, _sdk_dir)

_mock_websockets = MagicMock()
_mock_websockets.connect = MagicMock()
_mock_websockets.exceptions = MagicMock()

_mock_aiofiles = MagicMock()


class _MockConnectionClosedError(Exception):
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
        super().__init__(reason)


_mock_websockets.exceptions.ConnectionClosedError = _MockConnectionClosedError
_mock_websockets.exceptions.WebSocketException = Exception


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

for mod_name, mock_obj in _module_mocks.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = mock_obj

from nexent.core.models.ali_tts_model import (
    AliTTSModel,
    AliTTSConfig,
    AliTTSError,
    COSYVOICE_API_URL,
    QWEN_REALTIME_API_URL,
)


class TestAliTTSConfig:
    """Test AliTTSConfig data model."""

    def test_config_default_values(self):
        """Test AliTTSConfig with default values."""
        config = AliTTSConfig(api_key="test_key")
        assert config.api_key == "test_key"
        assert config.model == "cosyvoice-v2"
        assert config.voice is None
        assert config.speech_rate == 1.0
        assert config.pitch_rate == 1.0
        assert config.volume == 50.0
        assert config.ws_url is None
        assert config.format == "mp3"
        assert config.sample_rate == 16000
        assert config.workspace_id is None

    def test_config_custom_values(self):
        """Test AliTTSConfig with custom values."""
        config = AliTTSConfig(
            api_key="custom_key",
            model="custom-tts",
            voice="custom_voice",
            speech_rate=1.5,
            pitch_rate=0.8,
            volume=75.0,
            ws_url="wss://custom.example.com",
            format="pcm",
            sample_rate=22050,
            workspace_id="ws_123"
        )
        assert config.api_key == "custom_key"
        assert config.model == "custom-tts"
        assert config.voice == "custom_voice"
        assert config.speech_rate == 1.5
        assert config.pitch_rate == 0.8
        assert config.volume == 75.0
        assert config.ws_url == "wss://custom.example.com"
        assert config.format == "pcm"
        assert config.sample_rate == 22050
        assert config.workspace_id == "ws_123"

    def test_is_realtime_api_true(self):
        """Test is_realtime_api returns True for /realtime URL."""
        config = AliTTSConfig(api_key="key", ws_url="wss://example.com/realtime")
        assert config.is_realtime_api() is True

    def test_is_realtime_api_false(self):
        """Test is_realtime_api returns False for non-realtime URL."""
        config = AliTTSConfig(api_key="key", ws_url="wss://example.com/api")
        assert config.is_realtime_api() is False

    def test_is_realtime_api_empty_url(self):
        """Test is_realtime_api returns False for empty URL."""
        config = AliTTSConfig(api_key="key")
        assert config.is_realtime_api() is False

    def test_get_api_url_custom(self):
        """Test get_api_url with custom ws_url."""
        config = AliTTSConfig(api_key="key", ws_url="wss://custom.example.com")
        assert config.get_api_url() == "wss://custom.example.com"

    def test_get_api_url_qwen_realtime(self):
        """Test get_api_url with custom ws_url - returns ws_url directly."""
        config = AliTTSConfig(api_key="key", ws_url="wss://custom.example.com/realtime")
        assert config.get_api_url() == "wss://custom.example.com/realtime"

    def test_get_api_url_qwen_model(self):
        """Test get_api_url for qwen model without realtime URL."""
        config = AliTTSConfig(api_key="key", model="qwen-tts-v1")
        assert config.get_api_url() == QWEN_REALTIME_API_URL

    def test_get_api_url_cosyvoice_default(self):
        """Test get_api_url for CosyVoice default."""
        config = AliTTSConfig(api_key="key")
        assert config.get_api_url() == COSYVOICE_API_URL


class TestAliTTSError:
    """Test AliTTSError exception class."""

    def test_error_message(self):
        """Test AliTTSError stores message."""
        err = AliTTSError("Service error occurred")
        assert err.message == "Service error occurred"
        assert str(err) == "Service error occurred"

    def test_error_inheritance(self):
        """Test AliTTSError inherits from Exception."""
        assert issubclass(AliTTSError, Exception)


class TestAliTTSModel:
    """Test AliTTSModel class."""

    @pytest.fixture
    def cosy_config(self):
        """Create a CosyVoice config."""
        return AliTTSConfig(api_key="test_key", model="cosyvoice-v2", voice="longxiaochun_v2")

    @pytest.fixture
    def qwen_config(self):
        """Create a Qwen Realtime config."""
        return AliTTSConfig(api_key="test_key", model="qwen-tts", voice="Cherry")

    @pytest.fixture
    def cosy_model(self, cosy_config):
        """Create a CosyVoice model instance."""
        return AliTTSModel(cosy_config)

    @pytest.fixture
    def qwen_model(self, qwen_config):
        """Create a Qwen Realtime model instance."""
        return AliTTSModel(qwen_config)

    def test_init_cosyvoice(self, cosy_config):
        """Test AliTTSModel initialization for CosyVoice."""
        model = AliTTSModel(cosy_config)
        assert model.config == cosy_config
        assert model._is_realtime is False

    def test_init_qwen(self, qwen_config):
        """Test AliTTSModel initialization for Qwen."""
        model = AliTTSModel(qwen_config)
        assert model.config == qwen_config
        assert model._is_realtime is True

    def test_init_without_audio_path(self, cosy_config):
        """Test AliTTSModel without audio path."""
        model = AliTTSModel(cosy_config, None)
        assert model.audio_file_path is None

    def test_get_websocket_url_cosyvoice(self, cosy_model):
        """Test get_websocket_url for CosyVoice."""
        url = cosy_model.get_websocket_url()
        assert COSYVOICE_API_URL in url

    def test_get_websocket_url_qwen(self, qwen_model):
        """Test get_websocket_url for Qwen with model param."""
        url = qwen_model.get_websocket_url()
        assert "?" in url
        assert "model=" in url

    def test_get_auth_headers(self, cosy_model):
        """Test get_auth_headers."""
        headers = cosy_model.get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_key"

    def test_cosyvoice_generate_task_id(self, cosy_model):
        """Test _cosyvoice_generate_task_id returns hex string."""
        task_id = cosy_model._cosyvoice_generate_task_id()
        assert isinstance(task_id, str)
        assert len(task_id) == 32

    def test_cosyvoice_construct_run_task_request(self, cosy_model):
        """Test _cosyvoice_construct_run_task_request."""
        task_id = "test_task_123"
        request = cosy_model._cosyvoice_construct_run_task_request(task_id)

        assert "header" in request
        assert request["header"]["action"] == "run-task"
        assert request["header"]["task_id"] == task_id
        assert request["header"]["streaming"] == "duplex"
        assert "payload" in request
        assert request["payload"]["task"] == "tts"
        assert request["payload"]["function"] == "SpeechSynthesizer"
        assert request["payload"]["model"] == "cosyvoice-v2"
        assert request["payload"]["parameters"]["voice"] == "longxiaochun_v2"

    def test_cosyvoice_construct_continue_request(self, cosy_model):
        """Test _cosyvoice_construct_continue_request."""
        task_id = "task_456"
        text = "Hello world"
        request = cosy_model._cosyvoice_construct_continue_request(task_id, text)

        assert request["header"]["action"] == "continue-task"
        assert request["header"]["task_id"] == task_id
        assert request["payload"]["input"]["text"] == text

    def test_cosyvoice_construct_finish_request(self, cosy_model):
        """Test _cosyvoice_construct_finish_request."""
        task_id = "task_789"
        request = cosy_model._cosyvoice_construct_finish_request(task_id)

        assert request["header"]["action"] == "finish-task"
        assert request["header"]["task_id"] == task_id

    def test_cosyvoice_parse_event_task_started(self, cosy_model):
        """Test _cosyvoice_parse_event with task-started."""
        message = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        event = cosy_model._cosyvoice_parse_event(message)
        assert event["type"] == "task-started"
        assert event["task_id"] == "task_1"

    def test_cosyvoice_parse_event_task_finished(self, cosy_model):
        """Test _cosyvoice_parse_event with task-finished."""
        message = json.dumps({
            "header": {"event": "task-finished", "task_id": "task_2"},
            "payload": {"usage": {"characters": 100}}
        })
        event = cosy_model._cosyvoice_parse_event(message)
        assert event["type"] == "task-finished"
        assert event["task_id"] == "task_2"

    def test_cosyvoice_parse_event_task_failed(self, cosy_model):
        """Test _cosyvoice_parse_event with task-failed."""
        message = json.dumps({
            "header": {"event": "task-failed", "task_id": "task_3", "error_code": 500, "error_message": "Service error"}
        })
        event = cosy_model._cosyvoice_parse_event(message)
        assert event["type"] == "task-failed"
        assert event["error_code"] == 500
        assert event["error_message"] == "Service error"

    def test_cosyvoice_parse_event_invalid_json(self, cosy_model):
        """Test _cosyvoice_parse_event with invalid JSON."""
        event = cosy_model._cosyvoice_parse_event("not json")
        assert event["type"] == "unknown"

    def test_qwen_generate_event_id(self, qwen_model):
        """Test _qwen_generate_event_id returns prefixed UUID."""
        event_id = qwen_model._qwen_generate_event_id()
        assert event_id.startswith("event_")
        assert len(event_id) == len("event_") + 16

    def test_qwen_construct_session_update(self, qwen_model):
        """Test _qwen_construct_session_update."""
        qwen_model.config.voice = "Cherry"
        session = qwen_model._qwen_construct_session_update()

        assert session["type"] == "session.update"
        assert "event_id" in session
        assert "session" in session
        assert session["session"]["voice"] == "Cherry"
        assert session["session"]["mode"] == "server_commit"

    def test_qwen_construct_session_update_default_voice(self, qwen_model):
        """Test _qwen_construct_session_update with default voice."""
        qwen_model.config.voice = None
        session = qwen_model._qwen_construct_session_update()
        assert session["session"]["voice"] == "Cherry"

    def test_qwen_format_to_response_format(self, qwen_model):
        """Test _qwen_format_to_response_format."""
        assert qwen_model._qwen_format_to_response_format("mp3") == "mp3"
        assert qwen_model._qwen_format_to_response_format("pcm") == "pcm"
        assert qwen_model._qwen_format_to_response_format("wav") == "wav"
        assert qwen_model._qwen_format_to_response_format("opus") == "opus"
        assert qwen_model._qwen_format_to_response_format("unknown") == "pcm"

    def test_qwen_construct_text_append(self, qwen_model):
        """Test _qwen_construct_text_append."""
        event = qwen_model._qwen_construct_text_append("Hello world")
        assert event["type"] == "input_text_buffer.append"
        assert "event_id" in event
        assert event["text"] == "Hello world"

    def test_qwen_construct_text_commit(self, qwen_model):
        """Test _qwen_construct_text_commit."""
        event = qwen_model._qwen_construct_text_commit()
        assert event["type"] == "input_text_buffer.commit"
        assert "event_id" in event

    def test_qwen_construct_session_finish(self, qwen_model):
        """Test _qwen_construct_session_finish."""
        event = qwen_model._qwen_construct_session_finish()
        assert event["type"] == "session.finish"
        assert "event_id" in event

    def test_qwen_parse_event_session_created(self, qwen_model):
        """Test _qwen_parse_event with session.created."""
        message = '{"type": "session.created"}'
        event = qwen_model._qwen_parse_event(message)
        assert event["type"] == "session.created"

    def test_qwen_parse_event_error(self, qwen_model):
        """Test _qwen_parse_event with error."""
        message = json.dumps({"type": "error", "error": {"code": "invalid_request", "message": "Bad request"}})
        event = qwen_model._qwen_parse_event(message)
        assert event["type"] == "error"
        assert event["error_code"] == "invalid_request"
        assert event["error_message"] == "Bad request"

    def test_qwen_parse_event_invalid_json(self, qwen_model):
        """Test _qwen_parse_event with invalid JSON."""
        event = qwen_model._qwen_parse_event("not json")
        assert event["type"] == "unknown"

    def test_qwen_is_terminal_event_response_done(self, qwen_model):
        """Test _qwen_is_terminal_event with response.done (not terminal)."""
        assert qwen_model._qwen_is_terminal_event("response.done") is False

    def test_qwen_is_terminal_event_response_audio_done(self, qwen_model):
        """Test _qwen_is_terminal_event with response.audio.done."""
        assert qwen_model._qwen_is_terminal_event("response.audio.done") is True

    def test_qwen_is_terminal_event_session_finished(self, qwen_model):
        """Test _qwen_is_terminal_event with session.finished."""
        assert qwen_model._qwen_is_terminal_event("session.finished") is True

    def test_qwen_is_terminal_event_false(self, qwen_model):
        """Test _qwen_is_terminal_event returns False for non-terminal."""
        assert qwen_model._qwen_is_terminal_event("session.created") is False
        assert qwen_model._qwen_is_terminal_event("response.create") is False

    def test_qwen_handle_audio_delta(self, qwen_model):
        """Test _qwen_handle_audio_delta."""
        audio_data = b"test_audio"
        encoded = base64.b64encode(audio_data).decode('utf-8')
        event = {"raw": {"delta": encoded}}

        buffer = bytearray()
        result = qwen_model._qwen_handle_audio_delta(event, buffer, yield_chunks=True)
        assert result == audio_data
        assert buffer == bytearray(audio_data)

    def test_qwen_handle_audio_delta_empty_delta(self, qwen_model):
        """Test _qwen_handle_audio_delta with empty delta."""
        event = {"raw": {"delta": ""}}
        result = qwen_model._qwen_handle_audio_delta(event, None, yield_chunks=True)
        assert result is None

    def test_qwen_handle_audio_delta_with_buffer(self, qwen_model):
        """Test _qwen_handle_audio_delta appends decoded audio to buffer."""
        audio_data = b"test_audio"
        encoded = base64.b64encode(audio_data).decode('utf-8')
        event = {"raw": {"delta": encoded}}

        buffer = bytearray()
        result = qwen_model._qwen_handle_audio_delta(event, buffer, yield_chunks=True)
        assert result == audio_data
        assert buffer == bytearray(audio_data)

    def test_qwen_handle_audio_delta_empty_delta(self, qwen_model):
        """Test _qwen_handle_audio_delta with empty delta."""
        event = {"raw": {"delta": ""}}
        result = qwen_model._qwen_handle_audio_delta(event, None, yield_chunks=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_speech_qwen_non_streaming(self, qwen_model):
        """Test generate_speech for Qwen non-streaming calls the right method."""
        qwen_model._generate_qwen_realtime_non_streaming = AsyncMock(return_value=b"audio_data")
        result = await qwen_model.generate_speech("hello", stream=False)
        assert result == b"audio_data"

    @pytest.mark.asyncio
    async def test_generate_speech_qwen_streaming(self, qwen_model):
        """Test generate_speech for Qwen streaming returns an async generator."""
        async def fake_gen():
            yield b"chunk1"
            yield b"chunk2"
        qwen_model._generate_qwen_realtime_streaming = MagicMock(return_value=fake_gen())
        result = await qwen_model.generate_speech("hello", stream=True)
        chunks = [c async for c in result]
        assert chunks == [b"chunk1", b"chunk2"]

    @pytest.mark.asyncio
    async def test_generate_speech_cosyvoice_non_streaming(self, cosy_model):
        """Test generate_speech for CosyVoice non-streaming."""
        cosy_model._generate_cosyvoice_non_streaming = AsyncMock(return_value=b"audio_data")
        result = await cosy_model.generate_speech("hello", stream=False)
        assert result == b"audio_data"

    @pytest.mark.asyncio
    async def test_generate_speech_cosyvoice_streaming(self, cosy_model):
        """Test generate_speech for CosyVoice streaming."""
        async def fake_gen():
            yield b"chunk1"
            yield b"chunk2"
        cosy_model._generate_cosyvoice_streaming = MagicMock(return_value=fake_gen())
        result = await cosy_model.generate_speech("hello", stream=True)
        chunks = [c async for c in result]
        assert chunks == [b"chunk1", b"chunk2"]

    def test_is_tts_result_successful_valid(self, cosy_model):
        """Test _is_tts_result_successful with valid result."""
        assert cosy_model._is_tts_result_successful(b"audio_data") is True

    def test_is_tts_result_successful_empty(self, cosy_model):
        """Test _is_tts_result_successful with empty result."""
        assert cosy_model._is_tts_result_successful(b"") is False
        assert cosy_model._is_tts_result_successful(None) is False

    def test_log_error_diagnostics_418(self, cosy_model):
        """Test _log_error_diagnostics with voice compatibility error."""
        cosy_model._log_error_diagnostics("Error 418: voice not found")

    def test_log_error_diagnostics_1007(self, cosy_model):
        """Test _log_error_diagnostics with protocol mismatch."""
        cosy_model._log_error_diagnostics("Error 1007: protocol mismatch")

    def test_log_error_diagnostics_auth(self, cosy_model):
        """Test _log_error_diagnostics with auth error."""
        cosy_model._log_error_diagnostics("Error 401: unauthorized")

    def test_log_error_diagnostics_task_session(self, cosy_model):
        """Test _log_error_diagnostics with task/session error."""
        cosy_model._log_error_diagnostics("Error: task-started timeout")

    def test_extract_tts_error_message(self, cosy_model):
        """Test _extract_tts_error_message."""
        msg = cosy_model._extract_tts_error_message(b"error message")
        assert "error message" in msg


class TestAliTTSCosyVoiceAsync:
    """Test CosyVoice async methods in AliTTSModel."""

    @pytest.fixture
    def cosy_config(self):
        """Create a CosyVoice config."""
        return AliTTSConfig(api_key="test_key", model="cosyvoice-v2", voice="longxiaochun_v2")

    @pytest.fixture
    def cosy_model(self, cosy_config):
        """Create a CosyVoice model instance."""
        return AliTTSModel(cosy_config)

    @pytest.mark.asyncio
    async def test_cosyvoice_wait_for_task_started_success(self, cosy_model):
        """Test _cosyvoice_wait_for_task_started with successful task start."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-started", "task_id": "task_1"}}),
        ])

        result = await cosy_model._cosyvoice_wait_for_task_started(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_cosyvoice_wait_for_task_started_failure(self, cosy_model):
        """Test _cosyvoice_wait_for_task_started with task failure."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-failed", "error_message": "Task failed"}}),
        ])

        with pytest.raises(AliTTSError):
            await cosy_model._cosyvoice_wait_for_task_started(mock_ws)

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_binary(self, cosy_model):
        """Test _cosyvoice_receive_audio with binary audio data."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"audio_chunk_1",
            b"audio_chunk_2",
            json.dumps({"header": {"event": "task-finished"}}),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in cosy_model._cosyvoice_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert len(buffer) > 0

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_timeout(self, cosy_model):
        """Test _cosyvoice_receive_audio with timeout."""
        import asyncio

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"audio_chunk",
            asyncio.TimeoutError(),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in cosy_model._cosyvoice_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_task_failed(self, cosy_model):
        """Test _cosyvoice_receive_audio with task-failed event."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-failed", "error_message": "Task failed"}}),
        ])

        with pytest.raises(AliTTSError):
            async for _ in cosy_model._cosyvoice_receive_audio(mock_ws):
                pass

    @pytest.mark.asyncio
    async def test_generate_cosyvoice_non_streaming_success(self, cosy_model):
        """Test _generate_cosyvoice_non_streaming with successful response."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-started"}}),
            b"audio_data",
            json.dumps({"header": {"event": "task-finished"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            result = await cosy_model._generate_cosyvoice_non_streaming(
                "Hello", "wss://example.com", {"Authorization": "Bearer test"}
            )

        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_generate_cosyvoice_non_streaming_error(self, cosy_model):
        """Test _generate_cosyvoice_non_streaming with AliTTSError."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-failed", "error_message": "Task failed"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            with pytest.raises(AliTTSError):
                await cosy_model._generate_cosyvoice_non_streaming(
                    "Hello", "wss://example.com", {"Authorization": "Bearer test"}
                )

    @pytest.mark.asyncio
    async def test_generate_cosyvoice_streaming_success(self, cosy_model):
        """Test _generate_cosyvoice_streaming with successful response."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-started"}}),
            b"audio_chunk",
            json.dumps({"header": {"event": "task-finished"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            chunks = []
            async for chunk in cosy_model._generate_cosyvoice_streaming(
                "Hello", "wss://example.com", {"Authorization": "Bearer test"}
            ):
                chunks.append(chunk)

        assert len(chunks) >= 1


class TestAliTTSQwenAsync:
    """Test Qwen Realtime async methods in AliTTSModel."""

    @pytest.fixture
    def qwen_config(self):
        """Create a Qwen Realtime config."""
        return AliTTSConfig(api_key="test_key", model="qwen-tts", voice="Cherry")

    @pytest.fixture
    def qwen_model(self, qwen_config):
        """Create a Qwen Realtime model instance."""
        return AliTTSModel(qwen_config)

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_success(self, qwen_model):
        """Test _qwen_wait_for_session_created with successful session."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created"}),
        ])

        result = await qwen_model._qwen_wait_for_session_created(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_error(self, qwen_model):
        """Test _qwen_wait_for_session_created with error."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "error", "error": {"message": "Session error"}}),
        ])

        with pytest.raises(AliTTSError):
            await qwen_model._qwen_wait_for_session_created(mock_ws)

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_with_delta(self, qwen_model):
        """Test _qwen_receive_audio with audio delta events."""
        audio_data = b"test_audio"
        encoded = base64.b64encode(audio_data).decode('utf-8')

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "response.audio.delta", "delta": encoded}),
            json.dumps({"type": "session.finished"}),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in qwen_model._qwen_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0] == audio_data
        assert len(buffer) == len(audio_data)

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_binary(self, qwen_model):
        """Test _qwen_receive_audio with binary data."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"binary_audio",
            json.dumps({"type": "response.audio.done"}),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in qwen_model._qwen_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0] == b"binary_audio"

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_error(self, qwen_model):
        """Test _qwen_receive_audio with error event."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "error", "error": {"message": "Service error"}}),
        ])

        with pytest.raises(AliTTSError):
            async for _ in qwen_model._qwen_receive_audio(mock_ws):
                pass

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_timeout(self, qwen_model):
        """Test _qwen_receive_audio with timeout."""
        import asyncio

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(b"chunk").decode()}),
            asyncio.TimeoutError(),
        ])

        chunks = []
        async for chunk in qwen_model._qwen_receive_audio(mock_ws, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_generate_qwen_realtime_non_streaming_success(self, qwen_model):
        """Test _generate_qwen_realtime_non_streaming with successful response."""
        audio_data = b"test_audio"
        encoded = base64.b64encode(audio_data).decode('utf-8')

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created"}),
            json.dumps({"type": "response.audio.delta", "delta": encoded}),
            json.dumps({"type": "response.audio.done"}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            result = await qwen_model._generate_qwen_realtime_non_streaming(
                "Hello", "wss://example.com", {"Authorization": "Bearer test"}
            )

        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_generate_qwen_realtime_non_streaming_error(self, qwen_model):
        """Test _generate_qwen_realtime_non_streaming with AliTTSError."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "error", "error": {"message": "Session error"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            with pytest.raises(AliTTSError):
                await qwen_model._generate_qwen_realtime_non_streaming(
                    "Hello", "wss://example.com", {"Authorization": "Bearer test"}
                )

    @pytest.mark.asyncio
    async def test_generate_qwen_realtime_streaming_success(self, qwen_model):
        """Test _generate_qwen_realtime_streaming with successful response."""
        audio_data = b"test_audio"
        encoded = base64.b64encode(audio_data).decode('utf-8')

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created"}),
            json.dumps({"type": "response.audio.delta", "delta": encoded}),
            json.dumps({"type": "response.audio.done"}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            chunks = []
            async for chunk in qwen_model._generate_qwen_realtime_streaming(
                "Hello", "wss://example.com", {"Authorization": "Bearer test"}
            ):
                chunks.append(chunk)

        assert len(chunks) >= 1


class TestAliTTSConnectivity:
    """Test connectivity check methods in AliTTSModel."""

    @pytest.fixture
    def cosy_config(self):
        """Create a CosyVoice config."""
        return AliTTSConfig(api_key="test_key", model="cosyvoice-v2", voice="longxiaochun_v2")

    @pytest.fixture
    def qwen_config(self):
        """Create a Qwen Realtime config."""
        return AliTTSConfig(api_key="test_key", model="qwen-tts", voice="Cherry")

    @pytest.fixture
    def cosy_model(self, cosy_config):
        """Create a CosyVoice model instance."""
        return AliTTSModel(cosy_config)

    @pytest.fixture
    def qwen_model(self, qwen_config):
        """Create a Qwen Realtime model instance."""
        return AliTTSModel(qwen_config)

    @pytest.mark.asyncio
    async def test_check_connectivity_cosyvoice_success(self, cosy_model):
        """Test check_connectivity for CosyVoice with successful response."""
        cosy_model._generate_cosyvoice_non_streaming = AsyncMock(return_value=b"audio_data")
        result = await cosy_model.check_connectivity()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_qwen_success(self, qwen_model):
        """Test check_connectivity for Qwen with successful response."""
        qwen_model._generate_qwen_realtime_non_streaming = AsyncMock(return_value=b"audio_data")
        result = await qwen_model.check_connectivity()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_failure(self, cosy_model):
        """Test check_connectivity with failure."""
        cosy_model._generate_cosyvoice_non_streaming = AsyncMock(return_value=b"")
        result = await cosy_model.check_connectivity()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_error(self, cosy_model):
        """Test check_connectivity with AliTTSError."""
        cosy_model._generate_cosyvoice_non_streaming = AsyncMock(
            side_effect=AliTTSError("Service error")
        )
        result = await cosy_model.check_connectivity()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_exception(self, cosy_model):
        """Test check_connectivity with general exception."""
        cosy_model._generate_cosyvoice_non_streaming = AsyncMock(
            side_effect=Exception("Network error")
        )
        result = await cosy_model.check_connectivity()
        assert result is False


class TestAliTTSConstants:
    """Test module constants."""

    def test_cosyvoice_api_url(self):
        """Test COSYVOICE_API_URL constant."""
        assert "dashscope.aliyuncs.com" in COSYVOICE_API_URL
        assert "inference" in COSYVOICE_API_URL

    def test_qwen_realtime_api_url(self):
        """Test QWEN_REALTIME_API_URL constant."""
        assert "dashscope.aliyuncs.com" in QWEN_REALTIME_API_URL
        assert "realtime" in QWEN_REALTIME_API_URL.lower()


class TestAliTTSModelAdditional:
    """Additional tests for AliTTSModel edge cases."""

    @pytest.fixture
    def cosy_config(self):
        """Create a CosyVoice config."""
        return AliTTSConfig(api_key="test_key", model="cosyvoice-v2", voice="longxiaochun_v2")

    @pytest.fixture
    def qwen_config(self):
        """Create a Qwen Realtime config."""
        return AliTTSConfig(api_key="test_key", model="qwen-tts", voice="Cherry")

    @pytest.fixture
    def cosy_model(self, cosy_config):
        """Create a CosyVoice model instance."""
        return AliTTSModel(cosy_config)

    @pytest.fixture
    def qwen_model(self, qwen_config):
        """Create a Qwen Realtime model instance."""
        return AliTTSModel(qwen_config)

    def test_get_api_url_with_realtime_in_model(self, qwen_config):
        """Test get_api_url when model name contains qwen but URL is not set."""
        config = AliTTSConfig(api_key="key", model="qwen-tts-v1", ws_url=None)
        assert "/realtime" in config.get_api_url()

    def test_get_websocket_url_cosyvoice_no_params(self, cosy_model):
        """Test get_websocket_url for CosyVoice without query params."""
        url = cosy_model.get_websocket_url()
        assert "dashscope" in url
        assert "?" not in url

    def test_get_websocket_url_qwen_with_existing_params(self, qwen_model):
        """Test get_websocket_url for Qwen when URL already has params."""
        qwen_model.config.ws_url = "wss://example.com/realtime?other=param"
        url = qwen_model.get_websocket_url()
        assert "other=param" in url
        assert "model=" in url

    def test_cosyvoice_parse_event_task_started_with_chars(self, cosy_model):
        """Test _cosyvoice_parse_event with task-finished containing usage."""
        message = json.dumps({
            "header": {"event": "task-finished", "task_id": "task_1"},
            "payload": {"usage": {"characters": 500}}
        })
        event = cosy_model._cosyvoice_parse_event(message)
        assert event["type"] == "task-finished"
        assert event["characters"] == 500

    def test_cosyvoice_parse_event_task_finished_no_usage(self, cosy_model):
        """Test _cosyvoice_parse_event with task-finished but no usage."""
        message = json.dumps({
            "header": {"event": "task-finished", "task_id": "task_1"},
            "payload": {}
        })
        event = cosy_model._cosyvoice_parse_event(message)
        assert event["type"] == "task-finished"
        assert event.get("characters") is None

    def test_qwen_parse_event_with_raw_data(self, qwen_model):
        """Test _qwen_parse_event extracts raw data."""
        message = json.dumps({
            "type": "session.created",
            "session": {"id": "sess_123"}
        })
        event = qwen_model._qwen_parse_event(message)
        assert event["type"] == "session.created"
        assert "raw" in event

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_response_done(self, qwen_model):
        """Test _qwen_receive_audio with response.done event (not terminal)."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "response.done"}),
            json.dumps({"type": "response.audio.done"}),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in qwen_model._qwen_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_error_with_code(self, qwen_model):
        """Test _qwen_receive_audio with error event containing code."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "error", "error": {"code": "INVALID_REQUEST", "message": "Bad request"}}),
        ])

        with pytest.raises(AliTTSError):
            async for _ in qwen_model._qwen_receive_audio(mock_ws, yield_chunks=True):
                pass

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_empty_buffer(self, cosy_model):
        """Test _cosyvoice_receive_audio with timeout but empty buffer."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            asyncio.TimeoutError(),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in cosy_model._cosyvoice_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_binary_and_event(self, cosy_model):
        """Test _cosyvoice_receive_audio with mixed binary and event messages."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"first_chunk",
            json.dumps({"header": {"event": "task-started"}}),
            b"second_chunk",
            json.dumps({"header": {"event": "task-finished"}}),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in cosy_model._cosyvoice_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert b"first_chunk" in buffer
        assert b"second_chunk" in buffer

    @pytest.mark.asyncio
    async def test_generate_cosyvoice_non_streaming_empty_audio(self, cosy_model):
        """Test _generate_cosyvoice_non_streaming when no audio is received."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-started"}}),
            json.dumps({"header": {"event": "task-finished"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            result = await cosy_model._generate_cosyvoice_non_streaming(
                "Hello", "wss://example.com", {"Authorization": "Bearer test"}
            )

        assert result == b""

    @pytest.mark.asyncio
    async def test_generate_cosyvoice_non_streaming_generic_exception(self, cosy_model):
        """Test _generate_cosyvoice_non_streaming with generic exception."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-started"}}),
            json.dumps({"header": {"event": "task-finished"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Generic error"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            with pytest.raises(Exception):
                await cosy_model._generate_cosyvoice_non_streaming(
                    "Hello", "wss://example.com", {"Authorization": "Bearer test"}
                )

    @pytest.mark.asyncio
    async def test_generate_cosyvoice_streaming_with_exception(self, cosy_model):
        """Test _generate_cosyvoice_streaming with generic exception."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"header": {"event": "task-started"}}),
            json.dumps({"header": {"event": "task-finished"}}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            with pytest.raises(Exception):
                async for _ in cosy_model._generate_cosyvoice_streaming(
                    "Hello", "wss://example.com", {"Authorization": "Bearer test"}
                ):
                    pass

    @pytest.mark.asyncio
    async def test_generate_qwen_realtime_non_streaming_empty_audio(self, qwen_model):
        """Test _generate_qwen_realtime_non_streaming when no audio is received."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created"}),
            json.dumps({"type": "response.audio.done"}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            result = await qwen_model._generate_qwen_realtime_non_streaming(
                "Hello", "wss://example.com", {"Authorization": "Bearer test"}
            )

        assert result == b""

    @pytest.mark.asyncio
    async def test_generate_qwen_realtime_non_streaming_generic_exception(self, qwen_model):
        """Test _generate_qwen_realtime_non_streaming with generic exception."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created"}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            with pytest.raises(Exception):
                await qwen_model._generate_qwen_realtime_non_streaming(
                    "Hello", "wss://example.com", {"Authorization": "Bearer test"}
                )

    @pytest.mark.asyncio
    async def test_generate_qwen_realtime_streaming_generic_exception(self, qwen_model):
        """Test _generate_qwen_realtime_streaming with generic exception."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "session.created"}),
        ])
        mock_ws.send = AsyncMock()

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch("websockets.connect", return_value=mock_connect):
            with pytest.raises(Exception):
                async for _ in qwen_model._generate_qwen_realtime_streaming(
                    "Hello", "wss://example.com", {"Authorization": "Bearer test"}
                ):
                    pass

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_session_finished_terminal(self, qwen_model):
        """Test _qwen_receive_audio with session.finished (terminal event)."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(b"chunk").decode()}),
            json.dumps({"type": "session.finished"}),
        ])

        chunks = []
        buffer = bytearray()
        async for chunk in qwen_model._qwen_receive_audio(mock_ws, buffer=buffer, yield_chunks=True):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert b"chunk" in buffer

    def test_log_error_diagnostics_unknown(self, cosy_model):
        """Test _log_error_diagnostics with unknown error."""
        cosy_model._log_error_diagnostics("Unknown error message")

    def test_is_tts_result_successful_with_error_dict(self, cosy_model):
        """Test _is_tts_result_successful with error in dict."""
        assert cosy_model._is_tts_result_successful({"error": "Failed"}) is False

    def test_is_tts_result_successful_with_audio_key(self, cosy_model):
        """Test _is_tts_result_successful with audio key in dict."""
        assert cosy_model._is_tts_result_successful({"audio": "data"}) is True

    def test_is_tts_result_successful_with_text_key(self, cosy_model):
        """Test _is_tts_result_successful with text key in dict."""
        assert cosy_model._is_tts_result_successful({"text": "speech"}) is True

    def test_extract_tts_error_message_from_dict(self, cosy_model):
        """Test _extract_tts_error_message with dict containing message."""
        msg = cosy_model._extract_tts_error_message({"message": "Custom message"})
        assert "Custom message" in msg

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_with_bytes(self, qwen_model):
        """Test _qwen_wait_for_session_created skips binary messages."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"binary_data",
            json.dumps({"type": "session.created"}),
        ])

        result = await qwen_model._qwen_wait_for_session_created(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_error_code(self, qwen_model):
        """Test _qwen_wait_for_session_created extracts error code."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "error", "error": {"code": "AUTH_FAILED", "message": "Auth error"}}),
        ])

        with pytest.raises(AliTTSError) as exc_info:
            await qwen_model._qwen_wait_for_session_created(mock_ws)
        assert "AUTH_FAILED" in str(exc_info.value) or "Auth error" in str(exc_info.value)

    def test_qwen_parse_event_unknown_type(self, qwen_model):
        """Test _qwen_parse_event with unknown event type."""
        message = json.dumps({"type": "unknown.event"})
        event = qwen_model._qwen_parse_event(message)
        assert event["type"] == "unknown.event"

    @pytest.mark.asyncio
    async def test_cosyvoice_wait_for_task_started_with_bytes(self, cosy_model):
        """Test _cosyvoice_wait_for_task_started skips binary messages."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"binary_data",
            json.dumps({"header": {"event": "task-started"}}),
        ])

        result = await cosy_model._cosyvoice_wait_for_task_started(mock_ws)
        assert result is True
