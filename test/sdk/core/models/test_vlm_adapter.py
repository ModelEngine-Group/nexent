"""Tests for OpenAIVLMAdapter — VLM protocol (moved from the deleted
OpenAIVLModel class).

The protocol methods (encode_image / prepare_image_message / prepare_media_message
/ analyze_image / analyze_audio / analyze_video / check_connectivity) now live
directly on the adapter and delegate chat completions to ``_model`` (an
OpenAIModel). A mock ``_model`` is therefore sufficient — no smolagents / OpenAI
client is constructed.
"""

import asyncio
import base64

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from nexent.core.gateway.modality import OpenAIVLMAdapter


@pytest.fixture()
def vlm_adapter():
    """Return an OpenAIVLMAdapter with a mocked _model."""
    adapter = OpenAIVLMAdapter.__new__(OpenAIVLMAdapter)
    inner = MagicMock()
    inner.model_id = "dummy-model"
    inner.client.chat.completions.create = MagicMock()
    adapter._model = inner
    return adapter


# ---------------------------------------------------------------------------
# Tests for check_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_connectivity_success(vlm_adapter):
    """check_connectivity should return True when no exception is raised."""
    with patch.object(
        asyncio,
        "to_thread",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_to_thread:
        result = await vlm_adapter.check_connectivity()

    assert result is True
    mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_connectivity_failure(vlm_adapter):
    """check_connectivity should return False when to_thread raises."""
    with patch.object(
        asyncio,
        "to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ):
        result = await vlm_adapter.check_connectivity()
    assert result is False


@pytest.mark.asyncio
async def test_check_connectivity_uses_fallback_url(vlm_adapter):
    """check_connectivity should use fallback remote URL when local image missing."""

    async def mock_to_thread_func(*args, **kwargs):
        return None

    with patch.object(vlm_adapter, "encode_image", return_value=""), \
         patch.object(asyncio, "to_thread", new_callable=AsyncMock,
                           side_effect=mock_to_thread_func):
        import os.path

        with patch.object(os.path, "exists", return_value=False):
            result = await vlm_adapter.check_connectivity()

    assert result is True


@pytest.mark.asyncio
async def test_check_connectivity_jpg_to_jpeg_conversion(vlm_adapter):
    """check_connectivity should convert jpg to jpeg format for MIME type."""
    import os.path

    def mock_exists(path):
        if "git-flow" in str(path):
            return True
        return False

    def mock_splitext(path):
        if "git-flow" in str(path):
            return ("", ".jpg")
        return ("", "")

    async def mock_to_thread_func(*args, **kwargs):
        return None

    with patch.object(os.path, "exists", side_effect=mock_exists), \
         patch.object(os.path, "splitext", side_effect=mock_splitext), \
         patch.object(vlm_adapter, "encode_image", return_value="fakebase64"), \
         patch.object(asyncio, "to_thread", new_callable=AsyncMock,
                           side_effect=mock_to_thread_func):
        result = await vlm_adapter.check_connectivity()

    assert result is True


# ---------------------------------------------------------------------------
# Tests for encode_image
# ---------------------------------------------------------------------------


def test_encode_image_with_file_path(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake image data")

    result = vlm_adapter.encode_image(str(test_image))

    expected = base64.b64encode(b"fake image data").decode('utf-8')
    assert result == expected


def test_encode_image_with_binary_io(vlm_adapter):
    mock_file = MagicMock()
    mock_file.read.return_value = b"binary image data"

    result = vlm_adapter.encode_image(mock_file)

    expected = base64.b64encode(b"binary image data").decode('utf-8')
    assert result == expected


# ---------------------------------------------------------------------------
# Tests for prepare_image_message
# ---------------------------------------------------------------------------


def test_prepare_image_message_with_png_file(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake png data")

    messages = vlm_adapter.prepare_image_message(str(test_image))

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "data:image/png;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_jpg_file(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.jpg"
    test_image.write_bytes(b"fake jpg data")

    messages = vlm_adapter.prepare_image_message(str(test_image))

    assert "data:image/jpeg;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_jpeg_file(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.jpeg"
    test_image.write_bytes(b"fake jpeg data")

    messages = vlm_adapter.prepare_image_message(str(test_image))

    assert "data:image/jpeg;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_gif_file(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.gif"
    test_image.write_bytes(b"fake gif data")

    messages = vlm_adapter.prepare_image_message(str(test_image))

    assert "data:image/gif;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_webp_file(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.webp"
    test_image.write_bytes(b"fake webp data")

    messages = vlm_adapter.prepare_image_message(str(test_image))

    assert "data:image/webp;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_binary_io(vlm_adapter):
    mock_file = MagicMock()
    mock_file.read.return_value = b"binary data"

    messages = vlm_adapter.prepare_image_message(mock_file)

    assert "data:image/jpeg;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_custom_system_prompt(vlm_adapter, tmp_path):
    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake png data")

    custom_prompt = "What is in this image?"
    messages = vlm_adapter.prepare_image_message(str(test_image), system_prompt=custom_prompt)

    assert messages[0]["content"][0]["text"] == custom_prompt


# ---------------------------------------------------------------------------
# Tests for analyze_image / analyze_audio / analyze_video
# ---------------------------------------------------------------------------


def test_analyze_image_calls_prepare_image_message(vlm_adapter, tmp_path):
    """analyze_image should call prepare_image_message and delegate to _model."""
    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake png data")

    with patch.object(vlm_adapter, "prepare_image_message",
                           return_value=[{"role": "user", "content": "test"}]) as mock_prepare:
        custom_prompt = "Describe this image"
        vlm_adapter.analyze_image(str(test_image), system_prompt=custom_prompt, stream=False)

        mock_prepare.assert_called_once_with(str(test_image), custom_prompt)
        vlm_adapter._model.assert_called_once()
        # ensure the prepared messages were forwarded to _model
        _, kwargs = vlm_adapter._model.call_args
        assert kwargs["messages"] == [{"role": "user", "content": "test"}]


def test_prepare_media_message_audio(vlm_adapter):
    audio_stream = MagicMock()
    audio_stream.read.return_value = b"audio bytes"

    messages = vlm_adapter.prepare_media_message(
        audio_stream,
        media_type="audio",
        content_type="audio/mpeg",
        system_prompt="Listen carefully",
    )

    assert messages[0]["content"][0]["type"] == "audio_url"
    assert messages[0]["content"][0]["audio_url"]["url"].startswith("data:audio/mpeg;base64,")
    assert messages[0]["content"][1] == {"type": "text", "text": "Listen carefully"}


def test_prepare_media_message_video(vlm_adapter):
    video_stream = MagicMock()
    video_stream.read.return_value = b"video bytes"

    messages = vlm_adapter.prepare_media_message(
        video_stream,
        media_type="video",
        content_type="video/mp4",
        system_prompt="Watch carefully",
    )

    assert messages[0]["content"][0]["type"] == "video_url"
    assert messages[0]["content"][0]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert messages[0]["content"][0]["video_url"]["max_frames"] == 16
    assert messages[0]["content"][0]["video_url"]["fps"] == 1
    assert messages[0]["content"][1] == {"type": "text", "text": "Watch carefully"}


def test_analyze_audio_calls_prepare_media_message(vlm_adapter):
    with patch.object(vlm_adapter, "prepare_media_message",
                           return_value=[{"role": "user", "content": "test"}]) as mock_prepare:
        vlm_adapter.analyze_audio("audio.mp3", system_prompt="Analyze", content_type="audio/mpeg")

        mock_prepare.assert_called_once_with("audio.mp3", "audio", "audio/mpeg", "Analyze")
        vlm_adapter._model.assert_called_once()


def test_analyze_video_calls_prepare_media_message(vlm_adapter):
    with patch.object(vlm_adapter, "prepare_media_message",
                           return_value=[{"role": "user", "content": "test"}]) as mock_prepare:
        vlm_adapter.analyze_video("video.mp4", system_prompt="Analyze", content_type="video/mp4")

        mock_prepare.assert_called_once_with("video.mp4", "video", "video/mp4", "Analyze")
        vlm_adapter._model.assert_called_once()


def test_invoke_sync_dispatches_by_media_type(vlm_adapter):
    """invoke_sync routes to the adapter's own analyze_* via _METHOD_MAP."""
    with patch.object(vlm_adapter, "analyze_image", return_value="img-result") as mock_analyze:
        from nexent.core.gateway.modality import VLMRequest
        result = vlm_adapter.invoke_sync(
            VLMRequest(media_type="image", media_input=b"bytes", prompt="p", stream=False)
        )
    assert result == "img-result"
    mock_analyze.assert_called_once_with(b"bytes", system_prompt="p", stream=False)


# ---------------------------------------------------------------------------
# Regression: _build_model must not leak frequency_penalty onto the wire.
# ---------------------------------------------------------------------------


def test_build_model_does_not_send_frequency_penalty():
    """Real _build_model (offline OpenAIModel construction) must keep
    frequency_penalty out of self.kwargs — smolagents merges self.kwargs into
    every chat.completions.create, so leaking it would silently send
    frequency_penalty=0.5 to the VLM API. The original OpenAIVLModel set it
    only as a dead instance attribute (never forwarded, never read).
    """
    from nexent.core.gateway.model_context import VLMContext
    from nexent.core.utils.observer import MessageObserver

    adapter = OpenAIVLMAdapter(VLMContext(
        modality="vlm",
        factory="openai",
        model_name="qwen-vl-max",
        display_name="vlm-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-fake",
        ssl_verify=True,
        observer=MessageObserver(),
    ))
    adapter._build_model()  # offline — no network call

    inner = adapter._model
    # frequency_penalty must NOT ride along in the smolagents model-defaults
    # dict that _prepare_completion_kwargs merges into the wire request.
    assert "frequency_penalty" not in getattr(inner, "kwargs", {}), inner.kwargs
    # but the dead instance attribute is preserved for getattr parity.
    assert inner.frequency_penalty == 0.5
    # sampling defaults that OpenAIVLModel DID forward must still be set.
    assert inner.temperature == 0.7
    assert inner.top_p == 0.7
    assert inner.max_tokens == 512


# ---------------------------------------------------------------------------
# get_model_info: the adapter owns the (provider, model) → capability mapping,
# replacing analyze_audio_tool's getattr + URL sniffing on the wrapped model.
# ---------------------------------------------------------------------------


def _make_vlm(model_name, base_url, **ctx_overrides):
    from nexent.core.gateway.model_context import VLMContext

    return OpenAIVLMAdapter(VLMContext(
        modality="vlm",
        factory="openai",
        model_name=model_name,
        display_name="vlm-test",
        base_url=base_url,
        api_key="sk-fake",
        ssl_verify=True,
        **ctx_overrides,
    ))


def test_model_info_siliconflow_non_omni_disables_audio():
    """SiliconFlow non-omni VLMs report audio=False — callers read
    get_model_info() instead of sniffing client_kwargs / model_id."""
    adapter = _make_vlm(
        "Qwen/Qwen3-VL-32B-Instruct",
        "https://api.siliconflow.cn/v1",
    )
    info = adapter.get_model_info()
    assert info.capabilities["audio"] is False
    assert info.capabilities["image"] is True
    assert info.capabilities["video"] is True


def test_model_info_siliconflow_omni_keeps_audio():
    adapter = _make_vlm(
        "Qwen/Qwen3-Omni-7B",
        "https://api.siliconflow.cn/v1",
    )
    assert adapter.get_model_info().capabilities["audio"] is True


def test_model_info_non_siliconflow_keeps_audio():
    adapter = _make_vlm(
        "qwen-vl-max",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    assert adapter.get_model_info().capabilities["audio"] is True


def test_model_info_explicit_capability_overrides_heuristic():
    """An explicit audio=True in context.capabilities wins over the
    SiliconFlow heuristic — the config author declared the capability."""
    from nexent.core.gateway.model_context import VLMContext

    adapter = OpenAIVLMAdapter(VLMContext(
        modality="vlm",
        factory="openai",
        model_name="Qwen/Qwen3-VL-32B-Instruct",
        display_name="vlm-test",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-fake",
        ssl_verify=True,
        capabilities={"audio": True},
    ))
    assert adapter.get_model_info().capabilities["audio"] is True
