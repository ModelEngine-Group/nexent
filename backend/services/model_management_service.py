import logging
from typing import List, Dict, Any, Optional

from consts.const import LOCALHOST_IP, LOCALHOST_NAME, DOCKER_INTERNAL_HOST
from consts.model import ModelConnectStatusEnum
from consts.provider import ProviderEnum, SILICON_BASE_URL

from database.model_management_db import (
    create_model_record,
    delete_model_record,
    get_model_by_display_name,
    get_model_records,
    get_models_by_tenant_factory_type,
    update_model_record,
)
from services.model_provider_service import (
    prepare_model_dict,
    merge_existing_model_tokens,
    get_provider_models,
)
from services.model_health_service import embedding_dimension_check
from utils.model_name_utils import (
    add_repo_to_name,
    split_display_name,
    split_repo_name,
    sort_models_by_id,
)

logger = logging.getLogger("model_management_service")


async def create_model_for_tenant(user_id: str, tenant_id: str, model_data: Dict[str, Any]):
    """Create a single model record for the given tenant.

    Raises ValueError on display name conflict or invalid input.
    """
    try:
        # Replace localhost with host.docker.internal for local llm
        model_base_url = model_data.get("base_url", "")
        if LOCALHOST_NAME in model_base_url or LOCALHOST_IP in model_base_url:
            model_data["base_url"] = (
                model_base_url.replace(LOCALHOST_NAME, DOCKER_INTERNAL_HOST)
                .replace(LOCALHOST_IP, DOCKER_INTERNAL_HOST)
            )

        # Split model_name into repo and name
        model_repo, model_name = split_repo_name(
            model_data["model_name"]) if model_data.get("model_name") else ("", "")
        model_data["model_repo"] = model_repo if model_repo else ""
        model_data["model_name"] = model_name

        if not model_data.get("display_name"):
            model_data["display_name"] = split_display_name(
                model_data.get("model_name", ""))

        # Use NOT_DETECTED status as default
        model_data["connect_status"] = model_data.get(
            "connect_status") or ModelConnectStatusEnum.NOT_DETECTED.value

        # Check display name conflict scoped by tenant
        if model_data.get("display_name"):
            existing_model_by_display = get_model_by_display_name(
                model_data["display_name"], tenant_id)
            if existing_model_by_display:
                logging.error(
                    f"Name {model_data['display_name']} is already in use, please choose another display name")
                raise ValueError(
                    f"Name {model_data['display_name']} is already in use, please choose another display name")

        # If embedding or multi_embedding, set max_tokens via embedding dimension check
        if model_data.get("model_type") in ("embedding", "multi_embedding"):
            model_data["max_tokens"] = await embedding_dimension_check(model_data)

        is_multimodal = model_data.get("model_type") == "multi_embedding"

        if is_multimodal:
            # Create multi_embedding record
            create_model_record(model_data, user_id, tenant_id)
            logging.debug(
                f"Multimodal embedding model {model_data['display_name']} created successfully")

            # Create embedding record variant
            embedding_data = model_data.copy()
            embedding_data["model_type"] = "embedding"
            create_model_record(embedding_data, user_id, tenant_id)
            logging.debug(
                f"Embedding model {embedding_data['display_name']} created successfully")

        # Non-multimodal
        create_model_record(model_data, user_id, tenant_id)
        logging.debug(
            f"Model {model_data['display_name']} created successfully")
    except Exception as e:
        logging.error(f"Failed to create model: {str(e)}")
        raise Exception(f"Failed to create model: {str(e)}")


async def create_provider_models_for_tenant(tenant_id: str, provider_request: Dict[str, Any]):
    """Create/refresh provider models in memory and merge existing attributes.

    Returns content dict with list data. Does not persist new records.
    """
    try:
        # Get provider model list
        model_list = await get_provider_models(provider_request)

        # Merge existing model's max_tokens attribute
        model_list = merge_existing_model_tokens(
            model_list, tenant_id, provider_request["provider"], provider_request["model_type"])

        # Sort model list by ID
        model_list = sort_models_by_id(model_list)

        logging.debug(
            f"Provider model {provider_request['provider']} created successfully")
        return model_list
    except Exception as e:
        logging.error(f"Failed to create provider models: {str(e)}")
        raise Exception(f"Failed to create provider models: {str(e)}")


async def batch_create_models_for_tenant(user_id: str, tenant_id: str, batch_payload: Dict[str, Any]):
    """Synchronize provider models for a tenant by creating/updating/deleting records."""
    try:
        provider = batch_payload["provider"]
        model_type = batch_payload["type"]
        model_list: List[Dict[str, Any]] = batch_payload.get("models", [])
        model_api_key: str = batch_payload.get("api_key", "")

        if provider == ProviderEnum.SILICON.value:
            model_url = SILICON_BASE_URL
        else:
            model_url = ""

        existing_model_list = get_models_by_tenant_factory_type(
            tenant_id, provider, model_type)
        model_list_ids = {model.get("id")
                          for model in model_list} if model_list else set()

        # Delete existing models not present
        for model in existing_model_list:
            model_full_name = model["model_repo"] + "/" + model["model_name"]
            if model_full_name not in model_list_ids:
                delete_model_record(model["model_id"], user_id, tenant_id)

        # Create or update new models
        for model in model_list:
            _, model_name = split_repo_name(
                model["id"]) if model.get("id") else ("", "")
            model_display_name = split_display_name(model.get("id", ""))
            if model_name:
                existing_model_by_display = get_model_by_display_name(
                    provider + "/" + model_display_name, tenant_id)
                if existing_model_by_display:
                    # Check if max_tokens has changed
                    existing_max_tokens = existing_model_by_display.get(
                        "max_tokens")
                    new_max_tokens = model.get("max_tokens")
                    if new_max_tokens is not None and existing_max_tokens != new_max_tokens:
                        update_model_record(existing_model_by_display["model_id"], {
                                            "max_tokens": new_max_tokens}, user_id)
                    continue

            model_dict = await prepare_model_dict(
                provider=provider,
                model=model,
                model_url=model_url,
                model_api_key=model_api_key,
            )
            create_model_record(model_dict, user_id, tenant_id)
            logging.debug(f"Model {model['id']} created successfully")
    except Exception as e:
        logging.error(f"Failed to batch create models: {str(e)}")
        raise Exception(f"Failed to batch create models: {str(e)}")


async def list_provider_models_for_tenant(tenant_id: str, provider: str, model_type: str):
    """List persisted models for a provider/type for a tenant."""
    try:
        model_list = get_models_by_tenant_factory_type(
            tenant_id, provider, model_type)
        for model in model_list:
            model["id"] = model["model_repo"] + "/" + model["model_name"]

        logging.debug(f"Provider model {provider} created successfully")
        return model_list
    except Exception as e:
        logging.error(f"Failed to list provider models: {str(e)}")
        raise Exception(f"Failed to list provider models: {str(e)}")


async def update_single_model_for_tenant(user_id: str, tenant_id: str, model_data: Dict[str, Any]):
    """Update a single model by its model_id, ensuring display_name uniqueness."""
    try:
        existing_model_by_display = get_model_by_display_name(
            model_data["display_name"], tenant_id)
        if existing_model_by_display and existing_model_by_display["model_id"] != model_data["model_id"]:
            raise ValueError(
                f"Name {model_data['display_name']} is already in use, please choose another display name")

        update_model_record(model_data["model_id"], model_data, user_id)
        logging.debug(
            f"Model {model_data['display_name']} updated successfully")
    except Exception as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise Exception(f"Failed to update model: {str(e)}")


async def batch_update_models_for_tenant(user_id: str, tenant_id: str, model_list: List[Dict[str, Any]]):
    """Batch update models for a tenant."""
    try:
        for model in model_list:
            update_model_record(model["model_id"], model, user_id)

        logging.debug("Batch update models successfully")
    except Exception as e:
        logging.error(f"Failed to batch update models: {str(e)}")
        raise Exception(f"Failed to batch update models: {str(e)}")


async def delete_model_for_tenant(user_id: str, tenant_id: str, display_name: str):
    """Delete model(s) by display_name. If embedding/multi_embedding, delete both types."""
    try:
        model = get_model_by_display_name(display_name, tenant_id)
        if not model:
            raise LookupError(f"Model not found: {display_name}")

        deleted_types: List[str] = []
        if model.get("model_type") in ["embedding", "multi_embedding"]:
            for t in ["embedding", "multi_embedding"]:
                m = get_model_by_display_name(display_name, tenant_id)
                if m and m.get("model_type") == t:
                    delete_model_record(m["model_id"], user_id, tenant_id)
                    deleted_types.append(t)
        else:
            delete_model_record(model["model_id"], user_id, tenant_id)
            deleted_types.append(model.get("model_type", "unknown"))

        logging.debug(
            f"Successfully deleted model(s) in types: {', '.join(deleted_types)}")
        return display_name
    except Exception as e:
        logging.error(f"Failed to delete model: {str(e)}")
        raise Exception(f"Failed to delete model: {str(e)}")


async def list_models_for_tenant(tenant_id: str):
    """Get detailed information for all models for a tenant with normalized fields."""
    try:
        records = get_model_records(None, tenant_id)
        result: List[Dict[str, Any]] = []
        for record in records:
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"],
            )
            record["connect_status"] = ModelConnectStatusEnum.get_value(
                record.get("connect_status"))
            result.append(record)

        logging.debug("Successfully retrieved model list")
        return result
    except Exception as e:
        logging.error(f"Failed to retrieve model list: {str(e)}")
        raise Exception(f"Failed to retrieve model list: {str(e)}")


async def list_llm_models_for_tenant(tenant_id: str):
    """Get detailed information for all models for a tenant with normalized fields."""
    try:
        records = get_model_records({"model_type": "llm"}, tenant_id)
        result: List[Dict[str, Any]] = []
        for record in records:
            result.append({
                "model_id": record["model_id"],
                "model_name": add_repo_to_name(
                    model_repo=record["model_repo"],
                    model_name=record["model_name"],
                ),
                "connect_status": ModelConnectStatusEnum.get_value(record.get("connect_status")),
                "display_name": record["display_name"],
                "api_key": record.get("api_key", ""),
                "base_url": record.get("base_url", ""),
                "max_tokens": record.get("max_tokens", 4096)
            })

        logging.debug("Successfully retrieved model list")
        return result
    except Exception as e:
        logging.error(f"Failed to retrieve model list: {str(e)}")
        raise Exception(f"Failed to retrieve model list: {str(e)}")




