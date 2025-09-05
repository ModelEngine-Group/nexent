import logging

from dotenv import load_dotenv
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from http import HTTPStatus

from gotrue.errors import AuthApiError, AuthWeakPasswordError

from consts.model import UserSignInRequest, UserSignUpRequest
from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException
from services.user_management_service import get_authorized_client, validate_token, \
    check_auth_service_health, signup_user, signin_user, refresh_user_token, \
    get_session_by_authorization
from utils.auth_utils import get_current_user_id


load_dotenv()
logging.getLogger("httpx").setLevel(logging.WARNING)
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/service_health")
async def service_health():
    """Service health check"""
    try:
        is_available = await check_auth_service_health()

        if is_available:
            return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Auth service is available"})
        else:
            return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content={"message": "Auth service is unavailable"})
    except Exception as e:
        logging.error(f"Auth service health check failed: {str(e)}")
        return HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Auth service is unavailable")


@router.post("/signup")
async def signup(request: UserSignUpRequest):
    """User registration"""
    try:
        user_data = await signup_user(email=request.email,
                          password=request.password,
                          is_admin=request.is_admin,
                          invite_code=request.invite_code)
        if request.is_admin:
            success_message = "🎉 Admin account registered successfully! You now have system management permissions."
        else:
            success_message = "🎉 User account registered successfully! Please start experiencing the AI assistant service."
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message":success_message, "data":user_data})
    except NoInviteCodeException as e:
        message = "Admin registration feature is not available, please contact the system administrator to configure the invite code"
        data = {
            "error_type": "INVITE_CODE_NOT_CONFIGURED",
            "details": "The system has not configured the admin invite code, please contact technical support"
        }
        logging.error(f"User registration failed by invite code: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": message, "data": data})
    except IncorrectInviteCodeException as e:
        message = "Admin invite code error, please check and re-enter"
        data = {
            "error_type": "INVITE_CODE_INVALID",
            "field": "inviteCode",
            "hint": "Please confirm that the invite code is entered correctly, case-sensitive"
        }
        logging.error(f"User registration failed by invite code: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": message, "data": data})
    except UserRegistrationException as e:
        message = "Registration service is temporarily unavailable, please try again later"
        data = {
            "error_type": "REGISTRATION_SERVICE_ERROR",
            "details": "Authentication service response exception"
        }
        logging.error(f"User registration failed by registration service: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": message, "data": data})
    except AuthApiError as e:
        message = f"Email {request.email} has already been registered"
        data = {
            "error_type": "EMAIL_ALREADY_EXISTS",
            "field": "email",
            "suggestion": "Please use a different email address or try logging in to an existing account"
        }
        logging.error(f"User registration failed by email already exists: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.CONFLICT,
                            content={"message": message, "data": data})
    except AuthWeakPasswordError as e:
        message = "Password strength is not enough, please set a stronger password"
        data = {
            "error_type": "WEAK_PASSWORD",
            "field": "password",
            "requirements": "Password must be at least 6 characters long, including letters, numbers, and special symbols"
        }
        logging.error(f"User registration failed by weak password: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            content={"message": message, "data": data})
    except Exception as e:
        message = "Registration failed, please try again later"
        data = {
            "error_type": "UNKNOWN_ERROR",
            "details": f"System error: {str(e)[:100]}",
            "suggestion": "If the problem persists, please contact technical support"
        }
        logging.error(f"User registration failed, unknown error: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": message, "data": data})


@router.post("/signin")
async def signin(request: UserSignInRequest):
    """User login"""
    try:
        signin_content = await signin_user(email=request.email,
                                      password=request.password)
        return JSONResponse(status_code=HTTPStatus.OK,
                            content=signin_content)
    except AuthApiError as e:
        logging.error(f"User login failed: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            content={"message": "Email or password error"})
    except Exception as e:
        logging.error(f"User login failed, unknown error: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": "Login failed"})


@router.post("/refresh_token")
async def user_refresh_token(request: Request):
    """Refresh token"""
    try:
        authorization = request.headers.get("Authorization")
        if not authorization:
            return JSONResponse(status_code=HTTPStatus.UNAUTHORIZED,
                                content={"message": "No authorization token provided"})
        session_data = await request.json()
        refresh_token = session_data.get("refresh_token")
        if not refresh_token:
            return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                                content={"message": "No refresh token provided"})
        session_info = await refresh_user_token(authorization, refresh_token)
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message":"Token refresh successful", "data":{"session": session_info}})
    except Exception as e:
        logging.error(f"Refresh token failed: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": "Refresh token failed"})


@router.post("/logout")
async def logout(request: Request):
    """User logout"""
    try:
        authorization = request.headers.get("Authorization")
        if not authorization:
            return JSONResponse(status_code=HTTPStatus.UNAUTHORIZED,
                                content={"message": "User not logged in"})

        client = get_authorized_client(authorization)
        client.auth.sign_out()
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message":"Logout successful"})

    except Exception as e:
        logging.error(f"User logout failed: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": "Logout failed!"})


@router.get("/session")
async def get_session(request: Request):
    """Get current user session"""
    try:
        authorization = request.headers.get("Authorization")
        if not authorization:
            return JSONResponse(status_code=HTTPStatus.UNAUTHORIZED,
                                content={"message": "No authorization token provided"})

        data = await get_session_by_authorization(authorization)
        return JSONResponse(status_code=HTTPStatus.OK,
                     content={"message": "Session is valid",
                              "data": data})
    except ValueError as e:
        logging.error(f"Get user session failed: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            content={"message": "Session is invalid"})
    except Exception as e:
        logging.error(f"error in get user session, {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": "Get user session failed"})


@router.get("/current_user_id")
async def get_user_id(request: Request):
    """Get current user ID, return None if not logged in"""
    try:
        authorization = request.headers.get("Authorization")
        if not authorization:
            return JSONResponse(status_code=HTTPStatus.UNAUTHORIZED,
                                content={"message": "No authorization token provided"})

        # Use the unified token validation function
        is_valid, user = validate_token(authorization)
        if is_valid and user:
            return JSONResponse(status_code=HTTPStatus.OK,
                                content={"message": "Get user ID successfully",
                                         "data":{"user_id": user.id}})

        # If the token is invalid, try to parse the user ID from the token
        user_id, _ = get_current_user_id(authorization)
        if user_id:
            return JSONResponse(status_code=HTTPStatus.OK,
                                content={"message": "Successfully parsed user ID from token",
                                         "data": {"user_id": user_id}})

        # If all methods fail, return the session invalid information
        return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            content={"message": "User not logged in or session invalid"})
    except Exception as e:
        logging.error(f"Get user ID failed: {str(e)}")
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": "Get user ID failed"})
