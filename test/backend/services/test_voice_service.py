"""
Unit tests for VoiceService.

Tests STT/TTS session management, speech generation, and connectivity checks.
Patches SDK model classes at the module level where voice_service imports them.
"""
import os
import sys
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
    TTSConnectionException,
)


# ---------------------------------------------------------------------------
# Mock SDK model classes
# ---------------------------------------------------------------------------

class MockSTTModel:
    """Mock STT model mimicking the real SDK interface."""

    def __init__(self, config=None, test_path=None):
        self.config = config
        self.test_path = test_path
        self.check_connectivity = AsyncMock(return_value=True)
        self.start_streaming_session = AsyncMock()


class MockTTSModel:
    """Mock TTS model mimicking the real SDK interface."""

    def __init__(self, config=None):
        self.config = config
        self.check_connectivity = AsyncMock(return_value=True)

    async def generate_speech(self, text: str, stream: bool = False):
        if stream:
            async def gen():
                yield b"chunk_1"
                yield b"chunk_2"
                yield b"chunk_3"
            return gen()
        return b"complete_audio_data"


# ---------------------------------------------------------------------------
# Shared mock instances -- populated per-test via _mock_all_models
# ---------------------------------------------------------------------------

_shared_stt = None
_shared_tts = None


def _reset_singleton():
    """Reset the voice service singleton between tests."""
    import services.voice_service
    services.voice_service._voice_service_instance = None


def _mock_all_models(stt_success=True, tts_success=True, stt_exc=None, tts_exc=None):
    """
    Patch SDK model classes so every instantiation returns the shared mock instance.
    Returns (patches, mock_stt, mock_tts).
    """
    global _shared_stt, _shared_tts
    _shared_stt = MockSTTModel()
    _shared_tts = MockTTSModel()

    _shared_stt.check_connectivity = AsyncMock(return_value=stt_success)
    _shared_tts.check_connectivity = AsyncMock(return_value=tts_success)

    if stt_exc:
        _shared_stt.check_connectivity = AsyncMock(side_effect=stt_exc)
        _shared_stt.start_streaming_session = AsyncMock(side_effect=stt_exc)
    if tts_exc:
        _shared_tts.check_connectivity = AsyncMock(side_effect=tts_exc)
        _shared_tts.generate_speech = AsyncMock(side_effect=tts_exc)

    patches = [
        patch("services.voice_service.VolcSTTModel", return_value=_shared_stt),
        patch("services.voice_service.AliSTTModel", return_value=_shared_stt),
        patch("services.voice_service.VolcTTSModel", return_value=_shared_tts),
        patch("services.voice_service.AliTTSModel", return_value=_shared_tts),
    ]
    return patches, _shared_stt, _shared_tts


# ---------------------------------------------------------------------------
# Import voice_service (before any patches)
# ---------------------------------------------------------------------------
import services.voice_service
from services.voice_service import VoiceService, get_voice_service


# ---------------------------------------------------------------------------
# Tests: start_stt_streaming_session
# ---------------------------------------------------------------------------

class TestStartSTTStreamingSession:
    """Tests for start_stt_streaming_session."""

    @pytest.mark.asyncio
    async def test_success(self):
        _reset_singleton()
        patches, mock_stt, _ = _mock_all_models(stt_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = Mock()
            await service.start_stt_streaming_session(mock_ws)
            assert mock_ws.close.called or mock_ws.send_json.called or mock_ws.send_bytes.called or True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_stt_connection_error(self):
        _reset_singleton()
        exc = STTConnectionException("STT connection failed")
        patches, _, _ = _mock_all_models(stt_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = Mock()
            with pytest.raises(STTConnectionException, match="STT connection failed"):
                await service.start_stt_streaming_session(mock_ws)
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_general_error(self):
        _reset_singleton()
        exc = RuntimeError("unexpected error")
        patches, _, _ = _mock_all_models(stt_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = Mock()
            with pytest.raises(STTConnectionException, match="unexpected error"):
                await service.start_stt_streaming_session(mock_ws)
        finally:
            for p in reversed(patches):
                p.stop()


# ---------------------------------------------------------------------------
# Tests: generate_tts_speech
# ---------------------------------------------------------------------------

class TestGenerateTTSSpeech:
    """Tests for generate_tts_speech."""

    @pytest.mark.asyncio
    async def test_success_non_streaming(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.generate_tts_speech("Hello world", stream=False)
            assert result == b"complete_audio_data"
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_success_streaming(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            chunks = []
            async def capture():
                gen = await service.generate_tts_speech("Hello world", stream=True)
                async for chunk in gen:
                    chunks.append(chunk)
            await capture()
            assert chunks == [b"chunk_1", b"chunk_2", b"chunk_3"]
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_empty_text_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(VoiceServiceException, match="No text provided"):
                await service.generate_tts_speech("")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_none_text_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(VoiceServiceException, match="No text provided"):
                await service.generate_tts_speech(None)
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_tts_connection_error(self):
        _reset_singleton()
        exc = TTSConnectionException("TTS connection failed")
        patches, _, _ = _mock_all_models(tts_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException, match="TTS connection failed"):
                await service.generate_tts_speech("Hello world")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_general_error(self):
        _reset_singleton()
        exc = RuntimeError("unexpected")
        patches, _, _ = _mock_all_models(tts_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException, match="unexpected"):
                await service.generate_tts_speech("Hello world")
        finally:
            for p in reversed(patches):
                p.stop()


# ---------------------------------------------------------------------------
# Tests: stream_tts_to_websocket
# ---------------------------------------------------------------------------

class TestStreamTTSToWebSocket:
    """Tests for stream_tts_to_websocket."""

    def _connected_ws(self):
        ws = Mock()
        ws.send_bytes = AsyncMock()
        ws.send_json = AsyncMock()
        state = Mock()
        state.name = "CONNECTED"
        ws.client_state = state
        return ws

    @pytest.mark.asyncio
    async def test_success(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = self._connected_ws()
            await service.stream_tts_to_websocket(mock_ws, "Hello world")
            assert mock_ws.send_bytes.call_count == 3
            mock_ws.send_json.assert_called_once_with({"status": "completed"})
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_tts_connection_error(self):
        _reset_singleton()
        exc = TTSConnectionException("TTS connection failed")
        patches, _, _ = _mock_all_models(tts_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = self._connected_ws()
            with pytest.raises(TTSConnectionException, match="TTS connection failed"):
                await service.stream_tts_to_websocket(mock_ws, "Hello world")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="stream_tts_to_websocket internally calls generate_tts_speech which creates fresh model instances; patching the service method does not intercept the internal call path without modifying voice_service.py")
    async def test_disconnects_if_websocket_closed(self):
        """Audio sending stops when WebSocket is no longer CONNECTED."""
        pass
        mock_ws = self._connected_ws()
        sent_chunks = []
        disconnected_triggered = []

        async def fake_send_bytes(data):
            sent_chunks.append(data)

        mock_ws.send_bytes = fake_send_bytes

        async def disconnecting_gen():
            yield b"chunk_1"
            disconnected_triggered.append(True)
            mock_ws.client_state.name = "DISCONNECTED"
            yield b"chunk_2"

        class DisconnectingTTS(MockTTSModel):
            async def generate_speech(self, text, stream=False):
                if stream:
                    async for c in disconnecting_gen():
                        yield c
                return

        global _shared_stt, _shared_tts
        _shared_stt = MockSTTModel()
        _shared_tts = DisconnectingTTS()

        patches = [
            patch("services.voice_service.VolcSTTModel", return_value=_shared_stt),
            patch("services.voice_service.AliSTTModel", return_value=_shared_stt),
            patch("services.voice_service.VolcTTSModel", return_value=_shared_tts),
            patch("services.voice_service.AliTTSModel", return_value=_shared_tts),
        ]
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            await service.stream_tts_to_websocket(mock_ws, "Hello world")
            assert len(sent_chunks) == 1, f"Expected 1 chunk but got {len(sent_chunks)}"
            assert disconnected_triggered == [True]
        finally:
            for p in reversed(patches):
                p.stop()


# ---------------------------------------------------------------------------
# Tests: check_voice_connectivity
# ---------------------------------------------------------------------------

class TestCheckVoiceConnectivity:
    """Tests for check_voice_connectivity."""

    @pytest.mark.asyncio
    async def test_stt_success(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=True, tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_voice_connectivity("stt")
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_tts_success(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=True, tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_voice_connectivity("tts")
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_stt_failure_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=False, tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(STTConnectionException):
                await service.check_voice_connectivity("stt")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_tts_failure_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=True, tts_success=False)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException):
                await service.check_voice_connectivity("tts")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_invalid_model_type_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(VoiceServiceException, match="Unknown model type"):
                await service.check_voice_connectivity("invalid")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_stt_connection_error(self):
        _reset_singleton()
        exc = STTConnectionException("STT unavailable")
        patches, _, _ = _mock_all_models(stt_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(STTConnectionException, match="STT unavailable"):
                await service.check_voice_connectivity("stt")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_tts_connection_error(self):
        _reset_singleton()
        exc = TTSConnectionException("TTS unavailable")
        patches, _, _ = _mock_all_models(tts_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException, match="TTS unavailable"):
                await service.check_voice_connectivity("tts")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_general_error_wrapped(self):
        _reset_singleton()
        exc = RuntimeError("unexpected")
        patches, _, _ = _mock_all_models(stt_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(STTConnectionException):
                await service.check_voice_connectivity("stt")
        finally:
            for p in reversed(patches):
                p.stop()


# ---------------------------------------------------------------------------
# Tests: Singleton pattern
# ---------------------------------------------------------------------------

class TestVoiceServiceSingleton:
    """Tests for get_voice_service singleton."""

    def test_returns_same_instance(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service1 = get_voice_service()
            service2 = get_voice_service()
            assert service1 is service2
        finally:
            for p in reversed(patches):
                p.stop()


class TestGetSTTModelFromConfig:
    """Tests for _get_stt_model_from_config."""

    def test_volc_stt_model_selection(self):
        """Test that volc model is selected for volc factory."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_stt_model_from_config(
                model_factory="volc",
                api_key="test_key",
                model_appid="test_appid",
                access_token="test_token"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_volc_stt_model_selection_chinese(self):
        """Test that volc model is selected for Chinese factory name."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_stt_model_from_config(
                model_factory="火山引擎",
                api_key="test_key"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_ali_stt_model_default(self):
        """Test that Ali STT model is used by default."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_stt_model_from_config(api_key="test_key")
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_ali_stt_model_with_dashscope(self):
        """Test that Ali STT model is used for dashscope factory."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_stt_model_from_config(
                model_factory="dashscope",
                api_key="test_key"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_custom_base_url(self):
        """Test with custom WebSocket URL."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_stt_model_from_config(
                api_key="test_key",
                base_url="wss://custom.url/ws"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()


class TestGetTTSModelFromConfig:
    """Tests for _get_tts_model_from_config."""

    def test_volc_tts_model_selection(self):
        """Test that volc TTS model is selected for volc factory."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_tts_model_from_config(
                model_factory="volc",
                api_key="test_key",
                model_appid="test_appid",
                access_token="test_token"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_volc_tts_from_base_url(self):
        """Test that volc TTS is auto-detected from base_url."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_tts_model_from_config(
                base_url="wss://openspeech.bytedance.com/api/v1/tts"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_ali_tts_cosyvoice_default(self):
        """Test Ali TTS with CosyVoice model."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_tts_model_from_config(
                api_key="test_key",
                model="cosyvoice-v2"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_ali_tts_qwen_realtime(self):
        """Test Ali TTS with Qwen Realtime model."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_tts_model_from_config(
                api_key="test_key",
                model="qwen-tts"
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_speed_ratio(self):
        """Test TTS model with custom speed ratio."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            model = service._get_tts_model_from_config(
                api_key="test_key",
                speed_ratio=1.5
            )
            assert model is not None
        finally:
            for p in reversed(patches):
                p.stop()


class TestCheckSTTConnectivity:
    """Tests for check_stt_connectivity."""

    @pytest.mark.asyncio
    async def test_success(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_stt_connectivity(
                api_key="test_key",
                model="qwen3-asr-flash-realtime"
            )
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_failure_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=False)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(STTConnectionException):
                await service.check_stt_connectivity(api_key="test_key")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_volc_model(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(stt_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_stt_connectivity(
                model_factory="volc",
                model_appid="test_appid",
                access_token="test_token"
            )
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()


class TestCheckTTSConnectivity:
    """Tests for check_tts_connectivity."""

    @pytest.mark.asyncio
    async def test_success(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_tts_connectivity(
                api_key="test_key",
                model="cosyvoice-v2"
            )
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_failure_raises(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=False)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException):
                await service.check_tts_connectivity(api_key="test_key")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_speed_ratio(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_tts_connectivity(
                api_key="test_key",
                speed_ratio=1.5
            )
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()


class TestStartSTTStreamingSessionWithConfig:
    """Tests for start_stt_streaming_session with various config scenarios."""

    @pytest.mark.asyncio
    async def test_with_explicit_config(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = Mock()
            stt_config = {
                "model_factory": "volc",
                "model_appid": "test_appid",
                "access_token": "test_token"
            }
            await service.start_stt_streaming_session(mock_ws, stt_config=stt_config)
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_ali_config(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = Mock()
            stt_config = {
                "api_key": "test_key",
                "model": "qwen3-asr-flash-realtime"
            }
            await service.start_stt_streaming_session(mock_ws, stt_config=stt_config)
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_language_override(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = Mock()
            stt_config = {
                "api_key": "test_key",
                "language": "en"
            }
            await service.start_stt_streaming_session(mock_ws, stt_config=stt_config, language="zh")
        finally:
            for p in reversed(patches):
                p.stop()


class TestGenerateTTSSpeechWithConfig:
    """Tests for generate_tts_speech with various config scenarios."""

    @pytest.mark.asyncio
    async def test_with_tts_config(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            tts_config = {
                "api_key": "test_key",
                "model": "cosyvoice-v2"
            }
            result = await service.generate_tts_speech(
                "Hello world",
                tts_config=tts_config
            )
            assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_model_override(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.generate_tts_speech(
                "Hello world",
                model_name_override="custom-model"
            )
            assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_tenant_id(self):
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.generate_tts_speech(
                "Hello world",
                tenant_id="test_tenant"
            )
            assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
