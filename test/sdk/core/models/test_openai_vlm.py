import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies similar to test_openai_llm.py
# ---------------------------------------------------------------------------

# Mock smolagents and submodules
mock_smolagents = MagicMock()
mock_smolagents.Tool = MagicMock()

# Create dummy sub-modules and attributes
mock_models_module = MagicMock()

# Provide a minimal OpenAIServerModel base with the method needed by OpenAIModel
class DummyOpenAIServerModel:
    def __init__(self, *args, **kwargs):
        pass

    def _prepare_completion_kwargs(self, *args, **kwargs):
        # In tests we will patch this method on the instance directly, so default impl is fine
        return {}

mock_models_module.OpenAIServerModel = DummyOpenAIServerModel
# Must be a type for isinstance() checks inside the SDK
# Also add from_dict to support __call__ method in the real code
mock_chat_message_cls = type("ChatMessage", (), {})
mock_chat_message_cls.from_dict = classmethod(lambda cls, d: MagicMock())
mock_models_module.ChatMessage = mock_chat_message_cls
mock_smolagents.models = mock_models_module

# Assemble smolagents.* paths and openai.* placeholders
module_mocks = {
    "smolagents": mock_smolagents,
    "smolagents.models": mock_models_module,
    "openai.types": MagicMock(),
    "openai.types.chat": MagicMock(),
    "openai.types.chat.chat_completion_message": MagicMock(),
}


with patch.dict("sys.modules", module_mocks):

    # Import after patching so dependencies are satisfied
    from sdk.nexent.core.models.openai_vlm import OpenAIVLModel as ImportedOpenAIVLModel


    # -----------------------------------------------------------------------
    # Fixtures
    # -----------------------------------------------------------------------

    @pytest.fixture()
    def vl_model_instance():
        """Return an OpenAIVLModel instance with minimal viable attributes for tests."""

        observer = MagicMock()
        model = ImportedOpenAIVLModel(observer=observer, ssl_verify=True)

        # Inject dummy attributes required by the method under test
        model.model_id = "dummy-model"

        # Client hierarchy: client.chat.completions.create
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_completions.create = MagicMock()
        mock_chat.completions = mock_completions
        mock_client.chat = mock_chat
        model.client = mock_client

        # Additional attributes required by __call__ -> _prepare_completion_kwargs
        model.custom_role_conversions = {}
        model.model_factory = MagicMock()

        return model


# ---------------------------------------------------------------------------
# Tests for check_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_connectivity_success(vl_model_instance):
    """check_connectivity should return True when no exception is raised."""

    with patch.object(
        asyncio,
        "to_thread",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_to_thread:
        result = await vl_model_instance.check_connectivity()

        assert result is True
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_connectivity_failure(vl_model_instance):
    """check_connectivity should return False when an exception is raised inside to_thread."""

    with patch.object(
        asyncio,
        "to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ):
        result = await vl_model_instance.check_connectivity()
        assert result is False


# ---------------------------------------------------------------------------
# Tests for encode_image
# ---------------------------------------------------------------------------


def test_encode_image_with_file_path(vl_model_instance, tmp_path):
    """encode_image should correctly encode an image file to base64."""

    # Create a simple test image file
    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake image data")

    result = vl_model_instance.encode_image(str(test_image))

    import base64
    expected = base64.b64encode(b"fake image data").decode('utf-8')
    assert result == expected


def test_encode_image_with_binary_io(vl_model_instance):
    """encode_image should correctly encode a BinaryIO object to base64."""

    # Create a mock BinaryIO object
    mock_file = MagicMock()
    mock_file.read.return_value = b"binary image data"

    result = vl_model_instance.encode_image(mock_file)

    import base64
    expected = base64.b64encode(b"binary image data").decode('utf-8')
    assert result == expected


# ---------------------------------------------------------------------------
# Tests for prepare_image_message
# ---------------------------------------------------------------------------


def test_prepare_image_message_with_png_file(vl_model_instance, tmp_path):
    """prepare_image_message should correctly handle PNG files."""

    # Create a PNG test file
    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake png data")

    messages = vl_model_instance.prepare_image_message(str(test_image))

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "data:image/png;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_jpg_file(vl_model_instance, tmp_path):
    """prepare_image_message should correctly handle JPG files and convert to jpeg format."""

    # Create a JPG test file
    test_image = tmp_path / "test.jpg"
    test_image.write_bytes(b"fake jpg data")

    messages = vl_model_instance.prepare_image_message(str(test_image))

    assert "data:image/jpeg;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_jpeg_file(vl_model_instance, tmp_path):
    """prepare_image_message should correctly handle jpeg files."""

    test_image = tmp_path / "test.jpeg"
    test_image.write_bytes(b"fake jpeg data")

    messages = vl_model_instance.prepare_image_message(str(test_image))

    assert "data:image/jpeg;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_gif_file(vl_model_instance, tmp_path):
    """prepare_image_message should correctly handle GIF files."""

    test_image = tmp_path / "test.gif"
    test_image.write_bytes(b"fake gif data")

    messages = vl_model_instance.prepare_image_message(str(test_image))

    assert "data:image/gif;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_webp_file(vl_model_instance, tmp_path):
    """prepare_image_message should correctly handle WebP files."""

    test_image = tmp_path / "test.webp"
    test_image.write_bytes(b"fake webp data")

    messages = vl_model_instance.prepare_image_message(str(test_image))

    assert "data:image/webp;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_with_binary_io(vl_model_instance):
    """prepare_image_message should correctly handle BinaryIO input and default to jpeg."""

    mock_file = MagicMock()
    mock_file.read.return_value = b"binary data"

    messages = vl_model_instance.prepare_image_message(mock_file)

    assert "data:image/jpeg;base64," in messages[1]["content"][0]["image_url"]["url"]


def test_prepare_image_message_custom_system_prompt(vl_model_instance, tmp_path):
    """prepare_image_message should use custom system prompt when provided."""

    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake png data")

    custom_prompt = "What is in this image?"
    messages = vl_model_instance.prepare_image_message(str(test_image), system_prompt=custom_prompt)

    assert messages[0]["content"][0]["text"] == custom_prompt


# ---------------------------------------------------------------------------
# Tests for analyze_image
# ---------------------------------------------------------------------------


def test_analyze_image_returns_call_result(vl_model_instance, tmp_path):
    """analyze_image should return the result from __call__."""

    test_image = tmp_path / "test.png"
    test_image.write_bytes(b"fake png data")

    expected_result = MagicMock()
    vl_model_instance.prepare_image_message = MagicMock(return_value=[{"role": "user", "content": "test"}])
    vl_model_instance.__call__ = MagicMock(return_value=expected_result)

    result = vl_model_instance.analyze_image(str(test_image), system_prompt="Test prompt", stream=False)

    vl_model_instance.prepare_image_message.assert_called_once_with(str(test_image), "Test prompt")
    vl_model_instance.__call__.assert_called_once()
    assert result is expected_result
