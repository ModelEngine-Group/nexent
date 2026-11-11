# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP routes for operations-managed system configuration."""

import logging
from http import HTTPStatus

from configuration.catalog import DEFAULT_CATALOG, ConfigurationValidationError
from contracts.configuration import (
    SystemConfigurationChangesRequest,
    SystemConfigurationRecommendationRequest,
)
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from ops.services.authorization import (
    OperationsForbiddenError,
    OperationsUnauthorizedError,
    authorize_operations,
)
from ops.services.system_configuration import (
    list_system_configurations,
    save_system_configurations,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system_configurations", tags=["system-configurations"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"detail": {"code": code, "message": message}}
    )


def _authorization_error(error: PermissionError) -> JSONResponse:
    if isinstance(error, OperationsUnauthorizedError):
        return _error(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", str(error))
    return _error(HTTPStatus.FORBIDDEN, "FORBIDDEN", str(error))


@router.get("")
def get_configurations(authorization: str | None = Header(None)):
    try:
        authorize_operations(authorization)
        items = list_system_configurations()
    except (OperationsUnauthorizedError, OperationsForbiddenError) as error:
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
def patch_configurations(
    request: SystemConfigurationChangesRequest,
    authorization: str | None = Header(None),
):
    try:
        actor = authorize_operations(authorization)
        result = save_system_configurations(request.changes, actor=actor)
    except (OperationsUnauthorizedError, OperationsForbiddenError) as error:
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
    authorization: str | None = Header(None),
):
    try:
        authorize_operations(authorization)
        DEFAULT_CATALOG.definition(request.key)
    except (OperationsUnauthorizedError, OperationsForbiddenError) as error:
        return _authorization_error(error)
    except ConfigurationValidationError as error:
        return _error(HTTPStatus.BAD_REQUEST, "INVALID_CONFIGURATION_KEY", str(error))
    return _error(
        HTTPStatus.BAD_REQUEST,
        "RECOMMENDATION_UNAVAILABLE",
        "No reliable automatic recommendation rule is registered for this parameter",
    )
