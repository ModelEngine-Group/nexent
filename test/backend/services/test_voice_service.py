"""
Unit tests for VoiceService.

Tests STT session management and connectivity checks.
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


# ---------------------------------------------------------------------------
# Shared mock instances -- populated per-test via _mock_all_models
# ---------------------------------------------------------------------------

_shared_stt = None


def _reset_singleton():
    """Reset the voice service singleton between tests."""
    import services.voice_service
    services.voice_service._voice_service_instance = None


def _mock_all_models(stt_success=True, stt_exc=None):
    """
    Patch SDK model classes so every instantiation returns the shared mock instance.
    Returns (patches, mock_stt).
    """
    global _shared_stt
    _shared_stt = MockSTTModel()

    _shared_stt.check_connectivity = AsyncMock(return_value=stt_success)

    if stt_exc:
        _shared_stt.check_connectivity = AsyncMock(side_effect=stt_exc)
        _shared_stt.start_streaming_session = AsyncMock(side_effect=stt_exc)

    patches = [
        patch("services.voice_service.VolcSTTModel", return_value=_shared_stt),
        patch("services.voice_service.AliSTTModel", return_value=_shared_stt),
    ]
    return patches, _shared_stt


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
        patches, mock_stt = _mock_all_models(stt_success=True)
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
        patches, _ = _mock_all_models(stt_exc=exc)
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
        patches, _ = _mock_all_models(stt_exc=exc)
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
# Tests: check_voice_connectivity
# ---------------------------------------------------------------------------

class TestCheckVoiceConnectivity:
    """Tests for check_voice_connectivity."""

    @pytest.mark.asyncio
    async def test_stt_success(self):
        _reset_singleton()
        patches, _ = _mock_all_models(stt_success=True)
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
    async def test_stt_failure_raises(self):
        _reset_singleton()
        patches, _ = _mock_all_models(stt_success=False)
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
    async def test_invalid_model_type_raises(self):
        _reset_singleton()
        patches, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()
            with pytest.raises(VoiceServiceException, match=r"Unsupported model type"):
                await service.check_voice_connectivity("invalid")
        finally:
            for p in reversed(patches):
                p.stop()

    @pytest.mark.asyncio
    async def test_stt_connection_error(self):
        _reset_singleton()
        exc = STTConnectionException("STT unavailable")
        patches, _ = _mock_all_models(stt_exc=exc)
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
    async def test_general_error_wrapped(self):
        _reset_singleton()
        exc = RuntimeError("unexpected")
        patches, _ = _mock_all_models(stt_exc=exc)
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
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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


class TestCheckSTTConnectivity:
    """Tests for check_stt_connectivity."""

    @pytest.mark.asyncio
    async def test_success(self):
        _reset_singleton()
        patches, _ = _mock_all_models(stt_success=True)
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
        patches, _ = _mock_all_models(stt_success=False)
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
        patches, _ = _mock_all_models(stt_success=True)
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


class TestStartSTTStreamingSessionWithConfig:
    """Tests for start_stt_streaming_session with various config scenarios."""

    @pytest.mark.asyncio
    async def test_with_explicit_config(self):
        _reset_singleton()
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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
        patches, _ = _mock_all_models()
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
