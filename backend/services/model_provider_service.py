import logging
from abc import ABC, abstractmethod
from typing import Dict, List

import httpx
import aiohttp

from consts.const import (
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
    MODEL_ENGINE_HOST,
    MODEL_ENGINE_APIKEY,
)
from consts.model import ModelConnectStatusEnum, ModelRequest
from consts.provider import SILICON_GET_URL, ProviderEnum
from consts.exceptions import TimeoutException
from database.model_management_db import get_models_by_tenant_factory_type
from services.model_health_service import embedding_dimension_check
from utils.model_name_utils import split_repo_name, add_repo_to_name

logger = logging.getLogger("model_provider_service")


class AbstractModelProvider(ABC):
    """Common interface that all model provider integrations must implement."""

    @abstractmethod
    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """Return a list of models provided by the concrete provider."""
        raise NotImplementedError


class SiliconModelProvider(AbstractModelProvider):
    """Concrete implementation for SiliconFlow provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
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

            return model_list
        except Exception as e:
            logger.error(f"Error getting models from silicon: {e}")
            return []


class ModelEngineProvider(AbstractModelProvider):
    """Concrete implementation for ModelEngine provider."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """
        Fetch models from ModelEngine API.
        
        Args:
            provider_config: Configuration dict containing model_type
            
        Returns:
            List of models with canonical fields
        """
        try:
            if not MODEL_ENGINE_HOST or not MODEL_ENGINE_APIKEY:
                logger.warning("ModelEngine environment variables not configured")
                return []

            model_type: str = provider_config.get("model_type", "")
            headers = {"Authorization": f"Bearer {MODEL_ENGINE_APIKEY}"}

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(ssl=False)
            ) as session:
                async with session.get(
                    f"{MODEL_ENGINE_HOST}/open/router/v1/models",
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    all_models = data.get("data", [])

            # Type mapping from ModelEngine to internal types
            type_map = {
                "embed": "embedding",
                "chat": "llm",
                "asr": "stt",
                "tts": "tts",
                "rerank": "rerank",
                "vlm": "vlm",
            }

            # Filter models by type if specified
            filtered_models = []
            for model in all_models:
                me_type = model.get("type", "")
                internal_type = type_map.get(me_type)
                
                # If model_type filter is provided, only include matching models
                if model_type and internal_type != model_type:
                    continue
                
                if internal_type:
                    filtered_models.append({
                        "id": model.get("id", ""),
                        "model_type": internal_type,
                        "model_tag": me_type,
                        "max_tokens": DEFAULT_LLM_MAX_TOKENS if internal_type in ("llm", "vlm") else 0,
                        # ModelEngine models will get base_url and api_key from environment
                        "base_url": MODEL_ENGINE_HOST,
                        "api_key": MODEL_ENGINE_APIKEY,
                    })

            return filtered_models
        except Exception as e:
            logger.error(f"Error getting models from ModelEngine: {e}")
            return []


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

    # For embedding models, apply default values when chunk sizes are null
    if model["model_type"] in ["embedding", "multi_embedding"]:
        expected_chunk_size = model.get("expected_chunk_size", DEFAULT_EXPECTED_CHUNK_SIZE)
        maximum_chunk_size = model.get("maximum_chunk_size", DEFAULT_MAXIMUM_CHUNK_SIZE)

    # For ModelEngine provider, extract the host from model's base_url
    # We'll append the correct path later
    if provider == ProviderEnum.MODELENGINE.value:
        # Get the raw host URL from model (e.g., "https://120.253.225.102:50001")
        raw_model_url = model.get("base_url", "")
        # Strip any existing path to get just the host
        if raw_model_url:
            # Remove any trailing /open/router/v1 or similar paths to get base host
            raw_model_url = raw_model_url.split("/open/")[0] if "/open/" in raw_model_url else raw_model_url
        model_url = raw_model_url
        model_api_key = model.get("api_key", model_api_key)

    # Build the canonical representation using the existing Pydantic schema for
    # consistency of validation and default handling.
    model_obj = ModelRequest(
        model_factory=provider,
        model_name=model_name,
        model_type=model["model_type"],
        api_key=model_api_key,
        max_tokens=model["max_tokens"],
        display_name=model_display_name,
        expected_chunk_size=expected_chunk_size,
        maximum_chunk_size=maximum_chunk_size
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
            model_dict["base_url"] = f"{model_url.rstrip('/')}/open/router/v1/embeddings"
        # The embedding dimension might differ from the provided max_tokens.
        model_dict["max_tokens"] = await embedding_dimension_check(model_dict)
    else:
        # For non-embedding models
        if provider == ProviderEnum.MODELENGINE.value:
            # Ensure ModelEngine models have the full API path
            model_dict["base_url"] = f"{model_url.rstrip('/')}/open/router/v1"
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
