"""
Unit tests for Ali TTS model.

Tests the AliTTSModel and AliTTSConfig classes.
"""
import pytest
import asyncio
import base64
import json
import os
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
    mock_file.read = AsyncMock(return_value=b"mock_audio_data")
    return _MockAsyncContextManager(mock_file)


_mock_aiofiles.open = _mock_aiofiles_open

_module_mocks = {
    "websockets": _mock_websockets,
    "aiofiles": _mock_aiofiles,
}

with patch.dict(_sys.modules, _module_mocks):
    from sdk.nexent.core.models.ali_tts_model import (
        AliTTSModel,
        AliTTSConfig,
        AliTTSError,
        DEFAULT_WS_OPEN_TIMEOUT,
        DEFAULT_WS_CLOSE_TIMEOUT,
        COSYVOICE_API_URL,
        QWEN_REALTIME_API_URL,
    )
    _ali_tts_module = _sys.modules[AliTTSModel.__module__]

_ali_tts_module.websockets = _mock_websockets


# ============================================================================
# AliTTSConfig Tests
# ============================================================================

class TestAliTTSConfig:
    """Tests for AliTTSConfig."""

    def test_config_init_default_values(self):
        """Test config initialization with default values."""
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

    def test_config_init_custom_values(self):
        """Test config initialization with custom values."""
        config = AliTTSConfig(
            api_key="custom_key",
            model="qwen-tts",
            voice="azure_stefanie",
            speech_rate=1.5,
            pitch_rate=0.9,
            volume=75.0,
            ws_url="wss://custom.url/ws",
            format="pcm",
            sample_rate=24000,
            workspace_id="ws_123",
        )
        assert config.api_key == "custom_key"
        assert config.model == "qwen-tts"
        assert config.voice == "azure_stefanie"
        assert config.speech_rate == 1.5
        assert config.pitch_rate == 0.9
        assert config.volume == 75.0
        assert config.ws_url == "wss://custom.url/ws"
        assert config.format == "pcm"
        assert config.sample_rate == 24000
        assert config.workspace_id == "ws_123"

    def test_is_realtime_api_true_when_realtime_in_url(self):
        """Test is_realtime_api returns True for /realtime in URL."""
        config = AliTTSConfig(api_key="key", ws_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        assert config.is_realtime_api() is True

    def test_is_realtime_api_false_when_no_realtime(self):
        """Test is_realtime_api returns False when URL is CosyVoice."""
        config = AliTTSConfig(api_key="key", ws_url="wss://dashscope.aliyuncs.com/api-ws/v1/inference")
        assert config.is_realtime_api() is False

    def test_is_realtime_api_false_when_no_ws_url(self):
        """Test is_realtime_api returns False when ws_url is None."""
        config = AliTTSConfig(api_key="key")
        assert config.is_realtime_api() is False

    def test_is_realtime_api_false_when_empty_ws_url(self):
        """Test is_realtime_api returns False when ws_url is empty."""
        config = AliTTSConfig(api_key="key", ws_url="")
        assert config.is_realtime_api() is False

    def test_get_api_url_with_explicit_ws_url(self):
        """Test get_api_url returns explicit ws_url when set."""
        config = AliTTSConfig(api_key="key", ws_url="wss://custom.url/api")
        assert config.get_api_url() == "wss://custom.url/api"

    def test_get_api_url_returns_qwen_when_in_model_name(self):
        """Test get_api_url returns Qwen URL when qwen in model name."""
        config = AliTTSConfig(api_key="key", model="qwen-tts-v1")
        assert config.get_api_url() == QWEN_REALTIME_API_URL

    def test_get_api_url_returns_qwen_when_realtime_flag(self):
        """Test get_api_url returns custom URL when ws_url is explicitly set."""
        config = AliTTSConfig(api_key="key", ws_url="wss://example.com/realtime")
        assert config.get_api_url() == "wss://example.com/realtime"

    def test_get_api_url_returns_cosyvoice_default(self):
        """Test get_api_url returns CosyVoice URL as default."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        assert config.get_api_url() == COSYVOICE_API_URL

    def test_get_api_url_returns_cosyvoice_for_other_models(self):
        """Test get_api_url returns CosyVoice URL for non-qwen models."""
        config = AliTTSConfig(api_key="key", model="some-other-model")
        assert config.get_api_url() == COSYVOICE_API_URL


# ============================================================================
# AliTTSModel Constants Tests
# ============================================================================

class TestAliTTSModelConstants:
    """Tests for AliTTSModel module constants."""

    def test_default_ws_open_timeout(self):
        """Test DEFAULT_WS_OPEN_TIMEOUT constant."""
        assert DEFAULT_WS_OPEN_TIMEOUT == 60

    def test_default_ws_close_timeout(self):
        """Test DEFAULT_WS_CLOSE_TIMEOUT constant."""
        assert DEFAULT_WS_CLOSE_TIMEOUT == 10

    def test_cosyvoice_api_url(self):
        """Test COSYVOICE_API_URL constant."""
        assert COSYVOICE_API_URL == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"

    def test_qwen_realtime_api_url(self):
        """Test QWEN_REALTIME_API_URL constant."""
        assert QWEN_REALTIME_API_URL == "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

    def test_ali_tts_error(self):
        """Test AliTTSError exception."""
        err = AliTTSError("Test error message")
        assert err.message == "Test error message"
        assert str(err) == "Test error message"


# ============================================================================
# AliTTSModel Constructor Tests
# ============================================================================

class TestAliTTSModelConstructor:
    """Tests for AliTTSModel constructor and initialization."""

    def test_model_init_cosyvoice(self):
        """Test model initialization with CosyVoice model."""
        config = AliTTSConfig(api_key="test_key", model="cosyvoice-v2")
        model = AliTTSModel(config)
        assert model.config is config
        assert model._is_realtime is False

    def test_model_init_qwen(self):
        """Test model initialization with Qwen model."""
        config = AliTTSConfig(api_key="test_key", model="qwen-tts-v1")
        model = AliTTSModel(config)
        assert model._is_realtime is True

    def test_model_init_with_realtime_url(self):
        """Test model initialization with realtime URL."""
        config = AliTTSConfig(api_key="test_key", ws_url="wss://example.com/realtime")
        model = AliTTSModel(config)
        assert model._is_realtime is True

    def test_model_init_with_audio_file_path(self):
        """Test model initialization with audio file path."""
        config = AliTTSConfig(api_key="test_key")
        model = AliTTSModel(config, audio_file_path="/path/to/audio.mp3")
        assert model.audio_file_path == "/path/to/audio.mp3"


# ============================================================================
# AliTTSModel URL and Auth Tests
# ============================================================================

class TestAliTTSModelUrlAndAuth:
    """Tests for get_websocket_url and get_auth_headers methods."""

    def test_get_websocket_url_cosyvoice(self):
        """Test get_websocket_url returns base URL for CosyVoice."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)
        assert model.get_websocket_url() == COSYVOICE_API_URL

    def test_get_websocket_url_qwen_with_model_param(self):
        """Test get_websocket_url appends model param for Qwen."""
        config = AliTTSConfig(api_key="key", model="qwen-tts-v1")
        model = AliTTSModel(config)
        url = model.get_websocket_url()
        assert url.startswith(QWEN_REALTIME_API_URL)
        assert "model=qwen-tts-v1" in url

    def test_get_websocket_url_with_explicit_ws_url_no_question_mark(self):
        """Test get_websocket_url uses ? when no query in explicit URL."""
        config = AliTTSConfig(api_key="key", ws_url="wss://example.com/realtime")
        model = AliTTSModel(config)
        url = model.get_websocket_url()
        assert "?" in url
        assert "model=" in url

    def test_get_websocket_url_with_explicit_ws_url_with_question_mark(self):
        """Test get_websocket_url uses & when query already in explicit URL."""
        config = AliTTSConfig(api_key="key", ws_url="wss://example.com/realtime?existing=param")
        model = AliTTSModel(config)
        url = model.get_websocket_url()
        assert "&model=" in url

    def test_get_auth_headers(self):
        """Test get_auth_headers returns Bearer token."""
        config = AliTTSConfig(api_key="my_secret_key")
        model = AliTTSModel(config)
        headers = model.get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my_secret_key"


# ============================================================================
# AliTTSModel CosyVoice Request Construction Tests
# ============================================================================

class TestAliTTSModelCosyVoiceRequestConstruction:
    """Tests for CosyVoice request construction methods."""

    def test_cosyvoice_generate_task_id(self):
        """Test _cosyvoice_generate_task_id generates valid UUID."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        task_id = model._cosyvoice_generate_task_id()
        assert isinstance(task_id, str)
        assert len(task_id) == 32

    def test_cosyvoice_generate_task_id_unique(self):
        """Test _cosyvoice_generate_task_id generates unique IDs."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        ids = [model._cosyvoice_generate_task_id() for _ in range(10)]
        assert len(set(ids)) == 10

    def test_cosyvoice_construct_run_task_request(self):
        """Test _cosyvoice_construct_run_task_request structure."""
        config = AliTTSConfig(
            api_key="key",
            model="cosyvoice-v2",
            voice="af_abella",
            format="mp3",
            sample_rate=16000,
            volume=60.0,
            speech_rate=1.2,
            pitch_rate=0.9,
        )
        model = AliTTSModel(config)
        task_id = "test_task_123"
        request = model._cosyvoice_construct_run_task_request(task_id)

        assert request["header"]["action"] == "run-task"
        assert request["header"]["task_id"] == task_id
        assert request["header"]["streaming"] == "duplex"
        assert request["payload"]["task_group"] == "audio"
        assert request["payload"]["task"] == "tts"
        assert request["payload"]["function"] == "SpeechSynthesizer"
        assert request["payload"]["model"] == "cosyvoice-v2"
        assert request["payload"]["parameters"]["text_type"] == "PlainText"
        assert request["payload"]["parameters"]["voice"] == "af_abella"
        assert request["payload"]["parameters"]["format"] == "mp3"
        assert request["payload"]["parameters"]["sample_rate"] == 16000
        assert request["payload"]["parameters"]["volume"] == 60
        assert request["payload"]["parameters"]["rate"] == 1.2
        assert request["payload"]["parameters"]["pitch"] == 0.9
        assert request["payload"]["parameters"]["enable_ssml"] is False

    def test_cosyvoice_construct_continue_request(self):
        """Test _cosyvoice_construct_continue_request structure."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        task_id = "task_456"
        text = "Hello world"
        request = model._cosyvoice_construct_continue_request(task_id, text)

        assert request["header"]["action"] == "continue-task"
        assert request["header"]["task_id"] == task_id
        assert request["header"]["streaming"] == "duplex"
        assert request["payload"]["input"]["text"] == text

    def test_cosyvoice_construct_finish_request(self):
        """Test _cosyvoice_construct_finish_request structure."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        task_id = "task_789"
        request = model._cosyvoice_construct_finish_request(task_id)

        assert request["header"]["action"] == "finish-task"
        assert request["header"]["task_id"] == task_id
        assert request["header"]["streaming"] == "duplex"
        assert request["payload"]["input"] == {}


# ============================================================================
# AliTTSModel CosyVoice Event Parsing Tests
# ============================================================================

class TestAliTTSModelCosyVoiceEventParsing:
    """Tests for _cosyvoice_parse_event method."""

    def test_parse_task_started_event(self):
        """Test parsing task-started event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"header": {"event": "task-started", "task_id": "task_123"}})
        result = model._cosyvoice_parse_event(message)
        assert result["type"] == "task-started"
        assert result["task_id"] == "task_123"

    def test_parse_task_failed_event(self):
        """Test parsing task-failed event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({
            "header": {"event": "task-failed", "task_id": "task_123", "error_code": 500, "error_message": "Service error"}
        })
        result = model._cosyvoice_parse_event(message)
        assert result["type"] == "task-failed"
        assert result["task_id"] == "task_123"
        assert result["error_code"] == 500
        assert result["error_message"] == "Service error"

    def test_parse_task_finished_event(self):
        """Test parsing task-finished event with usage info."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({
            "header": {"event": "task-finished", "task_id": "task_456"},
            "payload": {"usage": {"characters": 100}}
        })
        result = model._cosyvoice_parse_event(message)
        assert result["type"] == "task-finished"
        assert result["task_id"] == "task_456"
        assert result["characters"] == 100

    def test_parse_unknown_event(self):
        """Test parsing unknown event type."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"header": {"event": "some-unknown-event", "task_id": "task_789"}})
        result = model._cosyvoice_parse_event(message)
        assert result["type"] == "some-unknown-event"

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON returns unknown type."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        result = model._cosyvoice_parse_event("not valid json {{{")
        assert result["type"] == "unknown"

    def test_parse_event_missing_header(self):
        """Test parsing event without header."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"payload": {"data": "value"}})
        result = model._cosyvoice_parse_event(message)
        assert result["type"] == ""


# ============================================================================
# AliTTSModel Qwen Request Construction Tests
# ============================================================================

class TestAliTTSModelQwenRequestConstruction:
    """Tests for Qwen Realtime API request construction methods."""

    def test_qwen_generate_event_id(self):
        """Test _qwen_generate_event_id generates valid event ID."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        event_id = model._qwen_generate_event_id()
        assert isinstance(event_id, str)
        assert event_id.startswith("event_")
        assert len(event_id) == 22  # "event_" + 16 hex chars

    def test_qwen_generate_event_id_unique(self):
        """Test _qwen_generate_event_id generates unique IDs."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        ids = [model._qwen_generate_event_id() for _ in range(10)]
        assert len(set(ids)) == 10

    def test_qwen_construct_session_update(self):
        """Test _qwen_construct_session_update structure."""
        config = AliTTSConfig(
            api_key="key",
            voice="Cherry",
            format="mp3",
            sample_rate=24000,
            speech_rate=1.5,
            volume=80.0,
        )
        model = AliTTSModel(config)
        request = model._qwen_construct_session_update()

        assert request["type"] == "session.update"
        assert "event_id" in request
        assert request["session"]["voice"] == "Cherry"
        assert request["session"]["mode"] == "server_commit"
        assert request["session"]["language_type"] == "Auto"
        assert request["session"]["response_format"] == "mp3"
        assert request["session"]["sample_rate"] == 24000
        assert request["session"]["speech_rate"] == 1.5
        assert request["session"]["volume"] == 80

    def test_qwen_construct_session_update_uses_default_voice(self):
        """Test _qwen_construct_session_update uses Cherry when voice is None."""
        config = AliTTSConfig(api_key="key", voice=None)
        model = AliTTSModel(config)
        request = model._qwen_construct_session_update()
        assert request["session"]["voice"] == "Cherry"

    def test_qwen_format_to_response_format_mp3(self):
        """Test _qwen_format_to_response_format for mp3."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_format_to_response_format("mp3") == "mp3"

    def test_qwen_format_to_response_format_pcm(self):
        """Test _qwen_format_to_response_format for pcm."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_format_to_response_format("pcm") == "pcm"

    def test_qwen_format_to_response_format_wav(self):
        """Test _qwen_format_to_response_format for wav."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_format_to_response_format("wav") == "wav"

    def test_qwen_format_to_response_format_opus(self):
        """Test _qwen_format_to_response_format for opus."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_format_to_response_format("opus") == "opus"

    def test_qwen_format_to_response_format_unknown(self):
        """Test _qwen_format_to_response_format for unknown format defaults to pcm."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_format_to_response_format("flac") == "pcm"

    def test_qwen_construct_text_append(self):
        """Test _qwen_construct_text_append structure."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        request = model._qwen_construct_text_append("Hello world")
        assert request["type"] == "input_text_buffer.append"
        assert "event_id" in request
        assert request["text"] == "Hello world"

    def test_qwen_construct_text_commit(self):
        """Test _qwen_construct_text_commit structure."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        request = model._qwen_construct_text_commit()
        assert request["type"] == "input_text_buffer.commit"
        assert "event_id" in request

    def test_qwen_construct_session_finish(self):
        """Test _qwen_construct_session_finish structure."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        request = model._qwen_construct_session_finish()
        assert request["type"] == "session.finish"
        assert "event_id" in request


# ============================================================================
# AliTTSModel Qwen Event Parsing Tests
# ============================================================================

class TestAliTTSModelQwenEventParsing:
    """Tests for Qwen event parsing methods."""

    def test_qwen_parse_event_session_created(self):
        """Test parsing session.created event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"type": "session.created", "session_id": "sess_123"})
        result = model._qwen_parse_event(message)
        assert result["type"] == "session.created"
        assert result["raw"]["session_id"] == "sess_123"

    def test_qwen_parse_event_error(self):
        """Test parsing error event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({
            "type": "error",
            "error": {"code": "INVALID_PARAM", "message": "Invalid parameter"}
        })
        result = model._qwen_parse_event(message)
        assert result["type"] == "error"
        assert result["error_code"] == "INVALID_PARAM"
        assert result["error_message"] == "Invalid parameter"

    def test_qwen_parse_event_response_created(self):
        """Test parsing response.created event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"type": "response.created", "response": {"id": "resp_123"}})
        result = model._qwen_parse_event(message)
        assert result["type"] == "response.created"

    def test_qwen_parse_event_response_audio_delta(self):
        """Test parsing response.audio.delta event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        audio_data = base64.b64encode(b"audio_chunk").decode()
        message = json.dumps({"type": "response.audio.delta", "delta": audio_data})
        result = model._qwen_parse_event(message)
        assert result["type"] == "response.audio.delta"
        assert result["raw"]["delta"] == audio_data

    def test_qwen_parse_event_response_audio_done(self):
        """Test parsing response.audio.done event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"type": "response.audio.done"})
        result = model._qwen_parse_event(message)
        assert result["type"] == "response.audio.done"

    def test_qwen_parse_event_session_finished(self):
        """Test parsing session.finished event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        message = json.dumps({"type": "session.finished"})
        result = model._qwen_parse_event(message)
        assert result["type"] == "session.finished"

    def test_qwen_parse_event_invalid_json(self):
        """Test parsing invalid JSON returns unknown type."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        result = model._qwen_parse_event("not json {{{")
        assert result["type"] == "unknown"

    def test_qwen_is_terminal_event_response_audio_done(self):
        """Test _qwen_is_terminal_event returns True for response.audio.done."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_is_terminal_event("response.audio.done") is True

    def test_qwen_is_terminal_event_session_finished(self):
        """Test _qwen_is_terminal_event returns True for session.finished."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_is_terminal_event("session.finished") is True

    def test_qwen_is_terminal_event_false_for_others(self):
        """Test _qwen_is_terminal_event returns False for non-terminal events."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._qwen_is_terminal_event("session.created") is False
        assert model._qwen_is_terminal_event("response.created") is False
        assert model._qwen_is_terminal_event("response.audio.delta") is False

    def test_qwen_handle_audio_delta(self):
        """Test _qwen_handle_audio_delta decodes base64 audio."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        audio_data = base64.b64encode(b"test_audio_chunk").decode()
        event = {"raw": {"delta": audio_data}}
        buffer = bytearray()
        result = model._qwen_handle_audio_delta(event, buffer, yield_chunks=True)
        assert result == b"test_audio_chunk"
        assert buffer == bytearray(b"test_audio_chunk")

    def test_qwen_handle_audio_delta_empty_delta(self):
        """Test _qwen_handle_audio_delta with empty delta."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        event = {"raw": {"delta": ""}}
        buffer = bytearray()
        result = model._qwen_handle_audio_delta(event, buffer, yield_chunks=True)
        assert result is None

    def test_qwen_handle_audio_delta_buffer_only(self):
        """Test _qwen_handle_audio_delta appends to buffer without yielding."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        audio_data = base64.b64encode(b"buffer_only").decode()
        event = {"raw": {"delta": audio_data}}
        buffer = bytearray()
        result = model._qwen_handle_audio_delta(event, buffer, yield_chunks=False)
        assert result is None
        assert buffer == bytearray(b"buffer_only")


# ============================================================================
# AliTTSModel Generate Speech Tests
# ============================================================================

class TestAliTTSModelGenerateSpeech:
    """Tests for generate_speech method."""

    def test_generate_speech_returns_generator_for_qwen_streaming(self):
        """Test generate_speech returns async generator for Qwen streaming."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)
        result = model.generate_speech("Hello", stream=True)
        import inspect
        assert inspect.iscoroutine(result) or inspect.isasyncgenfunction(result)

    def test_generate_speech_returns_generator_for_cosyvoice_streaming(self):
        """Test generate_speech returns async generator for CosyVoice streaming."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)
        result = model.generate_speech("Hello", stream=True)
        import inspect
        assert inspect.iscoroutine(result) or inspect.isasyncgenfunction(result)


# ============================================================================
# AliTTSModel CosyVoice Async Generation Tests
# ============================================================================

class TestAliTTSModelCosyVoiceAsyncGeneration:
    """Tests for CosyVoice async generation methods."""

    @pytest.mark.asyncio
    async def test_cosyvoice_non_streaming_success(self):
        """Test CosyVoice non-streaming generation success.

        The buffer only accumulates bytes messages (actual audio data).
        JSON messages like task-finished don't get added to the buffer.
        """
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        audio_data = b"fake_audio_data"
        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        task_finished_msg = json.dumps({"header": {"event": "task-finished", "task_id": "task_1", "payload": {"usage": {"characters": 10}}}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_started_msg, audio_data, task_finished_msg])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model._generate_cosyvoice_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})
            assert result == audio_data

    @pytest.mark.asyncio
    async def test_cosyvoice_non_streaming_connection_error(self):
        """Test CosyVoice non-streaming with connection error."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(Exception, match="Connection failed"):
                await model._generate_cosyvoice_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})

    @pytest.mark.asyncio
    async def test_cosyvoice_non_streaming_task_failed(self):
        """Test CosyVoice non-streaming with task failure."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        task_failed_msg = json.dumps({
            "header": {"event": "task-failed", "task_id": "task_1", "error_message": "Task failed"}
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_started_msg, task_failed_msg])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(AliTTSError, match="Task failed"):
                await model._generate_cosyvoice_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})

    @pytest.mark.asyncio
    async def test_cosyvoice_non_streaming_timeout(self):
        """Test CosyVoice non-streaming with timeout after task starts.

        When a timeout occurs during audio receiving, the loop breaks and
        returns whatever audio has been accumulated (empty in this case).
        """
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})

        call_count = [0]

        async def recv_with_timeout():
            call_count[0] += 1
            if call_count[0] == 1:
                return task_started_msg
            else:
                raise asyncio.TimeoutError

        mock_ws = AsyncMock()
        mock_ws.recv = recv_with_timeout

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model._generate_cosyvoice_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})
            assert result == b""

    @pytest.mark.asyncio
    async def test_cosyvoice_streaming_success(self):
        """Test CosyVoice streaming generation success.

        Bytes chunks are yielded as audio data. JSON messages don't get yielded.
        Audio chunks should come before task-finished for proper streaming.
        """
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        audio_chunks = [b"chunk1", b"chunk2", b"chunk3"]
        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        task_finished_msg = json.dumps({"header": {"event": "task-finished", "task_id": "task_1"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            task_started_msg,
            audio_chunks[0],
            audio_chunks[1],
            audio_chunks[2],
            task_finished_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            chunks = []
            async for chunk in model._generate_cosyvoice_streaming("Hello", "wss://test", {"Authorization": "Bearer key"}):
                chunks.append(chunk)
            assert chunks == audio_chunks


# ============================================================================
# AliTTSModel Qwen Realtime Async Generation Tests
# ============================================================================

class TestAliTTSModelQwenRealtimeAsyncGeneration:
    """Tests for Qwen Realtime API async generation methods."""

    @pytest.mark.asyncio
    async def test_qwen_non_streaming_success(self):
        """Test Qwen Realtime non-streaming generation success."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        audio_data = base64.b64encode(b"qwen_audio").decode()
        session_created_msg = json.dumps({"type": "session.created"})
        response_created_msg = json.dumps({"type": "response.created"})
        audio_delta_msg = json.dumps({"type": "response.audio.delta", "delta": audio_data})
        audio_done_msg = json.dumps({"type": "response.audio.done"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            session_created_msg,
            response_created_msg,
            audio_delta_msg,
            audio_done_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model._generate_qwen_realtime_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})
            assert result == b"qwen_audio"

    @pytest.mark.asyncio
    async def test_qwen_non_streaming_session_error(self):
        """Test Qwen Realtime non-streaming with session error."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        error_msg = json.dumps({"type": "error", "error": {"message": "Session error"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[error_msg])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(AliTTSError, match="Session error"):
                await model._generate_qwen_realtime_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})

    @pytest.mark.asyncio
    async def test_qwen_non_streaming_connection_error(self):
        """Test Qwen Realtime non-streaming with connection error."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=Exception("Connection failed"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(Exception, match="Connection failed"):
                await model._generate_qwen_realtime_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})

    @pytest.mark.asyncio
    async def test_qwen_non_streaming_empty_audio(self):
        """Test Qwen Realtime non-streaming with no audio data."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        session_created_msg = json.dumps({"type": "session.created"})
        response_created_msg = json.dumps({"type": "response.created"})
        audio_done_msg = json.dumps({"type": "response.audio.done"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            session_created_msg,
            response_created_msg,
            audio_done_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model._generate_qwen_realtime_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})
            assert result == b""

    @pytest.mark.asyncio
    async def test_qwen_non_streaming_multiple_audio_chunks(self):
        """Test Qwen Realtime non-streaming with multiple audio chunks."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        audio1 = base64.b64encode(b"chunk1").decode()
        audio2 = base64.b64encode(b"chunk2").decode()
        session_created_msg = json.dumps({"type": "session.created"})
        response_created_msg = json.dumps({"type": "response.created"})
        audio_delta1 = json.dumps({"type": "response.audio.delta", "delta": audio1})
        audio_delta2 = json.dumps({"type": "response.audio.delta", "delta": audio2})
        audio_done_msg = json.dumps({"type": "response.audio.done"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            session_created_msg,
            response_created_msg,
            audio_delta1,
            audio_delta2,
            audio_done_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model._generate_qwen_realtime_non_streaming("Hello", "wss://test", {"Authorization": "Bearer key"})
            assert result == b"chunk1chunk2"

    @pytest.mark.asyncio
    async def test_qwen_streaming_success(self):
        """Test Qwen Realtime streaming generation success."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        audio1 = base64.b64encode(b"stream1").decode()
        audio2 = base64.b64encode(b"stream2").decode()
        session_created_msg = json.dumps({"type": "session.created"})
        response_created_msg = json.dumps({"type": "response.created"})
        audio_delta1 = json.dumps({"type": "response.audio.delta", "delta": audio1})
        audio_delta2 = json.dumps({"type": "response.audio.delta", "delta": audio2})
        audio_done_msg = json.dumps({"type": "response.audio.done"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            session_created_msg,
            response_created_msg,
            audio_delta1,
            audio_delta2,
            audio_done_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            chunks = []
            async for chunk in model._generate_qwen_realtime_streaming("Hello", "wss://test", {"Authorization": "Bearer key"}):
                chunks.append(chunk)
            assert chunks == [b"stream1", b"stream2"]

    @pytest.mark.asyncio
    async def test_qwen_streaming_error_event(self):
        """Test Qwen Realtime streaming with error event."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        session_created_msg = json.dumps({"type": "session.created"})
        error_msg = json.dumps({"type": "error", "error": {"message": "Streaming error"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[session_created_msg, error_msg])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            with pytest.raises(AliTTSError, match="Streaming error"):
                async for _ in model._generate_qwen_realtime_streaming("Hello", "wss://test", {"Authorization": "Bearer key"}):
                    pass

    @pytest.mark.asyncio
    async def test_qwen_streaming_session_finished_before_response(self):
        """Test Qwen Realtime streaming with session.finished before response.created.

        When session.finished comes before response.created, no audio chunks are yielded.
        The async generator will raise StopAsyncIteration when exhausted.
        """
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        session_created_msg = json.dumps({"type": "session.created"})
        session_finished_msg = json.dumps({"type": "session.finished"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[session_created_msg, session_finished_msg])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            chunks = []
            with pytest.raises(RuntimeError, match="async generator"):
                async for chunk in model._generate_qwen_realtime_streaming("Hello", "wss://test", {"Authorization": "Bearer key"}):
                    chunks.append(chunk)

    @pytest.mark.asyncio
    async def test_qwen_receive_audio_handles_binary_messages(self):
        """Test _qwen_receive_audio passes through binary messages."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        audio_done_msg = json.dumps({"type": "response.audio.done"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"binary_audio_data",
            audio_done_msg,
        ])

        chunks = []
        async for chunk in model._qwen_receive_audio(mock_ws, yield_chunks=True):
            chunks.append(chunk)
        assert chunks == [b"binary_audio_data"]


# ============================================================================
# AliTTSModel Base Class Tests
# ============================================================================

class TestAliTTSModelBaseClass:
    """Tests for base class methods in AliTTSModel."""

    def test_is_tts_result_successful_with_bytes(self):
        """Test _is_tts_result_successful with bytes."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._is_tts_result_successful(b"audio_data") is True
        assert model._is_tts_result_successful(b"") is False

    def test_is_tts_result_successful_with_dict(self):
        """Test _is_tts_result_successful with dict."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._is_tts_result_successful({"audio": "data"}) is True
        assert model._is_tts_result_successful({"text": "result"}) is True
        assert model._is_tts_result_successful({"error": "error"}) is False

    def test_is_tts_result_successful_invalid_types(self):
        """Test _is_tts_result_successful with invalid types."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._is_tts_result_successful(None) is False
        assert model._is_tts_result_successful("string") is False
        assert model._is_tts_result_successful(123) is False

    def test_extract_tts_error_message(self):
        """Test _extract_tts_error_message."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)
        assert model._extract_tts_error_message({"error": "test error"}) == "test error"
        assert model._extract_tts_error_message({"message": "msg error"}) == "msg error"
        assert "Unknown error" in model._extract_tts_error_message({"data": "value"})


# ============================================================================
# AliTTSModel Connectivity Tests
# ============================================================================

class TestAliTTSModelConnectivity:
    """Tests for check_connectivity method."""

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_false_when_no_audio_path(self):
        """Test check_connectivity returns False when no audio_file_path and no speech generated."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)
        model.audio_file_path = None

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        task_finished_msg = json.dumps({"header": {"event": "task-finished", "task_id": "task_1"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_started_msg, task_finished_msg, b""])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_true_with_audio(self):
        """Test check_connectivity returns True when audio is generated."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        task_finished_msg = json.dumps({"header": {"event": "task-finished", "task_id": "task_1"}})
        audio_data = b"some_audio_data"

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            task_started_msg,
            audio_data,
            task_finished_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.check_connectivity()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_false_on_ali_tts_error(self):
        """Test check_connectivity returns False on AliTTSError."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})
        task_failed_msg = json.dumps({
            "header": {"event": "task-failed", "task_id": "task_1", "error_message": "Task failed"}
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_started_msg, task_failed_msg])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_returns_false_on_generic_exception(self):
        """Test check_connectivity returns False on generic exception."""
        config = AliTTSConfig(api_key="key", model="cosyvoice-v2")
        model = AliTTSModel(config)

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(side_effect=RuntimeError("Unexpected error"))
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.check_connectivity()
            assert result is False

    @pytest.mark.asyncio
    async def test_check_connectivity_qwen_realtime(self):
        """Test check_connectivity with Qwen Realtime API."""
        config = AliTTSConfig(api_key="key", model="qwen-tts")
        model = AliTTSModel(config)

        audio_data = base64.b64encode(b"qwen_connectivity_audio").decode()
        session_created_msg = json.dumps({"type": "session.created"})
        response_created_msg = json.dumps({"type": "response.created"})
        audio_delta_msg = json.dumps({"type": "response.audio.delta", "delta": audio_data})
        audio_done_msg = json.dumps({"type": "response.audio.done"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            session_created_msg,
            response_created_msg,
            audio_delta_msg,
            audio_done_msg,
        ])

        mock_connect = AsyncMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.__aexit__ = AsyncMock(return_value=None)

        with patch.object(_mock_websockets, "connect", return_value=mock_connect):
            result = await model.check_connectivity()
            assert result is True


# ============================================================================
# AliTTSModel Async Helper Methods Tests
# ============================================================================

class TestAliTTSModelAsyncHelpers:
    """Tests for async helper methods."""

    @pytest.mark.asyncio
    async def test_cosyvoice_wait_for_task_started_success(self):
        """Test _cosyvoice_wait_for_task_started returns True on task-started."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_started_msg])

        result = await model._cosyvoice_wait_for_task_started(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_cosyvoice_wait_for_task_started_raises_on_failure(self):
        """Test _cosyvoice_wait_for_task_started raises AliTTSError on task-failed."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        task_failed_msg = json.dumps({
            "header": {"event": "task-failed", "task_id": "task_1", "error_message": "Service unavailable"}
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_failed_msg])

        with pytest.raises(AliTTSError, match="Service unavailable"):
            await model._cosyvoice_wait_for_task_started(mock_ws)

    @pytest.mark.asyncio
    async def test_cosyvoice_wait_for_task_started_skips_binary(self):
        """Test _cosyvoice_wait_for_task_started skips binary messages."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        task_started_msg = json.dumps({"header": {"event": "task-started", "task_id": "task_1"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"binary_data",
            task_started_msg,
        ])

        result = await model._cosyvoice_wait_for_task_started(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_success(self):
        """Test _qwen_wait_for_session_created returns True on session.created."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        session_created_msg = json.dumps({"type": "session.created"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[session_created_msg])

        result = await model._qwen_wait_for_session_created(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_raises_on_error(self):
        """Test _qwen_wait_for_session_created raises on error event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        error_msg = json.dumps({"type": "error", "error": {"message": "Session error"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[error_msg])

        with pytest.raises(AliTTSError, match="Session error"):
            await model._qwen_wait_for_session_created(mock_ws)

    @pytest.mark.asyncio
    async def test_qwen_wait_for_session_created_skips_binary(self):
        """Test _qwen_wait_for_session_created skips binary messages."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        session_created_msg = json.dumps({"type": "session.created"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"binary_data",
            b"more_binary",
            session_created_msg,
        ])

        result = await model._qwen_wait_for_session_created(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_qwen_wait_for_response_created_success(self):
        """Test _qwen_wait_for_response_created returns True on response.created."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        response_created_msg = json.dumps({"type": "response.created"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[response_created_msg])

        result = await model._qwen_wait_for_response_created(mock_ws)
        assert result is True

    @pytest.mark.asyncio
    async def test_qwen_wait_for_response_created_raises_on_error(self):
        """Test _qwen_wait_for_response_created raises on error event."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        error_msg = json.dumps({"type": "error", "error": {"message": "Response error"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[error_msg])

        with pytest.raises(AliTTSError, match="Response error"):
            await model._qwen_wait_for_response_created(mock_ws)

    @pytest.mark.asyncio
    async def test_qwen_wait_for_response_created_returns_false_on_session_finished(self):
        """Test _qwen_wait_for_response_created returns False when session finishes early."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        session_finished_msg = json.dumps({"type": "session.finished"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[session_finished_msg])

        result = await model._qwen_wait_for_response_created(mock_ws)
        assert result is False

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_with_buffer(self):
        """Test _cosyvoice_receive_audio accumulates audio in buffer."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        task_finished_msg = json.dumps({"header": {"event": "task-finished", "task_id": "task_1"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"audio_chunk1",
            b"audio_chunk2",
            task_finished_msg,
        ])

        buffer = bytearray()
        received = []
        async for chunk in model._cosyvoice_receive_audio(mock_ws, buffer=buffer, yield_chunks=False):
            received.append(chunk)
        assert buffer == bytearray(b"audio_chunk1audio_chunk2")
        assert received == []

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_yields_chunks(self):
        """Test _cosyvoice_receive_audio yields chunks when requested."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        task_finished_msg = json.dumps({"header": {"event": "task-finished", "task_id": "task_1"}})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[
            b"yield_chunk1",
            b"yield_chunk2",
            task_finished_msg,
        ])

        chunks = []
        async for chunk in model._cosyvoice_receive_audio(mock_ws, yield_chunks=True):
            chunks.append(chunk)
        assert chunks == [b"yield_chunk1", b"yield_chunk2"]

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_task_failed(self):
        """Test _cosyvoice_receive_audio raises on task-failed."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        task_failed_msg = json.dumps({
            "header": {"event": "task-failed", "task_id": "task_1", "error_message": "Task failed"}
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[task_failed_msg])

        with pytest.raises(AliTTSError, match="Task failed"):
            async for _ in model._cosyvoice_receive_audio(mock_ws, yield_chunks=True):
                pass

    @pytest.mark.asyncio
    async def test_cosyvoice_receive_audio_timeout(self):
        """Test _cosyvoice_receive_audio handles timeout."""
        config = AliTTSConfig(api_key="key")
        model = AliTTSModel(config)

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())

        chunks = []
        async for chunk in model._cosyvoice_receive_audio(mock_ws, yield_chunks=True):
            chunks.append(chunk)
        assert chunks == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
