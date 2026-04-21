"""
Unit tests for Ali TTS model.

Tests the AliTTSModel and AliTTSConfig classes.
"""
import pytest
import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import sys as _sys

_mock_websockets = MagicMock()
_mock_websockets.connect = MagicMock()


class _MockConnectionClosedError(Exception):
    pass


_mock_websockets.exceptions.ConnectionClosedError = _MockConnectionClosedError
_mock_websockets.exceptions.WebSocketException = Exception

_module_mocks = {
    "websockets": _mock_websockets,
}

with patch.dict(_sys.modules, _module_mocks):
    from sdk.nexent.core.models.ali_tts_model import (
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
        assert session["session"]["modalities"] == ["text", "audio"]

    def test_qwen_construct_session_update_default_voice(self, qwen_model):
        """Test _qwen_construct_session_update with default voice."""
        qwen_model.config.voice = None
        session = qwen_model._qwen_construct_session_update()
        assert session["session"]["voice"] == "Cherry"

    def test_qwen_construct_response_create(self, qwen_model):
        """Test _qwen_construct_response_create."""
        response_create = qwen_model._qwen_construct_response_create()
        assert response_create["type"] == "response.create"
        assert "event_id" in response_create
        assert response_create["response"]["modalities"] == ["text", "audio"]
        assert response_create["response"]["stream"] is True

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
        """Test _qwen_is_terminal_event with response.done."""
        assert qwen_model._qwen_is_terminal_event("response.done") is True

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

    def test_qwen_handle_response_done_with_audio(self, qwen_model):
        """Test _qwen_handle_response_done with audio in output."""
        audio_data = b"final_audio"
        encoded = base64.b64encode(audio_data).decode('utf-8')
        event = {
            "raw": {
                "output": [
                    {"type": "audio", "data": encoded}
                ]
            }
        }
        buffer = bytearray()
        result = qwen_model._qwen_handle_response_done(event, buffer, yield_chunks=True)
        assert buffer == bytearray(audio_data)

    def test_qwen_handle_response_done_no_audio(self, qwen_model):
        """Test _qwen_handle_response_done with no audio."""
        event = {"raw": {"output": []}}
        result = qwen_model._qwen_handle_response_done(event, None, yield_chunks=False)
        assert result is None

    def test_qwen_process_event_error(self, qwen_model):
        """Test _qwen_process_event with error."""
        event = {"type": "error", "error_message": "Service error"}
        with pytest.raises(AliTTSError, match="Service error"):
            qwen_model._qwen_process_event("error", event, None, False)

    def test_qwen_process_event_audio_delta(self, qwen_model):
        """Test _qwen_process_event with audio delta."""
        audio_data = b"chunk"
        encoded = base64.b64encode(audio_data).decode('utf-8')
        event = {"raw": {"delta": encoded}}
        done = qwen_model._qwen_process_event("response.audio.delta", event, None, False)
        assert done is False

    def test_qwen_process_event_terminal(self, qwen_model):
        """Test _qwen_process_event with session.finished (terminal event)."""
        done = qwen_model._qwen_process_event("session.finished", {}, None, False)
        assert done is True

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

    def test_extract_tts_error_message(self, cosy_model):
        """Test _extract_tts_error_message."""
        msg = cosy_model._extract_tts_error_message(b"error message")
        assert "error message" in msg


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
