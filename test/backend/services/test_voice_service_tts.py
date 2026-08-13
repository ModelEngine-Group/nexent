"""
Unit tests for VoiceService TTS methods.

These tests cover:
- _get_tts_model_from_config
- _get_tts_model_from_tenant_config
- generate_tts_speech
- stream_tts_to_websocket
- check_tts_connectivity
"""
import os
import sys
import pytest
from unittest.mock import Mock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from consts.exceptions import (
    VoiceServiceException,
    TTSConnectionException,
)


class MockSTTModel:
    """Mock STT model."""

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
        patch("services.voice_service.get_stt_adapter_from_params", return_value=_shared_stt),
        patch("services.voice_service.get_stt_adapter_from_tenant_config", return_value=_shared_stt),
        patch("services.voice_service.get_tts_adapter_from_params", return_value=_shared_tts),
        patch("services.voice_service.get_tts_adapter_from_tenant_config", return_value=_shared_tts),
    ]
    return patches, _shared_stt, _shared_tts


import services.voice_service
from services.voice_service import VoiceService


# ---------------------------------------------------------------------------
# Tests: _get_tts_model_from_config / _get_tts_model_from_tenant_config (deleted)
# These private methods were moved to model_gateway_service adapter factories.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests: generate_tts_speech
# ---------------------------------------------------------------------------

class TestGenerateTTSSpeech:
    """Tests for generate_tts_speech."""

    @pytest.mark.asyncio
    async def test_with_explicit_tts_config_volc(self):
        """Test generate_tts_speech with explicit Volcano TTS config."""
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            tts_config = {
                "model_factory": "volc",
                "model_appid": "test_appid",
                "access_token": "test_token",
                "speed_ratio": 1.0
            }
            result = await service.generate_tts_speech(
                "Hello world",
                stream=True,
                tts_config=tts_config
            )
            chunks = []
            async for chunk in result:
                chunks.append(chunk)
            assert chunks == [b"chunk_1", b"chunk_2", b"chunk_3"]
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_explicit_tts_config_ali_with_api_key(self):
        """Test generate_tts_speech with explicit Ali TTS config containing api_key."""
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            tts_config = {
                "api_key": "test_api_key",
                "model": "qwen3-tts-flash",
                "speed_ratio": 1.2
            }
            result = await service.generate_tts_speech(
                "Hello world",
                stream=True,
                tts_config=tts_config
            )
            chunks = []
            async for chunk in result:
                chunks.append(chunk)
            assert chunks == [b"chunk_1", b"chunk_2", b"chunk_3"]
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_tenant_id(self):
        """Test generate_tts_speech with tenant_id to pull model from tenant config."""
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.generate_tts_speech(
                "Hello world",
                stream=False,
                tenant_id="test_tenant_id"
            )
            assert result == b"complete_audio_data"
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_empty_text_raises_voice_service_exception(self):
        """Test generate_tts_speech raises VoiceServiceException for empty text."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(VoiceServiceException, match="No text provided for TTS generation"):
                await service.generate_tts_speech("")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_none_text_raises_voice_service_exception(self):
        """Test generate_tts_speech raises VoiceServiceException when text is None."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(VoiceServiceException, match="No text provided for TTS generation"):
                await service.generate_tts_speech(None)
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_tts_connection_error_raises_tts_connection_exception(self):
        """Test generate_tts_speech raises TTSConnectionException on connection failure."""
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
    async def test_general_error_raises_tts_connection_exception(self):
        """Test generate_tts_speech wraps general errors in TTSConnectionException."""
        _reset_singleton()
        exc = RuntimeError("unexpected error")
        patches, _, _ = _mock_all_models(tts_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException, match="unexpected error"):
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
    async def test_success_with_async_iterator(self):
        """Test stream_tts_to_websocket correctly handles async iterator from TTS model."""
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
    async def test_success_with_sync_iterator(self):
        """Test stream_tts_to_websocket handles synchronous iterator from TTS model."""

        def sync_gen():
            for chunk in [b"sync_1", b"sync_2"]:
                yield chunk

        _reset_singleton()
        global _shared_tts
        _shared_tts = MockTTSModel()

        class SyncIterTTSModel(MockTTSModel):
            async def generate_speech(self, text: str, stream: bool = False):
                if stream:
                    return sync_gen()
                return b"sync_complete"

        _shared_tts = SyncIterTTSModel()
        patches = [
            patch("services.voice_service.get_tts_adapter_from_params", return_value=_shared_tts),
            patch("services.voice_service.get_tts_adapter_from_tenant_config", return_value=_shared_tts),
        ]
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = self._connected_ws()
            await service.stream_tts_to_websocket(
                mock_ws, "Hello world", tts_config={"api_key": "test"}
            )
            assert mock_ws.send_bytes.call_count == 2
            mock_ws.send_json.assert_called_once_with({"status": "completed"})
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_success_with_single_chunk(self):
        """Test stream_tts_to_websocket handles single non-iterable chunk."""

        class SingleChunkTTSModel:
            """Minimal mock that returns bytes directly from generate_speech."""

            def __init__(self):
                self.check_connectivity = AsyncMock(return_value=True)

            async def generate_speech(self, text: str, stream: bool = False):
                return b"single_audio_chunk"

        _reset_singleton()
        _shared_tts = SingleChunkTTSModel()
        patches = [
            patch("services.voice_service.get_tts_adapter_from_params", return_value=_shared_tts),
            patch("services.voice_service.get_tts_adapter_from_tenant_config", return_value=_shared_tts),
        ]
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            mock_ws = self._connected_ws()
            await service.stream_tts_to_websocket(
                mock_ws, "Hello world", tts_config={"api_key": "test"}
            )
            mock_ws.send_json.assert_called_once_with({"status": "completed"})
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self):
        """Test stream_tts_to_websocket propagates TTSConnectionException."""
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


# ---------------------------------------------------------------------------
# Tests: check_tts_connectivity
# ---------------------------------------------------------------------------

class TestCheckTTSConnectivity:
    """Tests for check_tts_connectivity."""

    @pytest.mark.asyncio
    async def test_success_returns_true(self):
        """Test check_tts_connectivity returns True on successful connection."""
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_tts_connectivity(
                api_key="test_key",
                model="qwen3-tts-flash"
            )
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_failure_raises(self):
        """Test check_tts_connectivity raises TTSConnectionException when connectivity check fails."""
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=False)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException, match="TTS service connectivity check returned False"):
                await service.check_tts_connectivity(
                    api_key="test_key",
                    model="qwen3-tts-flash"
                )
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_exception_raises(self):
        """Test check_tts_connectivity raises TTSConnectionException when an exception occurs."""
        _reset_singleton()
        exc = RuntimeError("connection timeout")
        patches, _, _ = _mock_all_models(tts_exc=exc)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(TTSConnectionException, match="connection timeout"):
                await service.check_tts_connectivity(
                    api_key="test_key"
                )
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_volc_factory_success(self):
        """Test check_tts_connectivity with Volcano TTS factory."""
        _reset_singleton()
        patches, _, _ = _mock_all_models(tts_success=True)
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            result = await service.check_tts_connectivity(
                model_factory="volc",
                model_appid="test_appid",
                access_token="test_token"
            )
            assert result is True
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_with_speed_ratio(self):
        """Test check_tts_connectivity with custom speed_ratio."""
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
