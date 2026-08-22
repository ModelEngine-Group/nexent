"""
Tests for BaseTTSModel abstract class.
"""
import pytest
from typing import Dict

from sdk.nexent.core.models.tts_model import BaseTTSModel


class ConcreteTTSModel(BaseTTSModel):
    """Concrete implementation of BaseTTSModel for testing."""

    def get_websocket_url(self) -> str:
        return "wss://test.com"

    def get_auth_headers(self) -> Dict[str, str]:
        return {}

    async def generate_speech(self, text: str, stream: bool = False):
        return b"test"

    async def check_connectivity(self) -> bool:
        return True


class TestTTSModelConstructor:
    """Test TTSModel constructor."""

    def test_init_with_audio_file_path(self):
        """Test initialization with audio_file_path set."""
        model = ConcreteTTSModel(audio_file_path="/path/to/audio.wav")

        assert model.audio_file_path == "/path/to/audio.wav"

    def test_init_without_audio_file_path(self):
        """Test initialization with audio_file_path as None."""
        model = ConcreteTTSModel()

        assert model.audio_file_path is None

    def test_init_with_none_explicit(self):
        """Test initialization with explicit None value."""
        model = ConcreteTTSModel(audio_file_path=None)

        assert model.audio_file_path is None


class TestIsTTSResultSuccessful:
    """Test _is_tts_result_successful method."""

    @pytest.fixture
    def model(self):
        return ConcreteTTSModel()

    @pytest.mark.parametrize("data", [b"audio data", b"\x00\x01\x02", b"hello world"])
    def test_bytes_with_data_returns_true(self, model, data):
        """Test that non-empty bytes return True."""
        assert model._is_tts_result_successful(data) is True

    def test_bytes_empty_returns_false(self, model):
        """Test that empty bytes return False."""
        assert model._is_tts_result_successful(b"") is False

    def test_dict_with_audio_key_returns_true(self, model):
        """Test that dict with 'audio' key returns True."""
        result = {"audio": b"audio_data", "format": "pcm"}
        assert model._is_tts_result_successful(result) is True

    def test_dict_with_text_key_returns_true(self, model):
        """Test that dict with 'text' key returns True."""
        result = {"text": "transcribed text"}
        assert model._is_tts_result_successful(result) is True

    def test_dict_with_both_audio_and_text_returns_true(self, model):
        """Test that dict with both 'audio' and 'text' keys returns True."""
        result = {"audio": b"data", "text": "some text"}
        assert model._is_tts_result_successful(result) is True

    def test_dict_with_error_key_returns_false(self, model):
        """Test that dict with 'error' key returns False regardless of other keys."""
        result = {"error": "something went wrong"}
        assert model._is_tts_result_successful(result) is False

    def test_dict_with_error_and_audio_returns_false(self, model):
        """Test that dict with both 'error' and 'audio' keys returns False."""
        result = {"error": "error message", "audio": b"data"}
        assert model._is_tts_result_successful(result) is False

    def test_dict_with_message_key_returns_true(self, model):
        """Test that dict with 'message' key (without 'error') returns True."""
        result = {"message": "some message"}
        assert model._is_tts_result_successful(result) is True

    def test_dict_with_only_other_keys_returns_false(self, model):
        """Test that dict with only other keys returns False."""
        result = {"status": "ok", "code": 200}
        assert model._is_tts_result_successful(result) is False

    def test_dict_empty_returns_false(self, model):
        """Test that empty dict returns False."""
        assert model._is_tts_result_successful({}) is False

    def test_none_returns_false(self, model):
        """Test that None returns False."""
        assert model._is_tts_result_successful(None) is False

    def test_string_returns_false(self, model):
        """Test that string returns False."""
        assert model._is_tts_result_successful("audio data") is False

    def test_empty_string_returns_false(self, model):
        """Test that empty string returns False."""
        assert model._is_tts_result_successful("") is False

    def test_list_returns_false(self, model):
        """Test that list returns False."""
        assert model._is_tts_result_successful([b"data"]) is False

    def test_int_returns_false(self, model):
        """Test that integer returns False."""
        assert model._is_tts_result_successful(42) is False

    def test_bool_true_returns_false(self, model):
        """Test that True returns False."""
        assert model._is_tts_result_successful(True) is False

    def test_bool_false_returns_false(self, model):
        """Test that False returns False."""
        assert model._is_tts_result_successful(False) is False


class TestExtractTTSErrorMessage:
    """Test _extract_tts_error_message method."""

    @pytest.fixture
    def model(self):
        return ConcreteTTSModel()

    def test_dict_with_error_key(self, model):
        """Test extraction from dict with 'error' key."""
        result = {"error": "Something went wrong"}
        assert model._extract_tts_error_message(result) == "Something went wrong"

    def test_dict_with_error_key_non_string(self, model):
        """Test extraction from dict with 'error' key containing non-string value."""
        result = {"error": 12345}
        assert model._extract_tts_error_message(result) == "12345"

    def test_dict_with_error_key_none(self, model):
        """Test extraction from dict with 'error' key set to None."""
        result = {"error": None}
        assert model._extract_tts_error_message(result) == "None"

    def test_dict_with_message_key(self, model):
        """Test extraction from dict with 'message' key (when no 'error' key)."""
        result = {"message": "User requested cancellation"}
        assert model._extract_tts_error_message(result) == "User requested cancellation"

    def test_dict_with_message_key_non_string(self, model):
        """Test extraction from dict with 'message' key containing non-string value."""
        result = {"message": 500}
        assert model._extract_tts_error_message(result) == "500"

    def test_dict_with_error_and_message_keys(self, model):
        """Test that 'error' key takes precedence over 'message' key."""
        result = {"error": "Error message", "message": "Message text"}
        assert model._extract_tts_error_message(result) == "Error message"

    def test_dict_with_only_other_keys(self, model):
        """Test extraction from dict with only other keys."""
        result = {"status": "failed", "code": 404}
        assert "Unknown error in result" in model._extract_tts_error_message(result)
        assert "404" in model._extract_tts_error_message(result)

    def test_dict_empty(self, model):
        """Test extraction from empty dict."""
        message = model._extract_tts_error_message({})
        assert "Unknown error in result" in message

    def test_none(self, model):
        """Test extraction from None."""
        message = model._extract_tts_error_message(None)
        assert "Unknown error in result" in message
        assert "None" in message

    def test_string(self, model):
        """Test extraction from string."""
        message = model._extract_tts_error_message("just a string")
        assert "Unknown error in result" in message
        assert "just a string" in message

    def test_bytes(self, model):
        """Test extraction from bytes."""
        message = model._extract_tts_error_message(b"audio data")
        assert "Unknown error in result" in message

    def test_int(self, model):
        """Test extraction from integer."""
        message = model._extract_tts_error_message(42)
        assert "Unknown error in result" in message
        assert "42" in message
