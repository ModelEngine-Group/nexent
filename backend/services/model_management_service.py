import logging
from typing import List, Dict, Any, Optional

from consts.const import LOCALHOST_IP, LOCALHOST_NAME, DOCKER_INTERNAL_HOST
from consts.model import ModelConnectStatusEnum
from consts.provider import ProviderEnum, SILICON_BASE_URL

from database.model_management_db import (
    create_model_record,
    delete_model_record,
    get_model_by_display_name,
    get_models_by_display_name,
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
    split_repo_name,
    sort_models_by_id,
)
from utils.memory_utils import build_memory_config as build_memory_config_for_tenant
from services.vectordatabase_service import get_vector_db_core
from nexent.memory.memory_service import clear_model_memories

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
        model_data['ssl_verify'] = True
        if "open/router" in model_base_url:
            model_data['ssl_verify'] = False
        # Split model_name into repo and name
        model_repo, model_name = split_repo_name(
            model_data["model_name"]) if model_data.get("model_name") else ("", "")
        model_data["model_repo"] = model_repo if model_repo else ""
        model_data["model_name"] = model_name

        if not model_data.get("display_name"):
            model_data["display_name"] = add_repo_to_name(
                model_repo=model_data.get("model_repo", ""),
                model_name=model_data.get("model_name", "")
            )

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
            # Set default chunk_batch if not provided
            if model_data.get("chunk_batch") is None:
                model_data["chunk_batch"] = 10

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
        else:
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
        elif provider == ProviderEnum.MODELENGINE.value:
            # ModelEngine models carry their own base_url in each model dict
            model_url = ""
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
            model_repo, model_name_only = split_repo_name(
                model.get("id", "")) if model.get("id") else ("", "")
            model_display_name = add_repo_to_name(model_repo, model_name_only)
            if model_name:
                existing_model_by_display = get_model_by_display_name(
                    model_display_name, tenant_id)
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


async def update_single_model_for_tenant(
    user_id: str,
    tenant_id: str,
    current_display_name: str,
    model_data: Dict[str, Any]
):
    """Update model(s) by current display_name. If embedding/multi_embedding, update both types.

    Args:
        user_id: The user performing the update.
        tenant_id: The tenant context.
        current_display_name: The current display_name used to look up the model(s).
        model_data: The fields to update, which may include a new display_name.

    Raises:
        LookupError: If no model is found with the current_display_name.
        ValueError: If a new display_name conflicts with an existing model.
    """
    try:
        # Get all models with the current display_name (may be 1 or 2 for embedding types)
        existing_models = get_models_by_display_name(current_display_name, tenant_id)

        if not existing_models:
            raise LookupError(f"Model not found: {current_display_name}")

        # Check if a new display_name is being set and if it conflicts
        new_display_name = model_data.get("display_name")
        if new_display_name and new_display_name != current_display_name:
            conflict_models = get_models_by_display_name(new_display_name, tenant_id)
            if conflict_models:
                raise ValueError(
                    f"Name {new_display_name} is already in use, please choose another display name"
                )

        # Check if any of the existing models is multi_embedding
        has_multi_embedding = any(
            m.get("model_type") == "multi_embedding" for m in existing_models
        )

        if has_multi_embedding:
            # Update both embedding and multi_embedding records
            for model in existing_models:
                # Prepare update data, excluding model_type to preserve original type
                update_data = {k: v for k, v in model_data.items() if k not in ["model_id", "model_type"]}
                update_model_record(model["model_id"], update_data, user_id)
            logging.debug(
                f"Model {current_display_name} (embedding + multi_embedding) updated successfully")
        else:
            # Single model update
            current_model = existing_models[0]
            current_model_id = current_model["model_id"]
            update_data = {k: v for k, v in model_data.items() if k != "model_id"}
            update_model_record(current_model_id, update_data, user_id)
            logging.debug(f"Model {current_display_name} updated successfully")
    except LookupError:
        raise
    except ValueError:
        raise
    except Exception as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise Exception(f"Failed to update model: {str(e)}")


async def batch_update_models_for_tenant(user_id: str, tenant_id: str, model_list: List[Dict[str, Any]]):
    """Batch update models for a tenant."""
    try:
        for model in model_list:
            update_model_record(model["model_id"], model, user_id, tenant_id)

        logging.debug("Batch update models successfully")
    except Exception as e:
        logging.error(f"Failed to batch update models: {str(e)}")
        raise Exception(f"Failed to batch update models: {str(e)}")


async def delete_model_for_tenant(user_id: str, tenant_id: str, display_name: str):
    """Delete model(s) by display_name. If embedding/multi_embedding, delete both types."""
    try:
        # Get all models with this display_name (may be 1 or 2 for embedding types)
        models = get_models_by_display_name(display_name, tenant_id)
        if not models:
            raise LookupError(f"Model not found: {display_name}")

        deleted_types: List[str] = []

        # Check if any of the models is multi_embedding (which means we have both types)
        has_multi_embedding = any(
            m.get("model_type") == "multi_embedding" for m in models
        )

        if has_multi_embedding:
            # Best-effort memory cleanup for embedding models
            try:
                vdb_core = get_vector_db_core()
                base_memory_config = build_memory_config_for_tenant(tenant_id)
                for m in models:
                    try:
                        await clear_model_memories(
                            vdb_core=vdb_core,
                            model_repo=m.get("model_repo", ""),
                            model_name=m.get("model_name", ""),
                            embedding_dims=int(m.get("max_tokens") or 0),
                            base_memory_config=base_memory_config,
                        )
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Best-effort clear_model_memories failed for %s/%s dims=%s: %s",
                            m.get("model_repo", ""),
                            m.get("model_name", ""),
                            m.get("max_tokens"),
                            cleanup_exc,
                        )
            except Exception as outer_cleanup_exc:
                logger.warning(
                    "Memory cleanup preparation failed: %s", outer_cleanup_exc)

            # Delete all records with the same display_name
            for m in models:
                delete_model_record(m["model_id"], user_id, tenant_id)
                deleted_types.append(m.get("model_type", "unknown"))
        else:
            # Single model delete
            model = models[0]
            delete_model_record(model["model_id"], user_id, tenant_id)
            deleted_types.append(model.get("model_type", "unknown"))

        logging.debug(
            f"Successfully deleted model(s) in types: {', '.join(deleted_types)}")
        return display_name
    except LookupError:
        raise
    except Exception as e:
        logging.error(f"Failed to delete model: {str(e)}")
        raise Exception(f"Failed to delete model: {str(e)}")


async def list_models_for_tenant(tenant_id: str):
    """Get detailed information for all models for a tenant with normalized fields."""
    try:
        records = get_model_records(None, tenant_id)
        result: List[Dict[str, Any]] = []

        # Type mapping for backwards compatibility (chat -> llm for frontend)
        type_map = {
            "chat": "llm",
        }

        for record in records:
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"],
            )
            record["connect_status"] = ModelConnectStatusEnum.get_value(
                record.get("connect_status"))

            # Map model_type if necessary (for ModelEngine compatibility)
            if record.get("model_type") in type_map:
                record["model_type"] = type_map[record["model_type"]]

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


async def list_models_for_admin(
    tenant_id: str,
    model_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
) -> Dict[str, Any]:
    """Get models for a specified tenant (admin operation) with pagination.

    Args:
        tenant_id: Target tenant ID to query models for
        model_type: Optional model type filter (e.g., 'llm', 'embedding')
        page: Page number for pagination (1-indexed)
        page_size: Number of items per page

    Returns:
        Dict containing tenant_id, tenant_name, paginated models list, and pagination info
    """
    try:
        # Build filters
        filters = None
        if model_type:
            filters = {"model_type": model_type}

        # Get model records for the specified tenant
        records = get_model_records(filters, tenant_id)

        # Type mapping for backwards compatibility
        type_map = {
            "chat": "llm",
        }

        # Normalize model records
        normalized_models: List[Dict[str, Any]] = []
        for record in records:
            record["model_name"] = add_repo_to_name(
                model_repo=record["model_repo"],
                model_name=record["model_name"],
            )
            record["connect_status"] = ModelConnectStatusEnum.get_value(
                record.get("connect_status"))

            # Map model_type if necessary
            if record.get("model_type") in type_map:
                record["model_type"] = type_map[record["model_type"]]

            normalized_models.append(record)

        # Calculate pagination
        total = len(normalized_models)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        paginated_models = normalized_models[start_index:end_index]

        # Get tenant name
        from services.tenant_service import get_tenant_info
        try:
            tenant_info = get_tenant_info(tenant_id)
            tenant_name = tenant_info.get("tenant_name", "")
        except Exception:
            tenant_name = ""

        result = {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "models": paginated_models,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

        logging.debug(f"Successfully retrieved admin model list for tenant: {tenant_id}, page: {page}, page_size: {page_size}")
        return result
    except Exception as e:
        logging.error(f"Failed to retrieve admin model list: {str(e)}")
        raise Exception(f"Failed to retrieve admin model list: {str(e)}")




