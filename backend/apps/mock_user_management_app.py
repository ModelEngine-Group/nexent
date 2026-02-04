import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from http import HTTPStatus

from consts.const import MOCK_USER, MOCK_SESSION
from consts.exceptions import UnauthorizedError
from consts.model import UserSignInRequest, UserSignUpRequest
from services.user_management_service import get_user_info

logger = logging.getLogger("mock_user_management_app")
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/service_health")
async def service_health():
    """
    Mock service health check endpoint
    """
    try:
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Auth service is available"})
    except Exception as e:
        logger.error(f"Service health check failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="Service health check failed")


@router.post("/signup")
async def signup(request: UserSignUpRequest):
    """
    Mock user registration endpoint
    """
    try:
        logger.info(
            f"Mock signup request: email={request.email}, is_admin={request.is_admin}")

        # Mock success response matching user_management_app.py format
        if request.is_admin:
            success_message = "🎉 Admin account registered successfully! You now have system management permissions."
        else:
            success_message = "🎉 User account registered successfully! Please start experiencing the AI assistant service."

        user_data = {
            "user": {
                "id": MOCK_USER["id"],
                "email": request.email,
                "role": "admin" if request.is_admin else "user"
            },
            "session": {
                "access_token": MOCK_SESSION["access_token"],
                "refresh_token": MOCK_SESSION["refresh_token"],
                "expires_at": int((datetime.now() + timedelta(days=3650)).timestamp()),
                "expires_in_seconds": MOCK_SESSION["expires_in_seconds"]
            },
            "registration_type": "admin" if request.is_admin else "user"
        }

        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": success_message, "data": user_data})
    except Exception as e:
        logger.error(f"User signup failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="User registration failed")


@router.post("/signin")
async def signin(request: UserSignInRequest):
    """
    Mock user login endpoint
    """
    try:
        logger.info(f"Mock signin request: email={request.email}")

        # Mock success response matching user_management_app.py format
        signin_content = {
            "message": "Login successful, session validity is 10 years",
            "data": {
                "user": {
                    "id": MOCK_USER["id"],
                    "email": request.email,
                    "role": MOCK_USER["role"]
                },
                "session": {
                    "access_token": MOCK_SESSION["access_token"],
                    "refresh_token": MOCK_SESSION["refresh_token"],
                    "expires_at": int((datetime.now() + timedelta(days=3650)).timestamp()),
                    "expires_in_seconds": MOCK_SESSION["expires_in_seconds"]
                }
            }
        }

        return JSONResponse(status_code=HTTPStatus.OK, content=signin_content)
    except Exception as e:
        logger.error(f"User signin failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="User login failed")


@router.post("/refresh_token")
async def user_refresh_token(request: Request):
    """
    Mock token refresh endpoint
    """
    try:
        logger.info("Mock refresh token request")

        # In speed/mock mode, extend for a very long time (10 years)
        new_expires_at = int((datetime.now() + timedelta(days=3650)).timestamp())

        session_info = {
            "access_token": f"mock_access_token_{new_expires_at}",
            "refresh_token": f"mock_refresh_token_{new_expires_at}",
            "expires_at": new_expires_at,
            "expires_in_seconds": 315360000
        }

        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "Token refresh successful", "data": {"session": session_info}})
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="Token refresh failed")


@router.post("/logout")
async def logout(request: Request):
    """
    Mock user logout endpoint
    """
    try:
        logger.info("Mock logout request")

        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "Logout successful"})
    except Exception as e:
        logger.error(f"User logout failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="User logout failed")


@router.get("/session")
async def get_session(request: Request):
    """
    Mock session validation endpoint
    """
    try:
        # In mock mode, always return valid session
        data = {
            "user": {
                "id": MOCK_USER["id"],
                "email": MOCK_USER["email"],
                "role": MOCK_USER["role"]
            }
        }

        return JSONResponse(status_code=HTTPStatus.OK,
                         content={"message": "Session is valid",
                                  "data": data})
    except Exception as e:
        logger.error(f"Session validation failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="Session validation failed")


@router.get("/current_user_id")
async def get_user_id(request: Request):
    """
    Mock current user ID endpoint
    """
    try:
        # In mock mode, always return the mock user ID
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "Get user ID successfully",
                                     "data": {"user_id": MOCK_USER["id"]}})
    except Exception as e:
        logger.error(f"Get user ID failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                          detail="Failed to get user ID")


@router.get("/current_user_info")
async def get_user_information(request: Request):
    """Get current user information including user ID, group IDs, tenant ID, and role"""
    try:
        # In mock mode, always get user ID by MOCK_USER
        user_id = MOCK_USER["id"]
        # Get user information
        user_info = await get_user_info(user_id)
        if not user_info:
            raise UnauthorizedError("User information not found")

        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "Success",
                                     "data": user_info})
    except UnauthorizedError as e:
        logging.error(f"Get user information unauthorized: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="User not logged in or session invalid")
    except Exception as e:
        logging.error(f"Get user information failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Get user information failed")
