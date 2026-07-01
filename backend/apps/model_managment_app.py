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
    CapacitySuggestionFields,
    ModelRequest,
    ModelCapacitySuggestionRequest,
    ModelCapacitySuggestionResponse,
    ProviderModelRequest,
    ManageTenantModelListRequest,
    ManageTenantModelListResponse,
    ManageTenantModelCreateRequest,
    ManageTenantModelUpdateRequest,
    ManageTenantModelDeleteRequest,
    ManageTenantModelHealthcheckRequest,
    ManageBatchCreateModelsRequest,
    ManageProviderModelListRequest,
    ManageProviderModelCreateRequest,
)
from consts.const import CAPACITY_SUGGESTION_ENABLED

from fastapi import APIRouter, Header, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from http import HTTPStatus
from typing import Annotated, List, Optional
from services.model_health_service import (
    check_model_connectivity,
    verify_model_config_connectivity,
)
from services.model_capacity_suggestion_service import suggest_capacity
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
    list_models_for_admin,
    get_capacity_coverage,
    pop_capacity_accept_signal,
    _record_capacity_suggestion_accept,
)
from utils.auth_utils import get_current_user_id


router = APIRouter(prefix="/model")
logger = logging.getLogger("model_management_app")


def _capacity_suggestion_response_to_model(result) -> ModelCapacitySuggestionResponse:
    suggestions = None
    if result.suggestions is not None:
        suggestions = CapacitySuggestionFields(
            context_window_tokens=result.suggestions.context_window_tokens,
            max_input_tokens=result.suggestions.max_input_tokens,
            max_output_tokens=result.suggestions.max_output_tokens,
            default_output_reserve_tokens=result.suggestions.default_output_reserve_tokens,
            tokenizer_family=result.suggestions.tokenizer_family,
        )

    return ModelCapacitySuggestionResponse(
        suggestions=suggestions,
        match_kind=result.match_kind.value,
        match_confidence=result.match_confidence.value if result.match_confidence else None,
        match_explanation=result.match_explanation,
        suggested_provider=result.suggested_provider,
        canonical_model_name=result.canonical_model_name,
        capability_profile_version=result.capability_profile_version,
        capacity_source_on_accept=result.capacity_source_on_accept,
    )


def _suggest_capacity_for_request(request: ModelCapacitySuggestionRequest) -> ModelCapacitySuggestionResponse:
    result = suggest_capacity(
        model_name=request.model_name,
        base_url=request.base_url,
        provider_hint=request.provider_hint,
        model_type=request.model_type,
        api_key=request.api_key,
        enabled=CAPACITY_SUGGESTION_ENABLED,
    )
    return _capacity_suggestion_response_to_model(result)


def _capacity_suggestion_for_model_request(request: ModelRequest):
    if not CAPACITY_SUGGESTION_ENABLED:
        return None

    try:
        suggestion_request = ModelCapacitySuggestionRequest(
            model_name=request.model_name,
            base_url=request.base_url,
            provider_hint=request.model_factory,
            api_key=request.api_key,
            model_type=request.model_type,
        )
        return _suggest_capacity_for_request(suggestion_request).model_dump()
    except ValueError as exc:
        logger.debug("Capacity suggestion unavailable for connectivity request: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Capacity suggestion failed during connectivity request: %s", exc)
        return None


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
        accept_signal = pop_capacity_accept_signal(model_data)
        logger.debug(
            f"Start to create model, user_id: {user_id}, tenant_id: {tenant_id}")
        await create_model_for_tenant(user_id, tenant_id, model_data)
        if accept_signal is not None:
            _record_capacity_suggestion_accept(
                accept_signal["match_kind"], request.model_factory
            )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model created successfully"
        })
    except ValueError as e:
        logging.error(f"Failed to create model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail=str(e))
    except Exception as e:
        logging.error(f"Failed to create model: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/suggest-capacity")
async def suggest_model_capacity(
    request: ModelCapacitySuggestionRequest,
    authorization: Optional[str] = Header(None),
):
    """Return a non-mutating capacity suggestion for a model add/edit form.

    Response uses the shared `/model/*` envelope ({message, data}) so the
    frontend service layer can unwrap it the same way as every other
    `/model/*` route. Returning the bare Pydantic model broke the dialog
    and coverage-banner integrations because the frontend reads
    `result.data` unconditionally.
    """
    try:
        get_current_user_id(authorization)
        result = _suggest_capacity_for_request(request)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully suggested model capacity",
            "data": jsonable_encoder(result),
        })
    except ValueError as e:
        logging.error(f"Invalid capacity suggestion request: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to suggest model capacity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/capacity-coverage")
async def get_model_capacity_coverage(authorization: Optional[str] = Header(None)):
    """Return bare-capacity LLM/VLM coverage for the current tenant.

    Wrapped in the shared `{message, data}` envelope; see
    `suggest_model_capacity` for the same rationale.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = get_capacity_coverage(tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully retrieved model capacity coverage",
            "data": jsonable_encoder(result),
        })
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to get model capacity coverage: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


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
                            detail=str(e))


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
        # Strip W11 accept-signal fields off every model entry before the
        # batch reaches the service/DB layer. Same audit-only contract as
        # the single-create path: pop now, emit the SLO counter on success.
        accept_signals = [
            signal
            for model in batch_model_config.get("models", [])
            if (signal := pop_capacity_accept_signal(model)) is not None
        ]
        await batch_create_models_for_tenant(user_id, tenant_id, batch_model_config)
        provider = batch_model_config.get("provider")
        for signal in accept_signals:
            _record_capacity_suggestion_accept(signal["match_kind"], provider)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Batch create models successfully"
        })
    except Exception as e:
        logging.error(f"Failed to batch create models: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


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
                            detail=str(e))


@router.post("/update")
async def update_single_model(
    request: dict,
    display_name: str = Query(..., description="Current display name of the model to update"),
    authorization: Optional[str] = Header(None)
):
    """Update a single model by its current `display_name`.

    The model is looked up using the `display_name` query parameter. The request
    body contains the fields to update, which may include a new `display_name`.

    Args:
        request: Arbitrary model fields to update (may include new display_name).
        display_name: Current display name of the model (query parameter for lookup).
        authorization: Bearer token header used to derive identity context.

    Raises:
        HTTPException: 404 if model not found, 409 if new `display_name` conflicts,
                       500 for unexpected errors.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        accept_signal = pop_capacity_accept_signal(request)
        await update_single_model_for_tenant(user_id, tenant_id, display_name, request)
        if accept_signal is not None:
            _record_capacity_suggestion_accept(
                accept_signal["match_kind"], request.get("model_factory")
            )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model updated successfully"
        })
    except LookupError as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND,
                            detail=str(e))
    except ValueError as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail=str(e))
    except Exception as e:
        logging.error(f"Failed to update model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


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
                            detail=str(e))


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
                            detail=str(e))
    except Exception as e:
        logging.error(f"Failed to delete model: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


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
                            detail=str(e))


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
                            detail=str(e))


@router.post("/healthcheck")
async def check_model_health(
        display_name: Annotated[str, Query(..., description="Display name to check")],
        model_type: Annotated[str, Query(..., description="...")],
        authorization: Optional[str] = Header(None)
):
    """Check and update model connectivity, returning the latest status.

    Args:
        display_name: Display name of the model to check.
        authorization: Bearer token header used to derive identity context.
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = await check_model_connectivity(display_name, tenant_id, model_type)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully checked model connectivity",
            "data": result
        })
    except LookupError as e:
        logging.error(f"Failed to check model connectivity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND,
                            detail=str(e))
    except ValueError as e:
        logging.error(f"Invalid model configuration: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail=str(e))
    except Exception as e:
        logging.error(f"Failed to check model connectivity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


@router.post("/temporary_healthcheck")
async def check_temporary_model_health(request: ModelRequest):
    """Verify connectivity for the provided model configuration without persisting it.

    Args:
        request: Model configuration to verify.
    """
    try:
        result = await verify_model_config_connectivity(request.model_dump())
        result["capacity_suggestion"] = (
            _capacity_suggestion_for_model_request(request)
            if result.get("connectivity") is True
            else None
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully verified model connectivity",
            "data": result
        },
        )
    except Exception as e:
        logging.error(f"Failed to verify model connectivity: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


# Manage Tenant Model CRUD Endpoints
# ---------------------------------------------------------------------------

@router.post("/manage/healthcheck")
async def manage_check_model_health(
    request: ManageTenantModelHealthcheckRequest,
    authorization: Optional[str] = Header(None)
):
    """Check and update model connectivity for a specified tenant (admin/manage operation).

    This endpoint allows checking connectivity for any tenant's model, typically used by super admins.

    Args:
        request: Query request with target tenant_id and model display_name.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        Connectivity check result with updated status.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to check model connectivity for tenant, user_id: {user_id}, "
            f"target_tenant_id: {request.tenant_id}, display_name: {request.display_name}")

        result = await check_model_connectivity(
            request.display_name,
            request.tenant_id
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully checked model connectivity",
            "data": result
        })
    except LookupError as e:
        logging.error(f"Failed to check model connectivity for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except ValueError as e:
        logging.error(f"Invalid model configuration: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to check model connectivity for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/manage/create")
async def manage_create_model(
    request: ManageTenantModelCreateRequest,
    authorization: Optional[str] = Header(None)
):
    """Create a model in a specified tenant (admin/manage operation).

    This endpoint allows creating models for any tenant, typically used by super admins.

    Args:
        request: Model configuration with target tenant_id.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        Success message on successful creation.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to create model for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}")

        model_data = request.model_dump(exclude={'tenant_id'})
        # Strip W11 accept-signal fields before the dict reaches the
        # service (which calls create_model_record -> SQLAlchemy insert).
        # Without the pop, the fields would fall through to .values() and
        # raise "Unconsumed column names"; without the recorder call,
        # operator-accepted suggestions saved by SU/asset-owner via
        # /manage/* would silently miss the accept_total SLO numerator.
        accept_signal = pop_capacity_accept_signal(model_data)
        await create_model_for_tenant(user_id, request.tenant_id, model_data)
        if accept_signal is not None:
            _record_capacity_suggestion_accept(
                accept_signal["match_kind"], request.model_factory
            )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model created successfully",
            "data": {"tenant_id": request.tenant_id}
        })
    except ValueError as e:
        logging.error(f"Failed to create model for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to create model for tenant: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/manage/update")
async def manage_update_model(
    request: ManageTenantModelUpdateRequest,
    authorization: Optional[str] = Header(None)
):
    """Update a model in a specified tenant (admin/manage operation).

    This endpoint allows updating models for any tenant, typically used by super admins.

    Args:
        request: Update payload with target tenant_id and current display_name.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        Success message on successful update.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to update model for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}, "
            f"current_display_name: {request.current_display_name}")

        model_data = request.model_dump(exclude={'tenant_id', 'current_display_name'}, exclude_unset=True)
        # Same audit-only contract as /manage/create above: pop before
        # the dict reaches update_model_record, emit after persist.
        accept_signal = pop_capacity_accept_signal(model_data)
        await update_single_model_for_tenant(
            user_id, request.tenant_id, request.current_display_name, model_data
        )
        if accept_signal is not None:
            _record_capacity_suggestion_accept(
                accept_signal["match_kind"], request.model_factory
            )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model updated successfully",
            "data": {"tenant_id": request.tenant_id}
        })
    except LookupError as e:
        logging.error(f"Failed to update model for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except ValueError as e:
        logging.error(f"Failed to update model for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to update model for tenant: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/manage/delete")
async def manage_delete_model(
    request: ManageTenantModelDeleteRequest,
    authorization: Optional[str] = Header(None)
):
    """Delete a model from a specified tenant (admin/manage operation).

    This endpoint allows deleting models from any tenant, typically used by super admins.

    Args:
        request: Delete request with target tenant_id and display_name.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        Success message with deleted model name.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to delete model for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}, "
            f"display_name: {request.display_name}")

        model_name = await delete_model_for_tenant(
            user_id, request.tenant_id, request.display_name
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Model deleted successfully",
            "data": {
                "tenant_id": request.tenant_id,
                "display_name": model_name
            }
        })
    except LookupError as e:
        logging.error(f"Failed to delete model for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to delete model for tenant: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/manage/batch_create")
async def manage_batch_create_models(
    request: ManageBatchCreateModelsRequest,
    authorization: Optional[str] = Header(None)
):
    """Batch create/update models in a specified tenant (admin/manage operation).

    This endpoint synchronizes provider models for any tenant by creating/updating/deleting records.
    Typically used by super admins to bulk import models.

    Args:
        request: Batch payload with target tenant_id, provider, type, api_key, and models list.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        Success message on completion.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to batch create models for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}, "
            f"provider: {request.provider}, type: {request.type}, models count: {len(request.models)}")

        batch_model_config = request.model_dump()
        # Mirror /provider/batch_create: pop W11 accept-signal fields per
        # model before the dict reaches the service/DB layer; emit the SLO
        # counter only after the batch persist call succeeds.
        accept_signals = [
            signal
            for model in batch_model_config.get("models", [])
            if (signal := pop_capacity_accept_signal(model)) is not None
        ]
        await batch_create_models_for_tenant(user_id, request.tenant_id, batch_model_config)
        for signal in accept_signals:
            _record_capacity_suggestion_accept(signal["match_kind"], request.provider)
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Batch create models successfully",
            "data": {
                "tenant_id": request.tenant_id,
                "provider": request.provider,
                "type": request.type,
                "models_count": len(request.models)
            }
        })
    except Exception as e:
        logging.error(f"Failed to batch create models for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/manage/list", response_model=ManageTenantModelListResponse)
async def manage_list_models(
    request: ManageTenantModelListRequest,
    authorization: Optional[str] = Header(None)
):
    """List models for a specified tenant (admin/manage operation).

    This endpoint allows querying models for any tenant, typically used by super admins.

    Args:
        request: Query request with target tenant_id and pagination params.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        Paginated model list for the specified tenant.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to list models for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}, "
            f"page: {request.page}, page_size: {request.page_size}")

        result = await list_models_for_admin(
            request.tenant_id,
            request.model_type,
            request.page,
            request.page_size
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully retrieved model list",
            "data": jsonable_encoder(result)
        })
    except Exception as e:
        logging.error(f"Failed to list models for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


@router.post("/manage/provider/list")
async def manage_list_provider_models(
    request: ManageProviderModelListRequest,
    authorization: Optional[str] = Header(None)
):
    """List provider models for a specified tenant (admin/manage operation).

    This endpoint fetches persisted models from a provider for any tenant,
    typically used by super admins when bulk importing models.

    Args:
        request: Query request with target tenant_id, provider, model_type.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        List of available provider models for the specified tenant.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to list provider models for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}, "
            f"provider: {request.provider}, model_type: {request.model_type}")

        model_list = await list_provider_models_for_tenant(
            request.tenant_id, request.provider, request.model_type
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully retrieved provider model list",
            "data": jsonable_encoder(model_list)
        })
    except Exception as e:
        logging.error(f"Failed to list provider models for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))


@router.post("/manage/provider/create")
async def manage_create_provider_models(
    request: ManageProviderModelCreateRequest,
    authorization: Optional[str] = Header(None)
):
    """Create/fetch provider models for a specified tenant (admin/manage operation).

    This endpoint fetches available models from a provider and prepares them for
    bulk importing into a specific tenant, typically used by super admins.

    Args:
        request: Query request with target tenant_id, provider, model_type, and optional api_key/base_url.
        authorization: Bearer token header used to derive `user_id`.

    Returns:
        List of available provider models for the specified tenant.
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        logger.debug(
            f"Start to create provider models for tenant, user_id: {user_id}, target_tenant_id: {request.tenant_id}, "
            f"provider: {request.provider}, model_type: {request.model_type}")

        # Build provider request dict for the service function
        provider_request = {
            "provider": request.provider,
            "model_type": request.model_type,
            "api_key": request.api_key,
            "base_url": request.base_url,
        }
        model_list = await create_provider_models_for_tenant(
            request.tenant_id, provider_request
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Successfully created provider models",
            "data": jsonable_encoder(model_list)
        })
    except Exception as e:
        logging.error(f"Failed to create provider models for tenant: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=str(e))
