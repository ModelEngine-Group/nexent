import logging
import os
from typing import Any, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Header, HTTPException, Request
from supabase import Client

from consts.model import ServiceResponse, STATUS_CODES, UserSignInRequest, UserSignUpRequest
from database.model_management_db import create_model_record
from database.user_tenant_db import insert_user_tenant
from utils.auth_utils import calculate_expires_at, get_current_user_id, get_jwt_expiry_seconds, get_supabase_client
from consts.const import INVITE_CODE

load_dotenv()
logging.getLogger("httpx").setLevel(logging.WARNING)
router = APIRouter(prefix="/user", tags=["user"])


# Set token to client
def set_auth_token_to_client(client: Client, token: str) -> None:
    """Set token to client"""
    jwt_token = token.replace(
        "Bearer ", "") if token.startswith("Bearer ") else token

    try:
        # Only set access_token
        client.auth.access_token = jwt_token
    except Exception as e:
        logging.error(f"设置访问令牌失败: {str(e)}")


def get_authorized_client(authorization: Optional[str] = Header(None)) -> Client:
    """Get token from authorization header and create authorized supabase client"""
    client = get_supabase_client()
    if authorization:
        token = authorization.replace("Bearer ", "") if authorization.startswith(
            "Bearer ") else authorization
        set_auth_token_to_client(client, token)
    return client


def get_current_user_from_client(client: Client) -> Optional[Any]:
    """Get current user from client, return user object or None"""
    try:
        user_response = client.auth.get_user()
        if user_response and user_response.user:
            return user_response.user
        return None
    except Exception as e:
        logging.error(f"获取当前用户失败: {str(e)}")
        return None


def validate_token(token: str) -> Tuple[bool, Optional[Any]]:
    """Validate token function, return (is valid, user object)"""
    client = get_supabase_client()
    set_auth_token_to_client(client, token)
    try:
        user = get_current_user_from_client(client)
        if user:
            return True, user
        return False, None
    except Exception as e:
        logging.error(f"令牌验证失败: {str(e)}")
        return False, None


async def get_current_user(request: Request) -> Any:
    """Get current user as dependency"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供授权令牌")

    is_valid, user = validate_token(authorization)
    if not is_valid or not user:
        raise HTTPException(status_code=401, detail="无效的用户会话")

    return user


def extend_session(client: Client, refresh_token: str) -> Optional[dict]:
    """Try to extend session validity, return new session information or None"""
    try:
        response = client.auth.refresh_session(refresh_token)
        if response and response.session:
            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "expires_at": calculate_expires_at(response.session.access_token),
                "expires_in_seconds": get_jwt_expiry_seconds(response.session.access_token)
            }
        return None
    except Exception as e:
        logging.error(f"延长会话失败: {str(e)}")
        return None


@router.get("/service_health", response_model=ServiceResponse)
async def service_health():
    """Service health check"""
    try:
        supabase_url = os.getenv("SUPABASE_URL")
        response = requests.get(f'{supabase_url}/auth/v1/health', headers={
            'apikey': os.getenv("SUPABASE_KEY")
        })

        if not response.ok:
            return ServiceResponse(
                code=STATUS_CODES["AUTH_SERVICE_UNAVAILABLE"],
                message="认证服务不可用",
                data=False
            )

        data = response.json()
        # Check if the service is available by checking if the response contains the name field and its value is "GoTrue"
        is_available = data and data.get("name") == "GoTrue"

        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"] if is_available else STATUS_CODES["AUTH_SERVICE_UNAVAILABLE"],
            message="认证服务正常" if is_available else "认证服务不可用",
            data=is_available
        )

    except Exception as e:
        logging.error(f"认证服务连通性检查失败: {str(e)}")
        return ServiceResponse(
            code=STATUS_CODES["SERVER_ERROR"],
            message=f"认证服务连通性检查失败: {str(e)}",
            data=False
        )


@router.post("/signup", response_model=ServiceResponse)
async def signup(request: UserSignUpRequest):
    """User registration"""
    client = get_supabase_client()

    # Record basic information of the registration request
    logging.info(f"收到注册请求: email={request.email}, is_admin={request.is_admin}")

    # If it is an admin registration, verify the invite code
    if request.is_admin:
        logging.info("检测到管理员注册请求，开始验证邀请码")

        # Get the invite code from consts.const (which reads from environment variable)
        logging.info(f"The INVITE_CODE obtained from consts.const: {INVITE_CODE}")

        if not INVITE_CODE:
            logging.error(
                "Admin invite code not found in configuration")
            logging.error("Please check the INVITE_CODE environment variable")
            return ServiceResponse(
                code=STATUS_CODES["SERVER_ERROR"],
                message="Admin registration feature is not available, please contact the system administrator to configure the invite code",
                data={
                    "error_type": "INVITE_CODE_NOT_CONFIGURED",
                    "details": "The system has not configured the admin invite code, please contact technical support"
                }
            )

        logging.info(f"User provided invite code: {request.invite_code}")

        if not request.invite_code:
            logging.warning("User did not provide admin invite code")
            return ServiceResponse(
                code=STATUS_CODES["INVALID_INPUT"],
                message="Please enter the admin invite code",
                data={
                    "error_type": "INVITE_CODE_REQUIRED",
                    "field": "inviteCode"
                }
            )

        if request.invite_code != INVITE_CODE:
            logging.warning(
                f"Admin invite code verification failed: user provided='{request.invite_code}', system configured='{INVITE_CODE}'")
            return ServiceResponse(
                code=STATUS_CODES["INVALID_INPUT"],
                message="Admin invite code error, please check and re-enter",
                data={
                    "error_type": "INVITE_CODE_INVALID",
                    "field": "inviteCode",
                    "hint": "Please confirm that the invite code is entered correctly, case-sensitive"
                }
            )

        logging.info("Admin invite code verification successful")

    try:
        # Set user metadata, including role information
        response = client.auth.sign_up({
            "email": request.email,
            "password": request.password,
            "options": {
                "data": {
                    "role": "admin" if request.is_admin else "user"
                }
            }
        })

        if response.user:
            user_id = response.user.id
            user_role = "admin" if request.is_admin else "user"

            # Determine tenant ID
            if request.is_admin:
                # The tenant_id of the admin is the same as the user_id
                tenant_id = user_id
            else:
                # Normal users use the default tenant ID
                tenant_id = "tenant_id"

            # Create user tenant relationship
            user_tenant_created = insert_user_tenant(
                user_id=user_id,
                tenant_id=tenant_id,
                created_by=user_id
            )

            if not user_tenant_created:
                # Registration successful but tenant relationship creation failed, continue to return success, but record the error
                logging.error(
                    f"Failed to create user tenant relationship: user_id={user_id}, tenant_id={tenant_id}")

            logging.info(
                f"User {request.email} registered successfully, role: {user_role}, tenant: {tenant_id}")

            success_message = f"🎉 {'Admin account' if request.is_admin else 'User account'} registered successfully!"
            if request.is_admin:
                tts_model_data = {
                    "model_name": "volcano_tts",
                    "model_factory": "OpenAI-API-Compatible",
                    "model_type": "tts",
                    "display_name": "volcano_tts",
                    "connect_status": "unavailable",
                    "delete_flag": "N"
                }
                stt_model_data = {
                    "model_name": "volcano_stt",
                    "model_factory": "OpenAI-API-Compatible",
                    "model_type": "stt",
                    "display_name": "volcano_stt",
                    "connect_status": "unavailable",
                    "delete_flag": "N"
                }
                create_model_record(tts_model_data, user_id, tenant_id)
                create_model_record(stt_model_data, user_id, tenant_id)
                success_message += " You now have system management permissions."
            else:
                success_message += " Please start experiencing the AI assistant service."

            return ServiceResponse(
                code=STATUS_CODES["SUCCESS"],
                message=success_message,
                data={
                    "user": {
                        "id": response.user.id,
                        "email": response.user.email,
                        "role": user_role
                    },
                    "session": {
                        "access_token": response.session.access_token if response.session else None,
                        "refresh_token": response.session.refresh_token if response.session else None,
                        "expires_at": calculate_expires_at() if response.session else None,
                        "expires_in_seconds": get_jwt_expiry_seconds(response.session.access_token) if response.session else 3600
                    } if response.session else None,
                    "registration_type": "admin" if request.is_admin else "user"
                }
            )
        else:
            logging.error(
                "Supabase registration request returned no user object")
            return ServiceResponse(
                code=STATUS_CODES["SERVER_ERROR"],
                message="Registration service is temporarily unavailable, please try again later",
                data={
                    "error_type": "REGISTRATION_SERVICE_ERROR",
                    "details": "Authentication service response exception"
                }
            )

    except Exception as e:
        logging.error(f"User registration failed: {str(e)}")
        error_message = str(e).lower()

        # Email already registered
        if "user already registered" in error_message or "email already in use" in error_message:
            return ServiceResponse(
                code=STATUS_CODES["USER_EXISTS"],
                message=f"Email {request.email} has already been registered",
                data={
                    "error_type": "EMAIL_ALREADY_EXISTS",
                    "field": "email",
                    "suggestion": "Please use a different email address or try logging in to an existing account"
                }
            )

        # Password strength is not enough
        if "password" in error_message and ("weak" in error_message or "strength" in error_message):
            return ServiceResponse(
                code=STATUS_CODES["INVALID_INPUT"],
                message="Password strength is not enough, please set a stronger password",
                data={
                    "error_type": "WEAK_PASSWORD",
                    "field": "password",
                    "requirements": "Password must be at least 6 characters long, including letters, numbers, and special symbols"
                }
            )

        # Email format error
        if "email" in error_message and ("invalid" in error_message or "format" in error_message):
            return ServiceResponse(
                code=STATUS_CODES["INVALID_INPUT"],
                message="Email format is incorrect, please check and re-enter",
                data={
                    "error_type": "INVALID_EMAIL_FORMAT",
                    "field": "email",
                    "example": "Please enter the correct format: user@example.com"
                }
            )

        # Network connection problem
        if "timeout" in error_message or "connection" in error_message:
            return ServiceResponse(
                code=STATUS_CODES["SERVER_ERROR"],
                message="Network connection timeout, please check your network connection and try again",
                data={
                    "error_type": "NETWORK_ERROR",
                    "suggestion": "Please check your network connection status"
                }
            )

        # Other unknown errors
        return ServiceResponse(
            code=STATUS_CODES["SERVER_ERROR"],
            message="Registration failed, please try again later",
            data={
                "error_type": "UNKNOWN_ERROR",
                "details": f"System error: {str(e)[:100]}",
                "suggestion": "If the problem persists, please contact technical support"
            }
        )


@router.post("/signin", response_model=ServiceResponse)
async def signin(request: UserSignInRequest):
    """User login"""
    client = get_supabase_client()
    try:
        response = client.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })

        # Get actual expiration time from access_token
        expiry_seconds = get_jwt_expiry_seconds(response.session.access_token)
        expires_at = calculate_expires_at(response.session.access_token)

        # Get role information from user metadata
        user_role = "user"  # Default role
        if 'role' in response.user.user_metadata:  # Adapt to historical user data
            user_role = response.user.user_metadata['role']

        logging.info(
            f"User {request.email} logged in successfully, session validity is {expiry_seconds} seconds, role: {user_role}")

        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message=f"Login successful, session validity is {expiry_seconds} seconds",
            data={
                "user": {
                    "id": response.user.id,
                    "email": response.user.email,
                    "role": user_role
                },
                "session": {
                    "access_token": response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                    "expires_at": expires_at,
                    "expires_in_seconds": expiry_seconds
                }
            }
        )
    except Exception as e:
        logging.error(f"User login failed: {str(e)}")
        error_message = str(e).lower()

        if "invalid login credentials" in error_message:
            return ServiceResponse(
                code=STATUS_CODES["INVALID_CREDENTIALS"],
                message="Email or password error",
                data=None
            )

        return ServiceResponse(
            code=STATUS_CODES["SERVER_ERROR"],
            message=f"Login failed: {str(e)}",
            data=None
        )


@router.post("/refresh_token", response_model=ServiceResponse)
async def refresh_token(request: Request):
    """Refresh token"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        return ServiceResponse(
            code=STATUS_CODES["UNAUTHORIZED"],
            message="No authorization token provided",
            data=None
        )

    client = get_authorized_client(authorization)
    try:
        session_data = await request.json()
        refresh_token = session_data.get("refresh_token")

        if not refresh_token:
            return ServiceResponse(
                code=STATUS_CODES["INVALID_INPUT"],
                message="No refresh token provided",
                data=None
            )

        session_info = extend_session(client, refresh_token)
        if not session_info:
            return ServiceResponse(
                code=STATUS_CODES["TOKEN_EXPIRED"],
                message="Refresh token failed, the token may have expired",
                data=None
            )

        logging.info(
            f"Token refresh successful: session validity is {session_info['expires_in_seconds']} seconds")

        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="Token refresh successful",
            data={"session": session_info}
        )
    except Exception as e:
        logging.error(f"Refresh token failed: {str(e)}")
        error_message = str(e).lower()

        if "token is expired" in error_message or "invalid token" in error_message:
            return ServiceResponse(
                code=STATUS_CODES["TOKEN_EXPIRED"],
                message="Refresh token has expired, please log in again",
                data=None
            )

        return ServiceResponse(
            code=STATUS_CODES["SERVER_ERROR"],
            message=f"Refresh token failed: {str(e)}",
            data=None
        )


@router.post("/logout", response_model=ServiceResponse)
async def logout(request: Request):
    """User logout"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="User not logged in",
            data=None
        )

    client = get_authorized_client(authorization)
    try:
        client.auth.sign_out()
        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="Logout successful",
            data=None
        )
    except Exception as e:
        logging.error(f"User logout failed: {str(e)}")
        return ServiceResponse(
            code=STATUS_CODES["SERVER_ERROR"],
            message=f"Logout failed: {str(e)}",
            data=None
        )


@router.get("/session", response_model=ServiceResponse)
async def get_session(request: Request):
    """Get current user session"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        return ServiceResponse(
            code=STATUS_CODES["UNAUTHORIZED"],
            message="No authorization token provided",
            data=None
        )

    # Use the unified token validation function
    is_valid, user = validate_token(authorization)

    if is_valid and user:
        # Get role information from user metadata
        user_role = "user"  # Default role
        if user.user_metadata and 'role' in user.user_metadata:
            user_role = user.user_metadata['role']

        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="Session is valid",
            data={
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "role": user_role
                }
            }
        )
    else:
        return ServiceResponse(
            code=STATUS_CODES["TOKEN_EXPIRED"],
            message="Session is invalid",
            data=None
        )


@router.get("/current_user_id", response_model=ServiceResponse)
async def get_user_id(request: Request):
    """Get current user ID, return None if not logged in"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="No authorization token provided",
            data={"user_id": None}
        )

    # Use the unified token validation function
    is_valid, user = validate_token(authorization)

    if is_valid and user:
        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="Get user ID successfully",
            data={"user_id": user.id}
        )

    # If the token is invalid, try to parse the user ID from the token
    try:
        user_id, _ = get_current_user_id(authorization)
        if user_id:
            logging.info(f"Successfully parsed user ID from token: {user_id}")
            return ServiceResponse(
                code=STATUS_CODES["SUCCESS"],
                message="Successfully parsed user ID from token",
                data={"user_id": user_id}
            )
    except Exception as token_error:
        logging.warning(
            f"Failed to parse user ID from token: {str(token_error)}")

    # If all methods fail, return the session invalid information
    return ServiceResponse(
        # Keep the same status code as the original script
        code=STATUS_CODES["SUCCESS"],
        message="User not logged in or session invalid",
        data={"user_id": None}
    )
