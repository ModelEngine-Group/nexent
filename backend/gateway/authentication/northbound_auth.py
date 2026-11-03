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
from gateway.authentication.auth import extract_bearer_token, require_active_account
from infrastructure.security.signatures import (
    calculate_hmac_signature,
    validate_timestamp,
)
from management.db.identity.token import get_token_by_access_key, log_token_usage
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.utils.request_context import get_user_language

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


def validate_bearer_token(authorization: Optional[str]) -> Tuple[bool, Optional[dict]]:
    """
    Validate Bearer token (API Key) from Authorization header.

    Args:
        authorization: Authorization header value (e.g., "Bearer nexent-xxxxx")

    Returns:
        Tuple of (is_valid, token_info_dict)
        - is_valid: True if token exists and is active
        - token_info: Token information dict if valid, None otherwise
    """
    if not authorization:
        logger.warning("No authorization header provided")
        return False, None

    # Extract token from "Bearer <token>" format
    try:
        token = extract_bearer_token(authorization)
    except UnauthorizedError:
        return False, None

    if not token:
        logger.warning("Empty bearer token")
        return False, None

    # Look up token in database
    try:
        token_info = get_token_by_access_key(token)
        if token_info and token_info.get("delete_flag") != "Y":
            require_active_account(token_info.get("user_id"))
            logger.debug(
                f"Token validated successfully for user {token_info.get('user_id')}"
            )
            return True, token_info
        else:
            logger.warning("Invalid or inactive token")
            return False, None
    except Exception as e:
        logger.error(f"Error validating bearer token: {str(e)}")
        return False, None


def get_user_and_tenant_by_access_key(access_key: str) -> Dict[str, str]:
    """
    Get user_id and tenant_id from access_key by querying user_token_info_t and user_tenant_t.

    Args:
        access_key: The access key (API Key) from the Authorization header.

    Returns:
        Dict containing user_id and tenant_id.

    Raises:
        UnauthorizedError: If the access key is not found or invalid.
    """
    if not access_key:
        raise TokenExpiredError("Invalid access key")

    # Query token from user_token_info_t
    token_info = get_token_by_access_key(access_key)
    if not token_info or token_info.get("delete_flag") == "Y":
        raise TokenExpiredError("Invalid or inactive access key")

    user_id = token_info.get("user_id")
    if not user_id:
        raise TokenExpiredError("No user associated with this access key")

    # Query tenant from user_tenant_t
    require_active_account(user_id)
    user_tenant_record = get_user_tenant_by_user_id(user_id)
    if not user_tenant_record or not user_tenant_record.get("tenant_id"):
        raise TokenExpiredError("No active tenant relationship for this access key")
    tenant_id = user_tenant_record["tenant_id"]

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "token_id": token_info.get("token_id"),
    }



def authenticate_api_key(authorization: Optional[str], request=None) -> AuthenticatedIdentity:
        valid, record = validate_bearer_token(authorization)
        if not valid or not record:
            raise TokenExpiredError("Invalid or missing bearer token")
        resolved = get_user_and_tenant_by_access_key(
            extract_bearer_token(authorization)
        )
        return AuthenticatedIdentity(
            resolved.get("user_id") or "",
            resolved.get("tenant_id") or "",
            token_id=resolved.get("token_id"),
            language=get_user_language(request),
            kind=CredentialKind.API_KEY,
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
