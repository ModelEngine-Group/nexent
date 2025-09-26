import logging
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import jwt
from fastapi import Request
from supabase import create_client

from consts.const import DEFAULT_TENANT_ID, DEFAULT_USER_ID, IS_SPEED_MODE, SUPABASE_URL, SUPABASE_KEY, SERVICE_ROLE_KEY, DEBUG_JWT_EXPIRE_SECONDS, LANGUAGE
from consts.exceptions import LimitExceededError, SignatureValidationError, UnauthorizedError
from database.user_tenant_db import get_user_tenant_by_user_id

# Module logger
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AK/SK authentication helpers (merged from aksk_auth_utils.py)
# ---------------------------------------------------------------------------

# Mock AK/SK configuration (replace with DB/config lookup in production)
MOCK_ACCESS_KEY = "mock_access_key_12345"
MOCK_SECRET_KEY = "mock_secret_key_67890abcdef"
MOCK_JWT_SECRET_KEY = "mock_jwt_secret_key_67890abcdef"

# Timestamp validity window in seconds (prevent replay attacks)
TIMESTAMP_VALIDITY_WINDOW = 300


def get_aksk_config(tenant_id: str) -> Tuple[str, str]:
    """
    Get AK/SK configuration according to tenant_id

    Returns:
        Tuple[str, str]: (access_key, secret_key)
    """

    # TODO: get ak/sk according to tenant_id from DB
    return MOCK_ACCESS_KEY, MOCK_SECRET_KEY


def validate_timestamp(timestamp: str) -> bool:
    """
    Validate timestamp is within validity window

    Args:
        timestamp: timestamp string

    Returns:
        bool: whether timestamp is valid
    """
    try:
        timestamp_int = int(timestamp)
        current_time = int(time.time())

        if abs(current_time - timestamp_int) > TIMESTAMP_VALIDITY_WINDOW:
            logger.warning(
                f"Timestamp validation failed: current={current_time}, provided={timestamp_int}"
            )
            return False

        return True
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid timestamp format: {timestamp}, error: {e}")
        return False


def calculate_hmac_signature(secret_key: str, access_key: str, timestamp: str, request_body: str = "") -> str:
    """
    Calculate HMAC-SHA256 signature

    Args:
        secret_key: secret key
        access_key: access key
        timestamp: timestamp
        request_body: request body (optional)

    Returns:
        str: HMAC-SHA256 signature (hex string)
    """
    string_to_sign = f"{access_key}{timestamp}{request_body}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def verify_aksk_signature(
    access_key: str, timestamp: str, signature: str, request_body: str = ""
) -> bool:
    """
    Validate AK/SK signature

    Args:
        access_key: access key
        timestamp: timestamp
        signature: provided signature
        request_body: request body (optional)

    Returns:
        bool: whether signature is valid
    """
    try:
        if not validate_timestamp(timestamp):
            raise SignatureValidationError("Timestamp is invalid or expired")

        # TODO: get ak/sk according to tenant_id from DB
        mock_access_key, mock_secret_key = get_aksk_config(
            tenant_id="tenant_id")

        if access_key != mock_access_key:
            logger.warning(f"Invalid access key: {access_key}")
            return False

        expected_signature = calculate_hmac_signature(
            mock_secret_key, access_key, timestamp, request_body
        )

        if not hmac.compare_digest(signature, expected_signature):
            logger.warning(
                f"Signature mismatch: expected={expected_signature}, provided={signature}"
            )
            return False

        return True
    except Exception as e:
        logger.error(f"Error during signature verification: {e}")
        return False


def extract_aksk_headers(headers: dict) -> Tuple[str, str, str]:
    """
    Extract AK/SK related information from request headers

    Args:
        headers: request headers dictionary

    Returns:
        Tuple[str, str, str]: (access_key, timestamp, signature)

    Raises:
        UnauthorizedError: when required headers are missing
    """

    def get_header(headers: dict, name: str) -> Optional[str]:
        for k, v in headers.items():
            if k.lower() == name.lower():
                return v
        return None

    access_key = get_header(headers, "X-Access-Key")
    timestamp = get_header(headers, "X-Timestamp")
    signature = get_header(headers, "X-Signature")

    if not access_key:
        raise UnauthorizedError("Missing X-Access-Key header")
    if not timestamp:
        raise UnauthorizedError("Missing X-Timestamp header")
    if not signature:
        raise UnauthorizedError("Missing X-Signature header")

    return access_key, timestamp, signature


def validate_aksk_authentication(headers: dict, request_body: str = "") -> bool:
    """
    Validate AK/SK authentication

    Args:
        headers: request headers dictionary
        request_body: request body (optional)

    Returns:
        bool: whether authentication is successful

    Raises:
        UnauthorizedError: when authentication fails
        SignatureValidationError: when signature verification fails
    """
    try:
        access_key, timestamp, signature = extract_aksk_headers(headers)

        if not verify_aksk_signature(access_key, timestamp, signature, request_body):
            raise SignatureValidationError("Invalid signature")

        return True
    except (UnauthorizedError, SignatureValidationError, LimitExceededError) as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during AK/SK authentication: {e}")
        raise UnauthorizedError("Authentication failed")


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
        jwt_token = token.replace(
            "Bearer ", "") if token.startswith("Bearer ") else token

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
    Extract user ID from JWT token

    Args:
        authorization: Authorization header value

    Returns:
        Optional[str]: User ID, return None if parsing fails
    """
    try:
        # Format authorization header
        token = authorization.replace("Bearer ", "") if authorization.startswith(
            "Bearer ") else authorization

        # Decode JWT token (without signature verification, only parse content)
        decoded = jwt.decode(token, options={"verify_signature": False})

        # Extract user ID from JWT claims
        user_id = decoded.get("sub")

        return user_id
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
    # if deploy in speed mode or authorization is None, return default user id and tenant id
    if IS_SPEED_MODE or authorization is None:
        logging.debug(
            "Speed mode or no valid authorization header detected - returning default user ID and tenant ID")
        return DEFAULT_USER_ID, DEFAULT_TENANT_ID

    try:
        user_id = _extract_user_id_from_jwt_token(authorization)
        if not user_id:
            raise UnauthorizedError("Invalid or expired authentication token")

        user_tenant_record = get_user_tenant_by_user_id(user_id)
        if user_tenant_record and user_tenant_record.get('tenant_id'):
            tenant_id = user_tenant_record['tenant_id']
            logging.debug(f"Found tenant ID for user {user_id}: {tenant_id}")
        else:
            tenant_id = DEFAULT_TENANT_ID
            logging.warning(
                f"No tenant relationship found for user {user_id}, using default tenant")

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
            if hasattr(request, 'cookies') and request.cookies:
                cookie_locale = request.cookies.get('NEXT_LOCALE')
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


def get_current_user_info(authorization: Optional[str] = None, request: Request = None) -> tuple[str, str, str]:
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
