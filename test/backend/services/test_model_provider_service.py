from unittest import mock
import sys
import pytest

# Create a generic MockModule to stand-in for optional/imported-at-runtime modules
class MockModule(mock.MagicMock):
    @classmethod
    def __getattr__(cls, item):
        return mock.MagicMock()

# ---------------------------------------------------------------------------
# Insert minimal stub modules so that the service under test can be imported
# without its real heavy dependencies being present during unit-testing.
# ---------------------------------------------------------------------------
for module_path in [
    "consts", "consts.provider", "consts.model",
    "utils", "utils.model_name_utils",
    "services", "services.model_health_service",
]:
    sys.modules.setdefault(module_path, MockModule())

# Provide concrete attributes required by the module under test
sys.modules["consts.provider"].SILICON_GET_URL = "https://silicon.com"

# Minimal ModelConnectStatusEnum stub so that prepare_model_dict can access
# `ModelConnectStatusEnum.NOT_DETECTED.value` without importing the real enum.
class _EnumStub:
    NOT_DETECTED = mock.Mock(value="not_detected")
    DETECTING = mock.Mock(value="detecting")

sys.modules["consts.model"].ModelConnectStatusEnum = _EnumStub

# ---------------------------------------------------------------------------
# Now that the import prerequisites are satisfied we can safely import the
# module under test.
# ---------------------------------------------------------------------------
from backend.services.model_provider_service import (
    SiliconModelProvider,
    prepare_model_dict,
)

# ---------------------------------------------------------------------------
# Test-cases for SiliconModelProvider.get_models
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_models_llm_success():
    """Silicon provider should append chat tag/type for LLM models."""
    provider_config = {"model_type": "llm", "api_key": "test-key"}

    # Patch HTTP client & constant inside the provider module
    with mock.patch("backend.services.model_provider_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_provider_service.SILICON_GET_URL", "https://silicon.com"):

        # Prepare mocked http client / response behaviour
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "gpt-4"}]}
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        # Execute
        result = await SiliconModelProvider().get_models(provider_config)

        # Assert returned value & correct HTTP call
        assert result == [{"id": "gpt-4", "model_tag": "chat", "model_type": "llm", "max_tokens": 4096}]
        mock_client_instance.get.assert_called_once_with(
            "https://silicon.com?sub_type=chat",
            headers={"Authorization": "Bearer test-key"},
        )


@pytest.mark.asyncio
async def test_get_models_embedding_success():
    """Silicon provider should append embedding tag/type for embedding models."""
    provider_config = {"model_type": "embedding", "api_key": "test-key"}

    with mock.patch("backend.services.model_provider_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_provider_service.SILICON_GET_URL", "https://silicon.com"):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "text-embedding-ada-002"}]}
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        result = await SiliconModelProvider().get_models(provider_config)

        assert result == [{
            "id": "text-embedding-ada-002",
            "model_tag": "embedding",
            "model_type": "embedding",
        }]
        mock_client_instance.get.assert_called_once_with(
            "https://silicon.com?sub_type=embedding",
            headers={"Authorization": "Bearer test-key"},
        )


@pytest.mark.asyncio
async def test_get_models_unknown_type():
    """Unknown model types should not have extra annotations and should hit the base URL."""
    provider_config = {"model_type": "other", "api_key": "test-key"}

    with mock.patch("backend.services.model_provider_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_provider_service.SILICON_GET_URL", "https://silicon.com"):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "model-x"}]}
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        result = await SiliconModelProvider().get_models(provider_config)

        # No additional keys should be injected for unknown type
        assert result == [{"id": "model-x"}]
        mock_client_instance.get.assert_called_once_with(
            "https://silicon.com",
            headers={"Authorization": "Bearer test-key"},
        )


@pytest.mark.asyncio
async def test_get_models_exception():
    """HTTP errors should be caught and an empty list returned."""
    provider_config = {"model_type": "llm", "api_key": "test-key"}

    with mock.patch("backend.services.model_provider_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_provider_service.SILICON_GET_URL", "https://silicon.com"):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        # Simulate request failure
        mock_client_instance.get.side_effect = Exception("Request failed")

        result = await SiliconModelProvider().get_models(provider_config)

        assert result == []

# ---------------------------------------------------------------------------
# Test-cases for prepare_model_dict (already indirectly covered elsewhere but
# re-asserted here directly against the provider service implementation).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prepare_model_dict_llm():
    """LLM models should not trigger embedding_dimension_check and keep base_url untouched."""
    with mock.patch("backend.services.model_provider_service.split_repo_name", return_value=("openai", "gpt-4")) as mock_split_repo, \
         mock.patch("backend.services.model_provider_service.split_display_name", return_value="gpt-4") as mock_split_display, \
         mock.patch("backend.services.model_provider_service.ModelRequest") as mock_model_request, \
         mock.patch("backend.services.model_provider_service.embedding_dimension_check", new_callable=mock.AsyncMock) as mock_emb_dim_check, \
         mock.patch("backend.services.model_provider_service.ModelConnectStatusEnum") as mock_enum:

        # Prepare baseline model_dump
        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "gpt-4",
            "model_type": "llm",
            "api_key": "test-key",
            "max_tokens": 4096,
            "display_name": "openai/gpt-4",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.NOT_DETECTED.value = "not_detected"

        provider = "openai"
        model = {"id": "openai/gpt-4", "model_type": "llm", "max_tokens": 4096}
        base_url = "https://api.openai.com/v1"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        mock_split_repo.assert_called_once_with("openai/gpt-4")
        mock_split_display.assert_called_once_with("openai/gpt-4")
        mock_model_request.assert_called_once_with(
            model_factory="openai",
            model_name="gpt-4",
            model_type="llm",
            api_key="test-key",
            max_tokens=4096,
            display_name="openai/gpt-4",
        )
        mock_emb_dim_check.assert_not_called()

        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": base_url,
            "connect_status": "not_detected",
        }
        assert result == expected


@pytest.mark.asyncio
async def test_prepare_model_dict_embedding():
    """Embedding models should call embedding_dimension_check and adjust base_url & max_tokens."""
    with mock.patch("backend.services.model_provider_service.split_repo_name", return_value=("openai", "text-embedding-ada-002")) as mock_split_repo, \
         mock.patch("backend.services.model_provider_service.split_display_name", return_value="text-embedding-ada-002") as mock_split_display, \
         mock.patch("backend.services.model_provider_service.ModelRequest") as mock_model_request, \
         mock.patch("backend.services.model_provider_service.embedding_dimension_check", new_callable=mock.AsyncMock, return_value=1536) as mock_emb_dim_check, \
         mock.patch("backend.services.model_provider_service.ModelConnectStatusEnum") as mock_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "text-embedding-ada-002",
            "model_type": "embedding",
            "api_key": "test-key",
            "max_tokens": 1024,
            "display_name": "openai/text-embedding-ada-002",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.NOT_DETECTED.value = "not_detected"

        provider = "openai"
        model = {"id": "openai/text-embedding-ada-002", "model_type": "embedding", "max_tokens": 1024}
        base_url = "https://api.openai.com/v1/"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        mock_split_repo.assert_called_once_with("openai/text-embedding-ada-002")
        mock_split_display.assert_called_once_with("openai/text-embedding-ada-002")
        mock_model_request.assert_called_once_with(
            model_factory="openai",
            model_name="text-embedding-ada-002",
            model_type="embedding",
            api_key="test-key",
            max_tokens=1024,
            display_name="openai/text-embedding-ada-002",
        )
        mock_emb_dim_check.assert_called_once_with(dump_dict)

        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1/embeddings",
            "connect_status": "not_detected",
            "max_tokens": 1536,
        }
        assert result == expected
