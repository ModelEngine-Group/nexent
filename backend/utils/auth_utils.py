import logging
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import jwt
from fastapi import Request
from supabase import create_client

from consts.const import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    IS_SPEED_MODE,
    SUPABASE_JWT_SECRET,
    SUPABASE_URL,
    SUPABASE_KEY,
    SERVICE_ROLE_KEY,
    DEBUG_JWT_EXPIRE_SECONDS,
    LANGUAGE,
)
from consts.exceptions import LimitExceededError, UnauthorizedError
from database.user_tenant_db import get_user_tenant_by_user_id
from database.token_db import get_token_by_access_key

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
TIMESTAMP_VALIDITY_WINDOW = 5 * 60


def calculate_hmac_signature(
    secret_key: str, access_key: str, timestamp: str, body: str
) -> str:
    """
    Calculate HMAC-SHA256 signature for AK/SK authentication.

    Returns a lowercase hex digest of length 64.
    """
    message = f"{access_key}\n{timestamp}\n{body}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def validate_timestamp(timestamp: str) -> bool:
    """Validate that timestamp is within allowed window."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = int(time.time())
    return abs(now - ts) <= TIMESTAMP_VALIDITY_WINDOW


def extract_aksk_headers(headers: Dict[str, str]) -> Tuple[str, str, str]:
    """Extract AK/SK headers or raise UnauthorizedError when missing."""
    access_key = headers.get("X-Access-Key") if headers else None
    timestamp = headers.get("X-Timestamp") if headers else None
    signature = headers.get("X-Signature") if headers else None

    if not access_key or not timestamp or not signature:
        raise UnauthorizedError("Missing AK/SK authentication headers")

    return access_key, timestamp, signature


def get_aksk_config(tenant_id: str) -> Tuple[str, str]:
    """
    Get (access_key, secret_key) configuration for a tenant.

    This is intentionally a thin indirection so tests can monkeypatch it.
    """
    raise UnauthorizedError("AK/SK authentication is not configured")


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
    from consts.exceptions import (
        SignatureValidationError,
    )  # imported lazily for test-time stubbing

    try:
        access_key, ts, sig = extract_aksk_headers(headers)

        if not validate_timestamp(ts):
            raise UnauthorizedError("Invalid or expired timestamp")

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
        raise UnauthorizedError("Authentication failed") from exc


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
    token = (
        authorization.replace("Bearer ", "")
        if authorization.startswith("Bearer ")
        else authorization
    )

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
            logger.warning(f"Invalid or inactive token: {token[:20]}...")
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
        raise UnauthorizedError("Invalid access key")

    # Query token from user_token_info_t
    token_info = get_token_by_access_key(access_key)
    if not token_info or token_info.get("delete_flag") == "Y":
        raise UnauthorizedError("Invalid or inactive access key")

    user_id = token_info.get("user_id")
    if not user_id:
        raise UnauthorizedError("No user associated with this access key")

    # Query tenant from user_tenant_t
    user_tenant_record = get_user_tenant_by_user_id(user_id)
    if user_tenant_record and user_tenant_record.get("tenant_id"):
        tenant_id = user_tenant_record["tenant_id"]
    else:
        tenant_id = DEFAULT_TENANT_ID
        logger.warning(
            f"No tenant relationship found for user {user_id}, using default tenant"
        )

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "token_id": token_info.get("token_id"),
    }


def get_supabase_client():
    """Get Supabase client instance with regular key (user-context operations)."""
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logging.error(f"Failed to create Supabase client: {str(e)}")
        return None


def get_supabase_admin_client():
    """Get Supabase client instance with service role key for admin operations."""
    try:
        return create_client(SUPABASE_URL, SERVICE_ROLE_KEY)
    except Exception as e:
        logging.error(f"Failed to create Supabase admin client: {str(e)}")
        return None


def get_jwt_expiry_seconds(token: str) -> int:
    """
    Get expiration time from JWT token (seconds)

    Args:
        token: JWT token string

    Returns:
        int: Token validity period (seconds), returns default value 3600 if parsing fails
    """
    try:
        # Speed mode: treat sessions as never expiring
        if IS_SPEED_MODE:
            # 10 years in seconds
            return 10 * 365 * 24 * 60 * 60
        # Ensure token is pure JWT, remove possible Bearer prefix
        jwt_token = (
            token.replace("Bearer ", "") if token.startswith("Bearer ") else token
        )

        # If debug expiration time is set, return directly for quick debugging
        if DEBUG_JWT_EXPIRE_SECONDS > 0:
            return DEBUG_JWT_EXPIRE_SECONDS

        # Decode JWT token (without signature verification, only parse content)
        decoded = jwt.decode(jwt_token, options={"verify_signature": False})

        # Extract expiration time and issued time from JWT claims
        exp = decoded.get("exp", 0)
        iat = decoded.get("iat", 0)

        # Calculate validity period (seconds)
        expiry_seconds = exp - iat

        return expiry_seconds
    except Exception as e:
        logging.warning(f"Failed to get expiration time from token: {str(e)}")
        return 3600  # supabase default setting


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

    expiry_seconds = get_jwt_expiry_seconds(token) if token else 3600
    return int((datetime.now() + timedelta(seconds=expiry_seconds)).timestamp())


def _extract_user_id_from_jwt_token(authorization: str) -> Optional[str]:
    """
    Extract user ID from JWT token after verifying signature and expiration.

    Args:
        authorization: Authorization header value

    Returns:
        Optional[str]: User ID, return None if parsing fails

    Raises:
        UnauthorizedError: If token is invalid, expired, or signature verification fails
    """
    if not SUPABASE_JWT_SECRET:
        logging.error(
            "SUPABASE_JWT_SECRET (or JWT_SECRET) is not configured; cannot verify JWT"
        )
        raise UnauthorizedError("JWT verification is not configured")

    try:
        # Format authorization header
        token = (
            authorization.replace("Bearer ", "")
            if authorization.startswith("Bearer ")
            else authorization
        )

        # Decode and verify JWT (signature + expiration)
        # verify_aud=False: allow tokens with aud claim (e.g. test JWT, Supabase) without strict audience check
        decoded = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_aud": False},
        )

        # Extract user ID from JWT claims
        user_id = decoded.get("sub")

        return user_id
    except jwt.ExpiredSignatureError:
        logging.warning("Token expired")
        raise UnauthorizedError("Token has expired")
    except jwt.InvalidSignatureError:
        logging.warning("JWT signature verification failed")
        raise UnauthorizedError("Invalid or expired authentication token")
    except jwt.InvalidTokenError as e:
        logging.warning(f"Invalid JWT: {e}")
        raise UnauthorizedError("Invalid or expired authentication token")
    except UnauthorizedError:
        raise
    except Exception as e:
        logging.error(f"Failed to extract user ID from token: {str(e)}")
        raise UnauthorizedError("Invalid or expired authentication token")


def get_current_user_id(authorization: Optional[str] = None) -> tuple[str, str]:
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
        raise UnauthorizedError("No authorization header provided")

    try:
        user_id = _extract_user_id_from_jwt_token(authorization)
        if not user_id:
            raise UnauthorizedError("Invalid or expired authentication token")

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

    except Exception as e:
        logging.error(f"Failed to get user ID and tenant ID: {str(e)}")
        raise UnauthorizedError("Invalid or expired authentication token")


def get_user_language(request: Request = None) -> str:
    """
    Get user language preference from request

    Args:
        request: FastAPI request object, used to get cookie

    Returns:
        str: Language code ('zh' or 'en'), default to 'zh'
    """
    default_language = LANGUAGE["ZH"]

    # Read language setting from cookie
    if request:
        try:
            if hasattr(request, "cookies") and request.cookies:
                cookie_locale = request.cookies.get("NEXT_LOCALE")
                if cookie_locale and cookie_locale in [LANGUAGE["ZH"], LANGUAGE["EN"]]:
                    return cookie_locale
        except (AttributeError, TypeError) as e:
            logging.warning(f"Error reading language from cookies: {e}")

    return default_language


# ---------------------------------------------------------------------------
# Simple JWT helpers for tests and tooling
# ---------------------------------------------------------------------------


def generate_test_jwt(user_id: str, expires_in: int = 3600) -> str:
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


def generate_session_jwt(user_id: str, expires_in: int = 3600) -> str:
    """Generate a signed JWT compatible with the existing auth verification flow."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now,
        "exp": now + expires_in,
        "iss": SUPABASE_URL,
    }
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
