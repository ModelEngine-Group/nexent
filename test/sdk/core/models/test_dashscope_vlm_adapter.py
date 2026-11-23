"""Tests for DashScopeVLMAdapter - the DashScope audio dialect."""

from unittest.mock import patch

import pytest
from nexent.core.gateway.modality import DashScopeVLMAdapter
from nexent.core.gateway.registry import get_registry


@pytest.fixture()
def dashscope_adapter():
    """Return a DashScopeVLMAdapter with encode_image mocked."""
    adapter = DashScopeVLMAdapter.__new__(DashScopeVLMAdapter)
    with patch.object(adapter, "encode_image", return_value="ZmFrZS1hdWRpbw=="):
        yield adapter


def test_registered_under_dashscope_factory():
    """The adapter should be registered for the dashscope factory."""
    assert get_registry().resolve("dashscope", "vlm") is DashScopeVLMAdapter


def test_factory_attribute_is_dashscope():
    """The adapter should advertise the dashscope factory."""
    assert DashScopeVLMAdapter.factory == "dashscope"


def test_prepare_media_message_audio_uses_input_audio(dashscope_adapter):
    """Audio should be sent as input_audio with a full data-URL string."""
    messages = dashscope_adapter.prepare_media_message(
        "audio.mp3",
        media_type="audio",
        content_type="audio/mpeg",
        system_prompt="Transcribe this clip",
    )

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert content[0]["type"] == "input_audio"
    assert content[0]["input_audio"] == {
        "data": "data:audio/mpeg;base64,ZmFrZS1hdWRpbw==",
        "format": "mpeg",
    }
    assert content[1] == {"type": "text", "text": "Transcribe this clip"}


def test_prepare_media_message_video_delegates_to_openai_form(dashscope_adapter):
    """Video should keep the generic OpenAI video_url form."""
    messages = dashscope_adapter.prepare_media_message(
        "video.mp4",
        media_type="video",
        content_type="video/mp4",
        system_prompt="Summarize the scene",
    )

    assert len(messages) == 1
    content = messages[0]["content"]
    assert content[0]["type"] == "video_url"
    assert content[0]["video_url"]["url"] == "data:video/mp4;base64,ZmFrZS1hdWRpbw=="
    assert content[0]["video_url"]["detail"] == "high"
    assert content[0]["video_url"]["max_frames"] == 16
    assert content[0]["video_url"]["fps"] == 1
    assert content[1] == {"type": "text", "text": "Summarize the scene"}
