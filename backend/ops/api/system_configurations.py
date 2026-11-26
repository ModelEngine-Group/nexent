# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP routes for operations-managed system configuration."""

import logging
from http import HTTPStatus

from contracts.configuration import (
    SystemConfigurationChangesRequest,
    SystemConfigurationRecommendationRequest,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from contracts.resource_denylist import GlobalDenylistUpdate
from management.services.configuration.resource_denylist import DenylistConflict, read_denylist, update_denylist
from management.services.permission.identity.session import authenticate
from infrastructure.system_configuration.catalog import (
    DEFAULT_CATALOG,
    ConfigurationValidationError,
)
from ops.services.authorization import (
    authorize_configuration_write,
    authorize_operations,
)
from ops.services.system_configuration import (
    list_system_configurations,
    run_system_configuration_io,
    save_system_configurations,
)
from permissions.models import CurrentUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system_configurations", tags=["system-configurations"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"detail": {"code": code, "message": message}}
    )


def _authorization_error(error: HTTPException) -> JSONResponse:
    if error.status_code == HTTPStatus.UNAUTHORIZED:
        return _error(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Authentication required")
    return _error(HTTPStatus.FORBIDDEN, "FORBIDDEN", "Operations permission required")


def _list_authorized_configurations(user):
    authorize_operations(user)
    return list_system_configurations()


def _save_authorized_configurations(changes, user):
    actor = authorize_configuration_write(user)
    return save_system_configurations(changes, actor=actor)


@router.get("/resource_denylist")
async def get_global_denylist(request: Request, user: CurrentUser = Depends(authenticate)):
    authorize_operations(user)
    return await run_system_configuration_io(request.app.state.thread_manager, read_denylist)


@router.put("/resource_denylist")
async def put_global_denylist(
    payload: GlobalDenylistUpdate, request: Request, user: CurrentUser = Depends(authenticate)
):
    actor = authorize_configuration_write(user)
    try:
        return await run_system_configuration_io(request.app.state.thread_manager, update_denylist, payload, actor)
    except DenylistConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def get_configurations(
    request: Request, user: CurrentUser = Depends(authenticate)
):
    try:
        items = await run_system_configuration_io(
            request.app.state.thread_manager,
            _list_authorized_configurations,
            user,
        )
    except HTTPException as error:
        return _authorization_error(error)
    except Exception:  # noqa: BLE001 - return a safe dependency error
        logger.error("System configuration query failed")
        return _error(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "CONFIGURATION_UNAVAILABLE",
            "Configuration database is unavailable",
        )
    return {"items": items, "total": len(items)}


@router.patch("")
async def patch_configurations(
    payload: SystemConfigurationChangesRequest,
    request: Request,
    user: CurrentUser = Depends(authenticate),
):
    try:
        result = await run_system_configuration_io(
            request.app.state.thread_manager,
            _save_authorized_configurations,
            payload.changes,
            user,
        )
    except HTTPException as error:
        return _authorization_error(error)
    except ConfigurationValidationError as error:
        return _error(HTTPStatus.BAD_REQUEST, "INVALID_CONFIGURATION", str(error))
    except Exception:  # noqa: BLE001 - return a safe dependency error
        logger.error("System configuration save failed")
        return _error(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "CONFIGURATION_UNAVAILABLE",
            "Configuration database is unavailable",
        )
    return {"saved": True, **result}


@router.post("/recommendations")
def recommend_configuration(
    request: SystemConfigurationRecommendationRequest,
    user: CurrentUser = Depends(authenticate),
):
    try:
        authorize_operations(user)
        DEFAULT_CATALOG.definition(request.key)
    except HTTPException as error:
        return _authorization_error(error)
    except ConfigurationValidationError as error:
        return _error(HTTPStatus.BAD_REQUEST, "INVALID_CONFIGURATION_KEY", str(error))
    return _error(
        HTTPStatus.BAD_REQUEST,
        "RECOMMENDATION_UNAVAILABLE",
        "No reliable automatic recommendation rule is registered for this parameter",
    )
