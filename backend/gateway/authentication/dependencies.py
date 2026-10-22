# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
import uuid
from http import HTTPStatus
from typing import Optional

from consts.const import IS_SPEED_MODE
from contracts.authentication import CredentialKind, NorthboundContext
from contracts.errors.exceptions import LimitExceededError, UnauthorizedError
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gateway.authentication.policies import authenticate_identity
from management.db.identity.token import log_token_usage
from permissions.models import CurrentUser

_bearer_scheme = HTTPBearer(auto_error=False)


def authenticate(
    authorization: Optional[str] = Header(None),
    _credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    """Resolve the bearer token into a CurrentUser."""
    header_token = authorization
    if not header_token and _credentials:
        header_token = _credentials.credentials
    if not header_token and not IS_SPEED_MODE:
        raise HTTPException(status_code=401, detail="Not authenticated")
    principal = authenticate_identity(header_token, require_role=True)
    return CurrentUser(
        user_id=principal.user_id, tenant_id=principal.tenant_id, role=principal.role
    )


async def get_northbound_context(request: Request) -> NorthboundContext:
    """
    Build northbound context from request.

    Authentication: Bearer Token (API Key) in Authorization header
    - Authorization: Bearer <access_key>

    The user_id and tenant_id are derived from the access_key by querying
    user_token_info_t and user_tenant_t tables.

    Optional headers:
    - X-Request-Id: Request ID, generated if not provided
    """
    # 1. Validate Bearer Token and extract access_key
    try:
        auth_header = request.headers.get("Authorization")
        principal = authenticate_identity(auth_header, CredentialKind.API_KEY, request)
        resolved_user_id = principal.user_id
        resolved_tenant_id = principal.tenant_id
        token_id = principal.token_id

    except HTTPException:
        raise
    except LimitExceededError as e:
        logging.error(f"Too Many Requests: rate limit exceeded: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail="Too Many Requests: rate limit exceeded",
        )
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to validate bearer token: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail="Unauthorized: invalid API key"
        )

    if not resolved_user_id:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Missing user information for this access key",
        )

    if not resolved_tenant_id:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Missing tenant information for this access key",
        )

    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

    path = request.url.path
    service_logs_usage = (
        path == "/nb/v1/chat/run"
        or path.startswith("/nb/v1/chat/stop/")
        or (path.startswith("/nb/v1/conversations/") and path.endswith("/title"))
    )
    if token_id and token_id > 0 and not service_logs_usage:
        try:
            log_token_usage(
                token_id=token_id,
                call_function_name=request.url.path,
                related_id=None,
                created_by=resolved_user_id,
                metadata={"method": request.method, "request_id": request_id},
            )
        except Exception as exc:
            logging.warning("Failed to log northbound API key usage: %s", exc)

    # Get authorization header if present, otherwise use a placeholder
    auth_header_value = request.headers.get("Authorization", "Bearer placeholder")

    return NorthboundContext(
        request_id=request_id,
        tenant_id=resolved_tenant_id,
        user_id=resolved_user_id,
        authorization=auth_header_value,
        token_id=token_id,
    )
