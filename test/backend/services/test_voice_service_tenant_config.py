"""
Unit tests for VoiceService tenant config methods.
These tests cover _get_stt_model_from_tenant_config and _get_tts_model_from_tenant_config.
"""
import os
import sys
import pytest
from unittest.mock import Mock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from consts.exceptions import (
    VoiceServiceException,
    STTConnectionException,
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
    """Mock TTS model."""

    def __init__(self, config=None):
        self.config = config
        self.check_connectivity = AsyncMock(return_value=True)

    async def generate_speech(self, text: str, stream: bool = False):
        if stream:
            async def gen():
                yield b"chunk_1"
            return gen()
        return b"complete_audio_data"


_shared_stt = None
_shared_tts = None


def _reset_singleton():
    """Reset the voice service singleton between tests."""
    import services.voice_service
    services.voice_service._voice_service_instance = None


def _mock_all_models(stt_success=True, tts_success=True):
    global _shared_stt, _shared_tts
    _shared_stt = MockSTTModel()
    _shared_tts = MockTTSModel()
    _shared_stt.check_connectivity = AsyncMock(return_value=stt_success)
    _shared_tts.check_connectivity = AsyncMock(return_value=tts_success)

    patches = [
        patch("services.voice_service.VolcSTTModel", return_value=_shared_stt),
        patch("services.voice_service.AliSTTModel", return_value=_shared_stt),
        patch("services.voice_service.VolcTTSModel", return_value=_shared_tts),
        patch("services.voice_service.AliTTSModel", return_value=_shared_tts),
    ]
    return patches, _shared_stt, _shared_tts


import services.voice_service
from services.voice_service import VoiceService


class TestGetSTTModelFromTenantConfig:
    """Tests for _get_stt_model_from_tenant_config."""

    def test_with_tenant_config_stt(self):
        """Test _get_stt_model_from_tenant_config with tenant config."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            mock_stt_config = {
                "model_factory": "volc",
                "model_name": "bigmodel",
                "api_key": "test_api_key",
                "model_appid": "test_appid",
                "access_token": "test_token",
                "base_url": "wss://custom.url"
            }

            with patch.object(service, '_get_stt_model_from_config') as mock_get_model:
                mock_get_model.return_value = MockSTTModel()
                result = service._get_stt_model_from_tenant_config(
                    "test_tenant_id",
                    language="en"
                )
                assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_database_model_records(self):
        """Test _get_stt_model_from_tenant_config with database records."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            mock_record = {
                "model_factory": "dashscope",
                "model_name": "qwen3-asr-flash-realtime",
                "api_key": "test_api_key",
            }

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr, \
                 patch('services.voice_service.get_model_records') as mock_get_records:
                mock_config_mgr.get_model_config.return_value = None
                mock_get_records.return_value = [mock_record]

                with patch.object(service, '_get_stt_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockSTTModel()
                    result = service._get_stt_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_default_config(self):
        """Test _get_stt_model_from_tenant_config with default config when no config exists."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr, \
                 patch('services.voice_service.get_model_records') as mock_get_records:
                mock_config_mgr.get_model_config.return_value = None
                mock_get_records.return_value = []

                with patch.object(service, '_get_stt_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockSTTModel()
                    result = service._get_stt_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_exception(self):
        """Test _get_stt_model_from_tenant_config when exception occurs."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr:
                mock_config_mgr.get_model_config.side_effect = Exception("Database error")

                with patch.object(service, '_get_stt_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockSTTModel()
                    result = service._get_stt_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()


class TestGetTTSModelFromTenantConfig:
    """Tests for _get_tts_model_from_tenant_config."""

    def test_with_tenant_config_tts(self):
        """Test _get_tts_model_from_tenant_config with tenant config."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            mock_tts_config = {
                "model_factory": "volc",
                "api_key": "test_api_key",
                "model_appid": "test_appid",
                "access_token": "test_token",
                "speed_ratio": 1.5,
                "base_url": "wss://custom.url",
                "model": "cosyvoice-v2"
            }

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr:
                mock_config_mgr.get_model_config.return_value = mock_tts_config

                with patch.object(service, '_get_tts_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockTTSModel()
                    result = service._get_tts_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_database_model_records(self):
        """Test _get_tts_model_from_tenant_config with database records."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            mock_record = {
                "model_factory": "dashscope",
                "api_key": "test_api_key",
                "model_name": "cosyvoice-v2",
            }

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr, \
                 patch('services.voice_service.get_model_records') as mock_get_records:
                mock_config_mgr.get_model_config.return_value = None
                mock_get_records.return_value = [mock_record]

                with patch.object(service, '_get_tts_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockTTSModel()
                    result = service._get_tts_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_default_config(self):
        """Test _get_tts_model_from_tenant_config with default config when no config exists."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr, \
                 patch('services.voice_service.get_model_records') as mock_get_records:
                mock_config_mgr.get_model_config.return_value = None
                mock_get_records.return_value = []

                with patch.object(service, '_get_tts_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockTTSModel()
                    result = service._get_tts_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()

    def test_with_exception(self):
        """Test _get_tts_model_from_tenant_config when exception occurs."""
        _reset_singleton()
        patches, _, _ = _mock_all_models()
        for p in patches:
            p.start()
        try:
            service = VoiceService()

            with patch('services.voice_service.tenant_config_manager') as mock_config_mgr:
                mock_config_mgr.get_model_config.side_effect = Exception("Database error")

                with patch.object(service, '_get_tts_model_from_config') as mock_get_model:
                    mock_get_model.return_value = MockTTSModel()
                    result = service._get_tts_model_from_tenant_config("test_tenant_id")
                    assert result is not None
        finally:
            for p in reversed(patches):
                p.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
