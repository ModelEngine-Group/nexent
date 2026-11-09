# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""API-key and AK/SK authentication for northbound requests."""

import hmac
import logging
import uuid
from http import HTTPStatus
from typing import Dict, Optional, Tuple

from contracts.authentication import (
    AuthenticatedIdentity,
    CredentialKind,
    NorthboundContext,
)
from contracts.constants.constants import DEFAULT_TENANT_ID
from contracts.errors.exceptions import (
    LimitExceededError,
    TokenExpiredError,
    UnauthorizedError,
)
from fastapi import HTTPException, Request
from management.services.permission.identity.session import extract_bearer_token, require_active_account
from infrastructure.security.signatures import (
    calculate_hmac_signature,
    validate_timestamp,
)
from management.db.identity.token import get_token_by_access_key, log_token_usage
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from infrastructure.web.request_context import get_user_language

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AK/SK (Access Key / Secret Key) authentication helpers
# ---------------------------------------------------------------------------

# Validity window in seconds for X-Timestamp header.


def extract_aksk_headers(headers: Dict[str, str]) -> Tuple[str, str, str]:
    """Extract AK/SK headers or raise TokenExpiredError when missing."""
    access_key = headers.get("X-Access-Key") if headers else None
    timestamp = headers.get("X-Timestamp") if headers else None
    signature = headers.get("X-Signature") if headers else None

    if not access_key or not timestamp or not signature:
        raise TokenExpiredError("Missing AK/SK authentication headers")

    return access_key, timestamp, signature


def get_aksk_config(tenant_id: str) -> Tuple[str, str]:
    """
    Get (access_key, secret_key) configuration for a tenant.

    This is intentionally a thin indirection so tests can monkeypatch it.
    """
    raise TokenExpiredError("AK/SK authentication is not configured")


def verify_aksk_signature(
    access_key: str, timestamp: str, signature: str, body: str, tenant_id: str = None
) -> bool:
    """Verify AK/SK signature; returns False instead of raising on mismatch."""
    tenant = tenant_id or DEFAULT_TENANT_ID
    try:
        expected_access_key, secret_key = get_aksk_config(tenant)
    except Exception:
        return False

    if access_key != expected_access_key:
        return False

    expected_sig = calculate_hmac_signature(secret_key, access_key, timestamp, body)
    return hmac.compare_digest(expected_sig, signature)


def validate_aksk_authentication(
    headers: Dict[str, str], body: str, tenant_id: str = None
) -> bool:
    """
    Validate AK/SK authentication.

    Returns True when valid, otherwise raises domain exceptions.
    """
    from contracts.errors.exceptions import SignatureValidationError

    try:
        access_key, ts, sig = extract_aksk_headers(headers)

        if not validate_timestamp(ts):
            raise TokenExpiredError("Invalid or expired timestamp")

        # Call with positional args so tests can monkeypatch with simple lambdas.
        if tenant_id is None:
            ok = verify_aksk_signature(access_key, ts, sig, body)
        else:
            ok = verify_aksk_signature(access_key, ts, sig, body, tenant_id)

        if not ok:
            raise SignatureValidationError("Invalid signature")

        return True
    except (UnauthorizedError, SignatureValidationError):
        raise
    except Exception as exc:
        logger.exception("Unexpected error during AK/SK authentication")
        raise TokenExpiredError("Authentication failed") from exc


# ---------------------------------------------------------------------------
# Bearer Token (API Key) authentication
# ---------------------------------------------------------------------------


def _require_api_key_record(access_key: str) -> dict:
    """Resolve one active credential and account for an authentication attempt."""
    if not access_key:
        raise TokenExpiredError("Invalid access key")
    record = get_token_by_access_key(access_key)
    if not record or record.get("delete_flag") == "Y":
        raise TokenExpiredError("Invalid or inactive access key")
    if not record.get("user_id"):
        raise TokenExpiredError("No user associated with this access key")
    require_active_account(record["user_id"])
    return record


def validate_bearer_token(authorization: Optional[str]) -> Tuple[bool, Optional[dict]]:
    """Keep the boolean compatibility API over the common credential resolver."""
    try:
        return True, _require_api_key_record(extract_bearer_token(authorization))
    except Exception as exc:
        logger.warning("API key validation failed (%s)", type(exc).__name__)
        return False, None


def get_user_and_tenant_by_access_key(access_key: str) -> Dict[str, str]:
    """Resolve the credential and its active tenant using one credential query."""
    record = _require_api_key_record(access_key)
    user_id = record["user_id"]
    membership = get_user_tenant_by_user_id(user_id)
    if not membership or not membership.get("tenant_id"):
        raise TokenExpiredError("No active tenant relationship for this access key")
    return {"user_id": user_id, "tenant_id": membership["tenant_id"], "token_id": record.get("token_id")}



def authenticate_api_key(authorization: Optional[str], request=None) -> AuthenticatedIdentity:
    from management.services.permission.identity.session import _gateway_identity

    identity = _gateway_identity("api_key")
    if identity is not None:
        return AuthenticatedIdentity(identity["user_id"], identity["tenant_id"],
                                     role=identity.get("role", ""), language=identity.get("language", "zh"),
                                     token_id=identity.get("token_id"), kind=CredentialKind.API_KEY)
    try:
        resolved = get_user_and_tenant_by_access_key(extract_bearer_token(authorization))
        if not resolved:
            raise TokenExpiredError("Invalid or missing bearer token")
    except Exception as exc:
        raise TokenExpiredError("Invalid or missing bearer token") from exc
    return AuthenticatedIdentity(resolved.get("user_id") or "", resolved.get("tenant_id") or "",
                                 token_id=resolved.get("token_id"), language=get_user_language(request),
                                 kind=CredentialKind.API_KEY)


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
        principal = authenticate_api_key(auth_header, request)
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
