import logging
from abc import ABC, abstractmethod
from typing import Dict, List

import httpx
import aiohttp

from consts.const import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
)
from consts.model import ModelConnectStatusEnum, ModelRequest
from consts.provider import SILICON_GET_URL, ProviderEnum
from database.model_management_db import get_models_by_tenant_factory_type
from services.model_health_service import embedding_dimension_check
from utils.model_name_utils import split_repo_name, add_repo_to_name

logger = logging.getLogger("model_provider_service")

MODEL_ENGINE_NORTH_PREFIX = "open/router/v1"

# =============================================================================
# Provider Error Handling Utilities
# =============================================================================


def _create_error_response(error_code: str, message: str, http_code: int = None) -> List[Dict]:
    """
    Create a standardized error response for provider API failures.

    Args:
        error_code: Machine-readable error code (e.g., 'authentication_failed')
        message: Human-readable error message
        http_code: HTTP status code if available

    Returns:
        List containing a single error dict with standardized format
    """
    error_dict = {"_error": error_code, "_message": message}
    if http_code:
        error_dict["_http_code"] = http_code
    return [error_dict]


def _classify_provider_error(
    provider_name: str,
    status_code: int = None,
    error_message: str = None,
    exception: Exception = None
) -> List[Dict]:
    """
    Classify provider errors and return standardized error response.

    This function centralizes error classification logic for all model providers,
    ensuring consistent error codes and messages across different providers.

    Args:
        provider_name: Name of the provider (for logging and messages)
        status_code: HTTP status code if available
        error_message: Error message from API if available
        exception: Exception object if available

    Returns:
        List containing a single error dict with standardized format
    """
    # Classify by HTTP status code
    if status_code:
        if status_code == 401:
            logger.error(
                f"{provider_name} API authentication failed: Invalid API key")
            return _create_error_response(
                "authentication_failed",
                "Invalid API key or authentication failed",
                status_code
            )
        elif status_code == 403:
            logger.error(
                f"{provider_name} API access forbidden: Insufficient permissions")
            return _create_error_response(
                "access_forbidden",
                "Access forbidden. Please check your permissions",
                status_code
            )
        elif status_code == 404:
            logger.error(
                f"{provider_name} API endpoint not found: URL may be incorrect")
            return _create_error_response(
                "endpoint_not_found",
                "API endpoint not found. Please verify the URL",
                status_code
            )
        elif status_code >= 500:
            logger.error(f"{provider_name} server error: HTTP {status_code}")
            return _create_error_response(
                "server_error",
                f"Server error (HTTP {status_code})",
                status_code
            )
        elif status_code >= 400:
            logger.error(
                f"{provider_name} API error (HTTP {status_code}): {error_message}")
            return _create_error_response(
                "api_error",
                f"API error (HTTP {status_code})",
                status_code
            )

    # Classify by exception type
    if exception:
        # aiohttp exceptions
        if isinstance(exception, aiohttp.ClientConnectorError):
            error_str = str(exception).lower()
            if "certificate" in error_str or "ssl" in error_str:
                logger.error(
                    f"{provider_name} SSL certificate error: {exception}")
                return _create_error_response(
                    "ssl_error",
                    "SSL certificate error. Please check the URL and SSL configuration"
                )
            else:
                logger.error(f"{provider_name} connection failed: {exception}")
                return _create_error_response(
                    "connection_failed",
                    f"Failed to connect to {provider_name}. Please check the URL and network connection"
                )
        elif isinstance(exception, aiohttp.ServerTimeoutError):
            logger.error(f"{provider_name} server timeout: {exception}")
            return _create_error_response(
                "timeout",
                "Connection timed out. Please check the URL and network connection"
            )
        elif isinstance(exception, aiohttp.ServerDisconnectedError):
            logger.error(f"{provider_name} server disconnected: {exception}")
            return _create_error_response(
                "connection_failed",
                f"Connection to {provider_name} was interrupted. Please try again"
            )
        elif isinstance(exception, aiohttp.ContentTypeError):
            logger.error(
                f"{provider_name} invalid response format: {exception}")
            return _create_error_response(
                "invalid_response",
                "Invalid response from provider API"
            )

        # httpx exceptions
        if isinstance(exception, httpx.HTTPStatusError):
            status = exception.response.status_code
            error_text = str(exception)
            return _classify_provider_error(provider_name, status_code=status, error_message=error_text)
        elif isinstance(exception, httpx.ConnectTimeout):
            logger.error(f"{provider_name} connection timeout: {exception}")
            return _create_error_response(
                "timeout",
                "Connection timed out. Please check the URL and network connection"
            )
        elif isinstance(exception, httpx.ReadTimeout):
            logger.error(f"{provider_name} read timeout: {exception}")
            return _create_error_response(
                "timeout",
                "Reading data timed out. Please try again"
            )
        elif isinstance(exception, (httpx.ConnectError, httpx.NetworkError)):
            logger.error(f"{provider_name} network error: {exception}")
            return _create_error_response(
                "connection_failed",
                f"Failed to connect to {provider_name}. Please check the URL and network connection"
            )
        elif isinstance(exception, httpx.InvalidURL):
            logger.error(f"{provider_name} invalid URL: {exception}")
            return _create_error_response(
                "invalid_url",
                "Invalid provider URL. Please verify the configuration"
            )
        elif isinstance(exception, httpx.InvalidResponse):
            logger.error(f"{provider_name} invalid response: {exception}")
            return _create_error_response(
                "invalid_response",
                "Invalid response from provider API"
            )

    # Generic connection error fallback
    error_msg = error_message or str(
        exception) if exception else "Unknown error"
    logger.error(f"{provider_name} error: {error_msg}")
    return _create_error_response(
        "connection_failed",
        f"Failed to connect to {provider_name}. Please check the URL and network connection"
    )


class AbstractModelProvider(ABC):
    """Common interface that all model provider integrations must implement."""

    @abstractmethod
    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """Return a list of models provided by the concrete provider."""
        raise NotImplementedError


class SiliconModelProvider(AbstractModelProvider):
    """Concrete implementation for SiliconFlow provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from SiliconFlow API.

        Args:
            provider_config: Configuration dict containing model_type and api_key

        Returns:
            List of models with canonical fields. Returns error dict if API call fails.
        """
        try:
            model_type: str = provider_config["model_type"]
            model_api_key: str = provider_config["api_key"]

            headers = {"Authorization": f"Bearer {model_api_key}"}

            # Choose endpoint by model type
            if model_type in ("llm", "vlm"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=chat"
            elif model_type in ("embedding", "multi_embedding"):
                silicon_url = f"{SILICON_GET_URL}?sub_type=embedding"
            else:
                silicon_url = SILICON_GET_URL

            async with httpx.AsyncClient(verify=False) as client:
                response = await client.get(silicon_url, headers=headers)
                response.raise_for_status()
                model_list: List[Dict] = response.json()["data"]

            # Annotate models with canonical fields expected downstream
            if model_type in ("llm", "vlm"):
                for item in model_list:
                    item["model_tag"] = "chat"
                    item["model_type"] = model_type
                    item["max_tokens"] = DEFAULT_LLM_MAX_TOKENS
            elif model_type in ("embedding", "multi_embedding"):
                for item in model_list:
                    item["model_tag"] = "embedding"
                    item["model_type"] = model_type

            # Return empty list to indicate successful API call but no models
            if not model_list:
                return []

            return model_list
        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            return _classify_provider_error("SiliconFlow", exception=e)


class ModelEngineProvider(AbstractModelProvider):
    """Concrete implementation for ModelEngine provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from ModelEngine API.

        Args:
            provider_config: Configuration dict containing model_type, base_url, and api_key

        Returns:
            List of models with canonical fields. Returns error dict if API call fails.
        """
        try:
            model_type: str = provider_config.get("model_type", "")
            host = provider_config.get("base_url")
            api_key = provider_config.get("api_key")
            model_engine_url = get_model_engine_raw_url(host)
            if not host or not api_key:
                logger.warning("ModelEngine host or api key not configured")
                return []

            headers = {"Authorization": f"Bearer {api_key}"}

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(ssl=False)
            ) as session:
                async with session.get(
                    f"{model_engine_url.rstrip('/')}/{MODEL_ENGINE_NORTH_PREFIX}/models",
                    headers=headers
                ) as response:
                    # Use centralized error classification
                    if response.status >= 400:
                        error_text = await response.text()
                        return _classify_provider_error(
                            "ModelEngine",
                            status_code=response.status,
                            error_message=error_text
                        )

                    data = await response.json()
                    all_models = data.get("data", [])
                    logger.info(
                        f"ModelEngine API returned {len(all_models)} models")

            # Type mapping from ModelEngine to internal types
            type_map = {
                "embed": "embedding",
                "chat": "llm",
                "asr": "stt",
                "tts": "tts",
                "rerank": "rerank",
                "multimodal": "vlm",
            }

            logger.info(f"Filtering models by type: '{model_type}'")
            filtered_models = []
            for model in all_models:
                me_type = model.get("type", "")
                internal_type = type_map.get(me_type)

                # If model_type filter is provided, only include matching models
                if model_type and internal_type != model_type:
                    logger.debug(
                        f"Model '{model.get('id', 'unknown')}' skipped: "
                        f"type '{me_type}' doesn't match filter '{model_type}'"
                    )
                    continue

                if internal_type:
                    filtered_models.append({
                        "id": model.get("id", ""),
                        "model_type": internal_type,
                        "model_tag": me_type,
                        "max_tokens": DEFAULT_LLM_MAX_TOKENS if internal_type in ("llm", "vlm") else 0,
                        "base_url": host,
                        "api_key": api_key,
                    })

            return filtered_models
        except Exception as e:
            return _classify_provider_error("ModelEngine", exception=e)


async def prepare_model_dict(provider: str, model: dict, model_url: str, model_api_key: str) -> dict:
    """
    Construct a model configuration dictionary that is ready to be stored in the
    database. This utility centralises the logic that was previously embedded in
    the *batch_create_models* route so that it can be reused elsewhere and keep
    the router implementation concise.

    Args:
        provider: Name of the model provider (e.g. "silicon", "openai", "modelengine").
        model:      A single model item coming from the provider list.
        model_url:  Base URL for the provider API.
        model_api_key: API key that should be saved together with the model.

    Returns:
        A dictionary ready to be passed to *create_model_record*.
    """

    # Split repo/name once so it can be reused multiple times.
    model_repo, model_name = split_repo_name(model["id"])
    model_display_name = add_repo_to_name(model_repo, model_name)

    # Initialize chunk size variables for all model types; only embeddings use them
    expected_chunk_size = None
    maximum_chunk_size = None
    chunk_batch = None

    # For embedding models, apply default values when chunk sizes are null
    if model["model_type"] in ["embedding", "multi_embedding"]:
        expected_chunk_size = model.get(
            "expected_chunk_size", DEFAULT_EXPECTED_CHUNK_SIZE)
        maximum_chunk_size = model.get(
            "maximum_chunk_size", DEFAULT_MAXIMUM_CHUNK_SIZE)
        chunk_batch = model.get("chunk_batch", 10)

    # For ModelEngine provider, extract the host from model's base_url
    # We'll append the correct path later
    if provider == ProviderEnum.MODELENGINE.value:
        # Get the raw host URL from model (e.g., "https://120.253.225.102:50001")
        raw_model_url = model.get("base_url", "")
        model_url = get_model_engine_raw_url(raw_model_url)

    # Build the canonical representation using the existing Pydantic schema for
    # consistency of validation and default handling.
    # For embedding/multi_embedding models, max_tokens will be set via connectivity check later,
    # so use 0 as placeholder if not provided
    model_type = model["model_type"]
    is_embedding_type = model_type in ["embedding", "multi_embedding"]
    max_tokens_value = model.get(
        "max_tokens", 0) if not is_embedding_type else 0

    model_obj = ModelRequest(
        model_factory=provider,
        model_name=model_name,
        model_type=model_type,
        api_key=model_api_key,
        max_tokens=max_tokens_value,
        display_name=model_display_name,
        expected_chunk_size=expected_chunk_size,
        maximum_chunk_size=maximum_chunk_size,
        chunk_batch=chunk_batch
    )

    model_dict = model_obj.model_dump()
    model_dict["model_repo"] = model_repo or ""

    # Determine the correct base_url and, for embeddings, update the actual
    # dimension by performing a real connectivity check.
    if model["model_type"] in ["embedding", "multi_embedding"]:
        if provider != ProviderEnum.MODELENGINE.value:
            model_dict["base_url"] = f"{model_url}embeddings"
        else:
            # For ModelEngine embedding models, append the embeddings path
            model_dict["base_url"] = f"{model_url.rstrip('/')}/{MODEL_ENGINE_NORTH_PREFIX}/embeddings"
        # The embedding dimension might differ from the provided max_tokens.
        model_dict["max_tokens"] = await embedding_dimension_check(model_dict)
    else:
        # For non-embedding models
        if provider == ProviderEnum.MODELENGINE.value:
            # Ensure ModelEngine models have the full API path
            model_dict["base_url"] = f"{model_url.rstrip('/')}/{MODEL_ENGINE_NORTH_PREFIX}"
        else:
            model_dict["base_url"] = model_url

    # ModelEngine models don't support SSL verification
    if provider == ProviderEnum.MODELENGINE.value:
        model_dict["ssl_verify"] = False

    # All newly created models start in NOT_DETECTED status.
    model_dict["connect_status"] = ModelConnectStatusEnum.NOT_DETECTED.value

    return model_dict


def merge_existing_model_tokens(model_list: List[dict], tenant_id: str, provider: str, model_type: str) -> List[dict]:
    """
    Merge existing model's max_tokens attribute into the model list

    Args:
        model_list: List of models
        tenant_id: Tenant ID
        provider: Provider
        model_type: Model type

    Returns:
        List[dict]: Merged model list
    """
    if model_type == "embedding" or model_type == "multi_embedding":
        return model_list

    existing_model_list = get_models_by_tenant_factory_type(
        tenant_id, provider, model_type)

    if not model_list or not existing_model_list:
        return model_list

    # Create a mapping table for existing models for quick lookup
    existing_model_map = {}
    for existing_model in existing_model_list:
        model_full_name = existing_model["model_repo"] + \
            "/" + existing_model["model_name"]
        existing_model_map[model_full_name] = existing_model

    # Iterate through the model list, if the model exists in the existing model list, add max_tokens attribute
    for model in model_list:
        if model.get("id") in existing_model_map:
            model["max_tokens"] = existing_model_map[model.get(
                "id")].get("max_tokens")

    return model_list


async def get_provider_models(model_data: dict) -> List[dict]:
    """
    Get model list based on provider

    Args:
        model_data: Model data containing provider information

    Returns:
        List[dict]: Model list
    """
    model_list = []

    if model_data["provider"] == ProviderEnum.SILICON.value:
        provider = SiliconModelProvider()
        model_list = await provider.get_models(model_data)
    elif model_data["provider"] == ProviderEnum.MODELENGINE.value:
        provider = ModelEngineProvider()
        model_list = await provider.get_models(model_data)

    return model_list


def get_model_engine_raw_url(model_engine_url: str) -> str:
    # Strip any existing path to get just the host
    model_engine_raw_url = model_engine_url
    if model_engine_url:
        # Remove any trailing /open/router/v1 or similar paths to get base host
        model_engine_raw_url = model_engine_url.split(
            "/open/")[0] if "/open/" in model_engine_url else model_engine_url
    return model_engine_raw_url
