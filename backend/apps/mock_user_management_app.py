import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from consts.const import DEFAULT_USER_ID
from consts.model import STATUS_CODES, ServiceResponse, UserSignUpRequest, UserSignInRequest

logger = logging.getLogger("mock_user_management_app")
router = APIRouter(prefix="/user", tags=["user"])

# Mock user data
MOCK_USER = {
    "id": DEFAULT_USER_ID,
    "email": "mock@example.com",
    "role": "admin"
}

MOCK_SESSION = {
    "access_token": "mock_access_token",
    "refresh_token": "mock_refresh_token",
    "expires_at": int((datetime.now() + timedelta(hours=1)).timestamp()),
    "expires_in_seconds": 3600
}


@router.get("/service_health", response_model=ServiceResponse)
async def service_health():
    """
    Mock service health check endpoint
    """
    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="Mock user service is healthy",
        data=True
    )


@router.post("/signup", response_model=ServiceResponse)
async def signup(request: UserSignUpRequest):
    """
    Mock user registration endpoint
    """
    logger.info(f"Mock signup request: email={request.email}, is_admin={request.is_admin}")

    # Return mock success response
    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="🎉 Mock user account registered successfully!",
        data={
            "user": {
                "id": MOCK_USER["id"],
                "email": request.email,
                "role": "admin" if request.is_admin else "user"
            },
            "session": {
                "access_token": MOCK_SESSION["access_token"],
                "refresh_token": MOCK_SESSION["refresh_token"],
                "expires_at": MOCK_SESSION["expires_at"],
                "expires_in_seconds": MOCK_SESSION["expires_in_seconds"]
            },
            "registration_type": "admin" if request.is_admin else "user"
        }
    )


@router.post("/signin", response_model=ServiceResponse)
async def signin(request: UserSignInRequest):
    """
    Mock user login endpoint
    """
    logger.info(f"Mock signin request: email={request.email}")

    # Return mock success response
    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="Login successful, session validity is 3600 seconds",
        data={
            "user": {
                "id": MOCK_USER["id"],
                "email": request.email,
                "role": "user"
            },
            "session": {
                "access_token": MOCK_SESSION["access_token"],
                "refresh_token": MOCK_SESSION["refresh_token"],
                "expires_at": MOCK_SESSION["expires_at"],
                "expires_in_seconds": MOCK_SESSION["expires_in_seconds"]
            }
        }
    )


@router.post("/refresh_token", response_model=ServiceResponse)
async def refresh_token(request: Request):
    """
    Mock token refresh endpoint
    """
    logger.info("Mock refresh token request")

    # Return mock success response with new tokens
    new_expires_at = int((datetime.now() + timedelta(hours=1)).timestamp())

    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="Token refreshed successfully",
        data={
            "access_token": f"mock_access_token_{new_expires_at}",
            "refresh_token": f"mock_refresh_token_{new_expires_at}",
            "expires_at": new_expires_at,
            "expires_in_seconds": 3600
        }
    )


@router.post("/logout", response_model=ServiceResponse)
async def logout(request: Request):
    """
    Mock user logout endpoint
    """
    logger.info("Mock logout request")

    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="Logout successful",
        data=None
    )


@router.get("/session", response_model=ServiceResponse)
async def get_session(request: Request):
    """
    Mock session validation endpoint
    """
    authorization = request.headers.get("Authorization")

    if not authorization:
        return ServiceResponse(
            code=STATUS_CODES["UNAUTHORIZED"],
            message="No authorization token provided",
            data=None
        )

    # In mock mode, always return valid session
    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="Session is valid",
        data={
            "user": {
                "id": MOCK_USER["id"],
                "email": MOCK_USER["email"],
                "role": MOCK_USER["role"]
            }
        }
    )


@router.get("/current_user_id", response_model=ServiceResponse)
async def get_user_id(request: Request):
    """
    Mock current user ID endpoint
    """
    authorization = request.headers.get("Authorization")

    if not authorization:
        return ServiceResponse(
            code=STATUS_CODES["SUCCESS"],
            message="No authorization token provided",
            data={"user_id": None}
        )

    # In mock mode, always return the mock user ID
    return ServiceResponse(
        code=STATUS_CODES["SUCCESS"],
        message="Get user ID successfully",
        data={"user_id": MOCK_USER["id"]}
    )
