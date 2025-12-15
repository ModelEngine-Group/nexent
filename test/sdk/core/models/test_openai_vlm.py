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
mock_models_module.ChatMessage = MagicMock()
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
        model = ImportedOpenAIVLModel(observer=observer)

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

        return model


# ---------------------------------------------------------------------------
# Tests for check_connectivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_connectivity_success(vl_model_instance):
    """check_connectivity should return True when no exception is raised."""

    with patch.object(
        vl_model_instance,
        "_prepare_completion_kwargs",
        return_value={},
    ) as mock_prepare_kwargs, patch.object(
        asyncio,
        "to_thread",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_to_thread:
        result = await vl_model_instance.check_connectivity()

        assert result is True
        mock_prepare_kwargs.assert_called_once()
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_connectivity_failure(vl_model_instance):
    """check_connectivity should return False when an exception is raised inside to_thread."""

    with patch.object(
        vl_model_instance,
        "_prepare_completion_kwargs",
        return_value={},
    ), patch.object(
        asyncio,
        "to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ):
        result = await vl_model_instance.check_connectivity()
        assert result is False
