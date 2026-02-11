import logging
from typing import List

from consts.const import (
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
)
from consts.model import ModelConnectStatusEnum, ModelRequest
from consts.provider import ProviderEnum
from database.model_management_db import get_models_by_tenant_factory_type
from services.model_health_service import embedding_dimension_check
from services.providers.base import AbstractModelProvider
from services.providers.silicon_provider import SiliconModelProvider
from services.providers.modelengine_provider import ModelEngineProvider, get_model_engine_raw_url, MODEL_ENGINE_NORTH_PREFIX
from utils.model_name_utils import split_repo_name, add_repo_to_name

logger = logging.getLogger("model_provider")


# =============================================================================
# Provider Factory and Public API
# =============================================================================


async def get_provider_models(model_data: dict) -> List[dict]:
    """
    Get model list based on provider.

    Args:
        model_data: Model data containing provider information

    Returns:
        List of models from the specified provider
    """
    model_list = []

    if model_data["provider"] == ProviderEnum.SILICON.value:
        provider = SiliconModelProvider()
        model_list = await provider.get_models(model_data)
    elif model_data["provider"] == ProviderEnum.MODELENGINE.value:
        provider = ModelEngineProvider()
        model_list = await provider.get_models(model_data)

    return model_list


# =============================================================================
# Model Dictionary Preparation
# =============================================================================


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
    Merge existing model's max_tokens attribute into the model list.

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


# Re-export provider classes for backward compatibility
__all__ = [
    "AbstractModelProvider",
    "SiliconModelProvider",
    "ModelEngineProvider",
    "prepare_model_dict",
    "merge_existing_model_tokens",
    "get_provider_models",
    "get_model_engine_raw_url",
]
