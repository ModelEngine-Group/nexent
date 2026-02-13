import logging

from dotenv import load_dotenv
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from http import HTTPStatus

from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from consts.model import UserSignInRequest, UserSignUpRequest
from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException
from services.user_management_service import get_authorized_client, validate_token, \
    check_auth_service_health, signup_user, signup_user_with_invitation, signin_user, refresh_user_token, \
    get_session_by_authorization, get_user_info
from services.user_service import delete_user_and_cleanup
from consts.exceptions import UnauthorizedError
from utils.auth_utils import get_current_user_id


load_dotenv()
logging.getLogger("httpx").setLevel(logging.WARNING)
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/service_health")
async def service_health():
    """Service health check"""
    try:
        await check_auth_service_health()

        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "Auth service is available"})
    except ConnectionError as e:
        logging.error(f"Auth service health check failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="Auth service is unavailable")
    except Exception as e:
        logging.error(f"Auth service health check failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Auth service is unavailable")


@router.post("/signup")
async def signup(request: UserSignUpRequest):
    """User registration"""
    try:
        if request.with_new_invitation:
            user_data = await signup_user_with_invitation(email=request.email,
                                                          password=request.password,
                                                          invite_code=request.invite_code)
        else:
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
        logging.error(f"User registration failed by invite code: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="INVITE_CODE_NOT_CONFIGURED")
    except IncorrectInviteCodeException as e:
        logging.error(f"User registration failed by invite code: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="INVITE_CODE_INVALID")
    except UserRegistrationException as e:
        logging.error(f"User registration failed by registration service: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="REGISTRATION_SERVICE_ERROR")
    except AuthApiError as e:
        logging.error(f"User registration failed by email already exists: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.CONFLICT,
                            detail="EMAIL_ALREADY_EXISTS")
    except AuthWeakPasswordError as e:
        logging.error(f"User registration failed by weak password: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_ACCEPTABLE,
                            detail="WEAK_PASSWORD")
    except Exception as e:
        logging.error(f"User registration failed, unknown error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="UNKNOWN_ERROR")


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
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="Email or password error")
    except Exception as e:
        logging.error(f"User login failed, unknown error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Login failed")


@router.post("/refresh_token")
async def user_refresh_token(request: Request):
    """Refresh token"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="No authorization token provided")
    try:
        session_data = await request.json()
        refresh_token = session_data.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token provided")
        session_info = await refresh_user_token(authorization, refresh_token)
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message":"Token refresh successful", "data":{"session": session_info}})
    except ValueError as e:
        logging.error(f"Refresh token failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            detail="No refresh token provided")
    except Exception as e:
        logging.error(f"Refresh token failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Refresh token failed")


@router.post("/logout")
async def logout(request: Request):
    """User logout"""
    authorization = request.headers.get("Authorization")
    try:
        # Make logout idempotent: if no token or token expired, still return success
        if authorization:
            client = get_authorized_client(authorization)
            try:
                client.auth.sign_out()
            except Exception as signout_err:
                # Ignore sign out errors to keep logout idempotent
                logging.warning(
                    f"Sign out encountered an error but will be ignored: {str(signout_err)}")
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message":"Logout successful"})

    except Exception as e:
        logging.error(f"User logout failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Logout failed!")


@router.get("/session")
async def get_session(request: Request):
    """Get current user session"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        # Treat as not logged in when missing token
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "User not logged in",
                                     "data": None})
    try:
        data = await get_session_by_authorization(authorization)
        return JSONResponse(status_code=HTTPStatus.OK,
                     content={"message": "Session is valid",
                              "data": data})
    except UnauthorizedError as e:
        logging.error(f"Get user session unauthorized: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="User not logged in or session invalid")
    except Exception as e:
        logging.error(f"error in get user session, {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Get user session failed")


@router.get("/current_user_info")
async def get_user_information(request: Request):
    """Get current user information including user ID, group IDs, tenant ID, and role"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        # Treat as not logged in when missing token
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "User not logged in",
                                     "data": None})

    try:
        # Use the unified token validation function to get user ID
        is_valid, user = validate_token(authorization)
        if not is_valid or not user:
            raise UnauthorizedError("User not logged in or session invalid")

        user_id = user.id

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


@router.get("/current_user_id")
async def get_user_id(request: Request):
    """Get current user ID, return None if not logged in"""
    authorization = request.headers.get("Authorization")
    if not authorization:
        # Treat as not logged in when missing token, return 200 with null user_id
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "User not logged in",
                                     "data": {"user_id": None}})
    try:
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
        raise ValueError("User not logged in or session invalid")

    except ValueError as e:
        logging.error(f"Get user ID failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                            detail="User not logged in or session invalid")
    except Exception as e:
        logging.error(f"Get user ID failed: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Get user ID failed")


@router.post("/revoke")
async def revoke_user_account(request: Request):
    """Delete current regular user's account and purge related data.

    Notes:
    - Tenant admin (role=admin) is not allowed to be revoked via this endpoint.
    - Idempotent: local deletions are soft deletes; Supabase deletion may already have occurred.
    """
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED,
                            detail="No authorization token provided")
    try:
        # Identify current user and tenant
        user_id, tenant_id = get_current_user_id(authorization)

        # Determine role via token validation
        is_valid, user = validate_token(authorization.replace("Bearer ", ""))
        if not is_valid or not user:
            raise UnauthorizedError("User not logged in or session invalid")

        # Extract role from user metadata
        user_role = "user"
        if getattr(user, "user_metadata", None) and 'role' in user.user_metadata:
            user_role = user.user_metadata['role']

        # Disallow admin revocation by this endpoint
        if user_role == "admin":
            raise HTTPException(status_code=HTTPStatus.FORBIDDEN,
                                detail="Admin account cannot be deleted via this endpoint")

        # Orchestrate revoke for regular user
        await delete_user_and_cleanup(user_id=user_id, tenant_id=tenant_id)

        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "User account revoked"})
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"User revoke failed: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="User revoke failed")
