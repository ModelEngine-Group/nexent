"""FastAPI App layer for model management endpoints.

This module exposes HTTP endpoints under the prefix "/model". It follows the App
layer contract:
- Parse and validate inputs using Pydantic models from `consts.model` and FastAPI parameters.
- Delegate business logic to services and database layer; do not implement core logic here.
- Map domain/service exceptions to HTTP where necessary; avoid leaking internals.
- Return structured responses consistent with existing patterns for backward compatibility.

Authorization: The bearer token is retrieved via the `authorization` header and
parsed with `utils.auth_utils.get_current_user_id`, then propagated as `user_id`
and `tenant_id` to services/database helpers.
"""

import logging

from consts.model import (
    BatchCreateModelsRequest,
    ModelRequest,
    ProviderModelRequest,
)

from fastapi import APIRouter, Header, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from http import HTTPStatus
from typing import List, Optional
from services.model_health_service import (
    check_model_connectivity,
    verify_model_config_connectivity,
)
from services.model_management_service import (
    create_model_for_tenant,
    create_provider_models_for_tenant,
    batch_create_models_for_tenant,
    list_provider_models_for_tenant,
    update_single_model_for_tenant,
    batch_update_models_for_tenant,
    delete_model_for_tenant,
    list_models_for_tenant,
    list_llm_models_for_tenant,
)
from utils.auth_utils import get_current_user_id


router = APIRouter(prefix="/model")
logger = logging.getLogger("model_management_app")


@router.post("/create")
async def create_model(request: ModelRequest, authorization: Optional[str] = Header(None)):
    """Create a single model record for the current tenant.

    Responsibilities (App layer):
    - Validate `ModelRequest` payload.
    - Normalize request fields (e.g., replace localhost in `base_url`).
    - Delegate embedding dimension checks and record creation to services/db.
    - Ensure display name uniqueness at the app boundary; map conflicts accordingly.

    Args:
        request: Model configuration payload.
        authorization: Bearer token header used to derive `user_id` and `tenant_id`.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        model_data = request.model_dump()
        logger.debug(
            f"Start to create model, user_id: {user_id}, tenant_id: {tenant_id}")
        await create_model_for_tenant(user_id, tenant_id, model_data)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model created successfully"
        })
    except ValueError as e:
        logging.error(f"Failed to create model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail="Failed to create model: name conflict")
    except Exception as e:
        logging.error(f"Failed to create model: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to create model")


@router.post("/provider/create")
async def create_provider_model(request: ProviderModelRequest, authorization: Optional[str] = Header(None)):
    """Create or refresh provider models for the current tenant in memory only.

    This endpoint fetches models from the specified provider and merges existing
    attributes (such as `max_tokens`). It does not persist new records; it
    returns the prepared model list for client consumption.

    Args:
        request: Provider and model type information.
        authorization: Bearer token header used to derive identity context.
    """
    try:
        provider_model_config = request.model_dump()
        _, tenant_id = get_current_user_id(authorization)
        model_list = await create_provider_models_for_tenant(tenant_id, provider_model_config)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Provider model created successfully",
            "data": model_list
        })
    except Exception as e:
        logging.error(f"Failed to create provider model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to create provider model")


@router.post("/provider/batch_create")
async def batch_create_models(request: BatchCreateModelsRequest, authorization: Optional[str] = Header(None)):
    """Synchronize provider models for a tenant by creating/updating/deleting records.

    The request includes the authoritative list of models for a provider/type.
    Existing models not present in the incoming list are deleted (soft delete),
    and missing ones are created. Existing models may be updated (e.g., `max_tokens`).

    Args:
        request: Batch payload with provider, type, models, and optional API key.
        authorization: Bearer token header used to derive identity context.

    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        batch_model_config = request.model_dump()
        await batch_create_models_for_tenant(user_id, tenant_id, batch_model_config)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Batch create models successfully"
        })
    except Exception as e:
        logging.error(f"Failed to batch create models: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to batch create models")


@router.post("/provider/list")
async def get_provider_list(request: ProviderModelRequest, authorization: Optional[str] = Header(None)):
    """List persisted models for a provider and type for the current tenant.

    Args:
        request: Provider and model type to filter.
        authorization: Bearer token header used to derive identity context.

    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        model_list = await list_provider_models_for_tenant(
            tenant_id, request.provider, request.model_type
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully retrieved provider list",
            "data": jsonable_encoder(model_list)
        })
    except Exception as e:
        logging.error(f"Failed to get provider list: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to get provider list")


@router.post("/update")
async def update_single_model(request: dict, authorization: Optional[str] = Header(None)):
    """Update a single model by its `model_id`.

    Performs a uniqueness check on `display_name` within the tenant and updates
    the record if valid.

    Args:
        request: Arbitrary model fields with required `model_id`.
        authorization: Bearer token header used to derive identity context.

    Raises:
        HTTPException: 409 if `display_name` conflicts, 500 for unexpected errors.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        await update_single_model_for_tenant(user_id, tenant_id, request)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model updated successfully"
        })
    except ValueError as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail="Failed to update model: name conflict")
    except Exception as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to update model")


@router.post("/batch_update")
async def batch_update_models(request: List[dict], authorization: Optional[str] = Header(None)):
    """Batch update multiple models for the current tenant.

    Args:
        request: List of partial model payloads with `model_id` fields.
        authorization: Bearer token header used to derive identity context.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        await batch_update_models_for_tenant(user_id, tenant_id, request)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Batch update models successfully"
        })
    except Exception as e:
        logging.error(f"Failed to batch update models: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to batch update models")


@router.post("/delete")
async def delete_model(display_name: str = Query(..., embed=True), authorization: Optional[str] = Header(None)):
    """Soft delete model(s) by `display_name` for the current tenant.

    Behavior:
    - If the model type is `embedding` or `multi_embedding`, both records with the
      same `display_name` will be deleted to keep them in sync.

    Args:
        display_name: Display name of the model to delete (unique key).
        authorization: Bearer token header used to derive identity context.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        logger.info(
            f"Start to delete model, user_id: {user_id}, tenant_id: {tenant_id}")
        model_name = await delete_model_for_tenant(user_id, tenant_id, display_name)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model deleted successfully",
            "data": model_name
        })
    except LookupError as e:
        logging.error(f"Failed to delete model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND,
                            detail="Failed to delete model: model not found")
    except Exception as e:
        logging.error(f"Failed to delete model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to delete model")


@router.get("/list")
async def get_model_list(authorization: Optional[str] = Header(None)):
    """Get detailed information for all models for the current tenant.

    Returns each model enriched with repo-qualified `model_name` and a normalized
    `connect_status` value.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        logger.debug(
            f"Start to list models, user_id: {user_id}, tenant_id: {tenant_id}")
        model_list = await list_models_for_tenant(tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully retrieved model list",
            "data": jsonable_encoder(model_list)
        })
    except Exception as e:
        logging.error(f"Failed to list models: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve model list")


@router.get("/llm_list")
async def get_llm_model_list(authorization: Optional[str] = Header(None)):
    """Get list of LLM models for the current tenant."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        llm_list = await list_llm_models_for_tenant(tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully retrieved LLM list",
            "data": jsonable_encoder(llm_list)
        })
    except Exception as e:
        logging.error(f"Failed to retrieve LLM list: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve LLM list")


@router.post("/healthcheck")
async def check_model_health(
        display_name: str = Query(..., description="Display name to check"),
        authorization: Optional[str] = Header(None)
):
    """Check and update model connectivity, returning the latest status.

    Args:
        display_name: Display name of the model to check.
        authorization: Bearer token header used to derive identity context.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = await check_model_connectivity(display_name, tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully checked model connectivity",
            "data": result
        })
    except LookupError as e:
        logging.error(f"Failed to check model connectivity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND,
                            detail="Model configuration not found")
    except ValueError as e:
        logging.error(f"Invalid model configuration: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="Invalid model configuration")
    except Exception as e:
        logging.error(f"Failed to check model connectivity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to check model connectivity")


@router.post("/temporary_healthcheck")
async def check_temporary_model_health(request: ModelRequest):
    """Verify connectivity for the provided model configuration without persisting it.

    Args:
        request: Model configuration to verify.
    """
    try:
        result = await verify_model_config_connectivity(request.model_dump())
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully verified model connectivity",
            "data": result
        },
        )
    except Exception as e:
        logging.error(f"Failed to verify model connectivity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Failed to verify model connectivity")
