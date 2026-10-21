# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Gateway-owned session, API-key and provider authentication adapters."""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
import jwt
from consts.const import (
    ASSET_OWNER_ROLE,
    ASSET_OWNER_TENANT_ID,
    DEBUG_JWT_EXPIRE_SECONDS,
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    IS_SPEED_MODE,
    JWT_EXPIRY_SECONDS,
    LANGUAGE,
    SERVICE_ROLE_KEY,
    SUPABASE_JWT_SECRET,
    SUPABASE_KEY,
    SUPABASE_URL,
)
from contracts.authentication import OAUTH_PENDING_PURPOSE
from contracts.exceptions import (
    LimitExceededError,
    TokenExpiredError,
    UnauthorizedError,
)
from fastapi import Header, Request
from gateway.authentication.credentials import extract_bearer_token
from gateway.authentication.internal import verify_internal_runtime_jwt
from infrastructure.security.internal_tokens import (
    INTERNAL_RUNTIME_JWT_AUDIENCE,
    INTERNAL_RUNTIME_JWT_ISSUER,
    INTERNAL_RUNTIME_JWT_SCOPE,
    INTERNAL_RUNTIME_JWT_TTL_SECONDS,
    generate_internal_runtime_jwt,
)
from infrastructure.security.signatures import (
    TIMESTAMP_VALIDITY_WINDOW,
    calculate_hmac_signature,
    validate_timestamp,
)
from management.db.identity.token import get_token_by_access_key
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.services.permission.identity.provider import (
    delete_supabase_user,
    get_supabase_admin_client,
    get_supabase_client,
)
from management.utils.request_context import get_user_language
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

# Module logger
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

# Fixed test secret used by generate_test_jwt and unit tests.
MOCK_JWT_SECRET_KEY = "nexent-mock-jwt-secret"


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
    from contracts.exceptions import SignatureValidationError

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
    user_tenant_record = get_user_tenant_by_user_id(user_id)
    if not user_tenant_record or not user_tenant_record.get("tenant_id"):
        raise TokenExpiredError("No active tenant relationship for this access key")
    tenant_id = user_tenant_record["tenant_id"]

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "token_id": token_info.get("token_id"),
    }


def resolve_tenant_id_from_user_tenant_record(user_tenant: Dict[str, Any]) -> str:
    """
    Resolve the effective tenant_id from a user_tenant_t record.

    ASSET_OWNER users may have an empty legacy tenant_id; map them to the
    virtual ASSET_OWNER tenant. Fall back to DEFAULT_TENANT_ID when unset.
    """
    tenant_id = user_tenant.get("tenant_id")
    if tenant_id:
        return tenant_id

    user_role = (user_tenant.get("user_role") or "").upper()
    if user_role == ASSET_OWNER_ROLE:
        return ASSET_OWNER_TENANT_ID

    return DEFAULT_TENANT_ID


def get_jwt_expiry_seconds(token: str) -> int:
    """
    Get expiration time from JWT token (seconds)

    Args:
        token: JWT token string

    Returns:
        int: Token validity period (seconds), returns configured default if parsing fails
    """
    try:
        # Speed mode: treat sessions as never expiring
        if IS_SPEED_MODE:
            # 10 years in seconds
            return 10 * 365 * 24 * 60 * 60
        # Ensure token is pure JWT, remove possible Bearer prefix
        jwt_token = extract_bearer_token(token)

        # If debug expiration time is set, return directly for quick debugging
        if DEBUG_JWT_EXPIRE_SECONDS > 0:
            return DEBUG_JWT_EXPIRE_SECONDS

        # Decode JWT token with signature verification. Expiration validation is
        # disabled intentionally because callers need the original exp/iat span.
        decoded = _decode_jwt_token_for_expiry(jwt_token)

        # Extract expiration time and issued time from JWT claims
        exp = int(decoded["exp"])
        iat = int(decoded["iat"])

        # Calculate validity period (seconds)
        expiry_seconds = exp - iat
        if expiry_seconds <= 0:
            raise ValueError("JWT exp must be greater than iat")

        return expiry_seconds
    except Exception as e:
        logging.warning(f"Failed to get expiration time from token: {str(e)}")
        return JWT_EXPIRY_SECONDS


def calculate_expires_at(token: Optional[str] = None) -> int:
    """
    Calculate session expiration time (consistent with Supabase JWT expiration time)

    Args:
        token: Optional JWT token to get actual expiration time

    Returns:
        int: Expiration time timestamp
    """
    # Speed mode: far future expiration
    if IS_SPEED_MODE:
        return int((datetime.now() + timedelta(days=3650)).timestamp())

    expiry_seconds = get_jwt_expiry_seconds(token) if token else JWT_EXPIRY_SECONDS
    return int((datetime.now() + timedelta(seconds=expiry_seconds)).timestamp())


def _decode_jwt_token_for_expiry(token: str) -> dict:
    """
    Decode JWT claims for session timing after verifying the token signature.

    Expiration validation is intentionally disabled so callers can compute the
    original token lifetime even when the token is already expired.
    """
    if not SUPABASE_JWT_SECRET:
        raise TokenExpiredError("JWT verification is not configured")

    return jwt.decode(
        token,
        SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_aud": False},
    )


def _decode_jwt_token(authorization: str) -> dict:
    """
    Extract user ID from JWT token after verifying signature and expiration.

    Args:
        authorization: Authorization header value

    Raises:
        UnauthorizedError: If token is invalid, expired, or signature verification fails
    """
    if not SUPABASE_JWT_SECRET:
        logging.error(
            "SUPABASE_JWT_SECRET (or JWT_SECRET) is not configured; cannot verify JWT"
        )
        raise TokenExpiredError("JWT verification is not configured")

    try:
        # Format authorization header
        token = extract_bearer_token(authorization)

        # Decode and verify JWT (signature + expiration)
        # verify_aud=False: allow tokens with aud claim (e.g. test JWT, Supabase) without strict audience check
        claims = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_aud": False},
        )
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if (
            claims.get("iss") == INTERNAL_RUNTIME_JWT_ISSUER
            or INTERNAL_RUNTIME_JWT_AUDIENCE in audiences
            or claims.get("scope") == INTERNAL_RUNTIME_JWT_SCOPE
            or claims.get("purpose") == OAUTH_PENDING_PURPOSE
        ):
            raise TokenExpiredError("Invalid session credential policy")
        return claims
    except jwt.ExpiredSignatureError:
        logging.warning("Token expired")
        raise TokenExpiredError("Token has expired")
    except jwt.InvalidSignatureError:
        logging.warning("JWT signature verification failed")
        raise TokenExpiredError("Invalid or expired authentication token")
    except jwt.InvalidTokenError as e:
        logging.warning(f"Invalid JWT: {e}")
        raise TokenExpiredError("Invalid or expired authentication token")
    except UnauthorizedError:
        raise
    except Exception as e:
        logging.error(f"Failed to decode token: {str(e)}")
        raise TokenExpiredError("Invalid or expired authentication token")


def _extract_user_id_from_jwt_token(authorization: str) -> Optional[str]:
    """
    Extract user ID from JWT token after verifying signature and expiration.
    """
    decoded = _decode_jwt_token(authorization)
    return decoded.get("sub")


def extract_session_id_from_authorization(
    authorization: Optional[str],
) -> Optional[str]:
    """Extract the sid claim without enforcing token validity, for idempotent logout."""
    if not authorization:
        return None
    try:
        token = extract_bearer_token(authorization)
        decoded = jwt.decode(token, options={"verify_signature": False})
        sid = decoded.get("sid")
        return str(sid) if sid else None
    except Exception:
        return None


def ensure_cas_session_active_from_authorization(authorization: Optional[str]) -> None:
    """Reject CAS-issued JWTs whose server-side session is expired or revoked."""
    session_id = extract_session_id_from_authorization(authorization)
    if not session_id:
        return

    from management.db.identity.cas_session import is_cas_session_active

    if not is_cas_session_active(str(session_id)):
        raise TokenExpiredError("CAS session has expired or been revoked")


def _resolve_session_user(authorization: Optional[str] = None) -> tuple[str, str]:
    """
    Get current user ID and tenant ID from authorization token

    Args:
        authorization: Authorization header value

    Returns:
        tuple[str, str]: (user_id, tenant_id)
    """
    # In speed mode, allow unauthenticated access with default user for demo/dev
    if IS_SPEED_MODE:
        logging.debug("Speed mode detected - returning default user ID and tenant ID")
        return DEFAULT_USER_ID, DEFAULT_TENANT_ID

    # In normal mode, missing auth header means unauthorized - return 401, not default user
    if authorization is None or (
        isinstance(authorization, str) and not authorization.strip()
    ):
        raise TokenExpiredError("No authorization header provided")

    try:
        decoded = _decode_jwt_token(authorization)
        user_id = decoded.get("sub")
        if not user_id:
            raise TokenExpiredError("Invalid or expired authentication token")

        ensure_cas_session_active_from_authorization(authorization)

        user_tenant_record = get_user_tenant_by_user_id(user_id)
        if user_tenant_record and user_tenant_record.get("tenant_id"):
            tenant_id = user_tenant_record["tenant_id"]
            logging.debug(f"Found tenant ID for user {user_id}: {tenant_id}")
        else:
            tenant_id = DEFAULT_TENANT_ID
            logging.warning(
                f"No tenant relationship found for user {user_id}, using default tenant"
            )

        return user_id, tenant_id

    except UnauthorizedError:
        raise
    except Exception as e:
        logging.error(f"Failed to get user ID and tenant ID: {str(e)}")
        raise TokenExpiredError("Invalid or expired authentication token")


def get_current_user_context(
    authorization: Optional[str] = None,
) -> tuple[str, str, str]:
    """Return the authenticated user ID, tenant ID, and normalized role."""
    user_id, tenant_id = get_current_user_id(authorization)

    if IS_SPEED_MODE:
        return user_id, tenant_id, "SPEED"

    user_tenant_record = get_user_tenant_by_user_id(user_id)
    if not user_tenant_record:
        raise TokenExpiredError("User tenant relationship not found")

    user_role = str(user_tenant_record.get("user_role") or "").upper()
    if not user_role:
        raise TokenExpiredError("User role not found")

    return (
        user_id,
        resolve_tenant_id_from_user_tenant_record(user_tenant_record),
        user_role,
    )


# ---------------------------------------------------------------------------
# Simple JWT helpers for tests and tooling
# ---------------------------------------------------------------------------


def generate_test_jwt(user_id: str, expires_in: Optional[int] = None) -> str:
    if expires_in is None:
        expires_in = JWT_EXPIRY_SECONDS
    """
    Generate a simple unsigned JWT for testing purposes (HS256 with dummy secret)
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + expires_in,
        "iss": "nexent-test",
        "aud": "nexent-api",
    }
    # Use a fixed test secret to avoid external dependencies in tests
    return jwt.encode(payload, MOCK_JWT_SECRET_KEY, algorithm="HS256")


def generate_session_jwt(
    user_id: str, expires_in: Optional[int] = None, session_id: str = None
) -> str:
    """Generate a signed JWT compatible with the existing auth verification flow."""
    if expires_in is None:
        expires_in = JWT_EXPIRY_SECONDS

    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now,
        "exp": now + expires_in,
        "iss": SUPABASE_URL,
    }
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def get_current_user_info(
    authorization: Optional[str] = None, request: Request = None
) -> tuple[str, str, str]:
    """
    Get current user information, including user ID, tenant ID, and language preference

    Args:
        authorization: Authorization header value
        request: FastAPI request object

    Returns:
        tuple[str, str, str]: (User ID, Tenant ID, Language code)
    """
    user_id, tenant_id = get_current_user_id(authorization)
    language = get_user_language(request)
    return user_id, tenant_id, language


def set_auth_token_to_client(client: Client, token: str) -> None:
    """Set token to client"""
    jwt_token = extract_bearer_token(token)

    try:
        # Only set access_token
        client.auth.access_token = jwt_token
    except Exception as e:
        logging.error(f"Set access token failed: {str(e)}")


def get_authorized_client(authorization: Optional[str] = Header(None)) -> Client:
    """Get token from authorization header and create authorized supabase client"""
    client = get_supabase_client()
    if authorization:
        token = extract_bearer_token(authorization)
        set_auth_token_to_client(client, token)
    return client


def get_current_user_from_client(
    client: Client, token: Optional[str] = None
) -> Optional[Any]:
    """Get current user from client using provided JWT, return user object or None"""
    try:
        # Prefer explicitly passing the JWT to avoid relying on client-side session state
        if token:
            jwt_token = extract_bearer_token(token)
            user_response = client.auth.get_user(jwt_token)
        else:
            user_response = client.auth.get_user()

        if user_response and getattr(user_response, "user", None):
            return user_response.user
        return None
    except Exception as e:
        logging.error(f"Get current user failed: {str(e)}")
        return None


def validate_token(token: str) -> Tuple[bool, Optional[Any]]:
    """Validate token function, return (is valid, user object)"""
    client = get_supabase_client()
    set_auth_token_to_client(client, token)
    try:
        user = get_current_user_from_client(client, token)
        if user:
            ensure_cas_session_active_from_authorization(token)
            return True, user
        return False, None
    except Exception as e:
        logging.error(f"Token validation failed: {str(e)}")
        return False, None


async def get_session_by_authorization(authorization):
    # Extract clean token from authorization header
    clean_token = extract_bearer_token(authorization)

    # Use the unified token validation function
    is_valid, user = validate_token(clean_token)
    if is_valid and user:
        user_role = "user"  # Default role
        if user.user_metadata and "role" in user.user_metadata:
            user_role = user.user_metadata["role"]
        return {"user": {"id": user.id, "email": user.email, "role": user_role}}
    else:
        # Use domain-specific exception for invalid/expired token
        raise UnauthorizedError("Session is invalid or expired")


def get_current_user_id(authorization: Optional[str] = None) -> tuple[str, str]:
    """Compatibility tuple over the shared gateway identity contract."""
    from gateway.authentication.policies import authenticate_identity

    principal = authenticate_identity(authorization)
    return principal.user_id, principal.tenant_id
