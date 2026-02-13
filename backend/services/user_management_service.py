import logging
from typing import Optional, Any, Tuple, Dict, List

import aiohttp
from fastapi import Header
from supabase import Client
from pydantic import EmailStr

from utils.auth_utils import (
    get_supabase_client,
    calculate_expires_at,
    get_jwt_expiry_seconds,
)
from consts.const import INVITE_CODE, SUPABASE_URL, SUPABASE_KEY, DEFAULT_TENANT_ID
from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException, UnauthorizedError

from database.model_management_db import create_model_record
from database.user_tenant_db import insert_user_tenant, get_user_tenant_by_user_id
from database.group_db import query_group_ids_by_user
from database.client import as_dict, get_db_session
from database.db_models import RolePermission
from services.invitation_service import use_invitation_code, check_invitation_available, get_invitation_by_code
from services.group_service import add_user_to_groups
from services.tool_configuration_service import init_tool_list_for_tenant



logging.getLogger("user_management_service").setLevel(logging.DEBUG)


def set_auth_token_to_client(client: Client, token: str) -> None:
    """Set token to client"""
    jwt_token = token.replace(
        "Bearer ", "") if token.startswith("Bearer ") else token

    try:
        # Only set access_token
        client.auth.access_token = jwt_token
    except Exception as e:
        logging.error(f"Set access token failed: {str(e)}")


def get_authorized_client(authorization: Optional[str] = Header(None)) -> Client:
    """Get token from authorization header and create authorized supabase client"""
    client = get_supabase_client()
    if authorization:
        token = authorization.replace("Bearer ", "") if authorization.startswith(
            "Bearer ") else authorization
        set_auth_token_to_client(client, token)
    return client


def get_current_user_from_client(client: Client, token: Optional[str] = None) -> Optional[Any]:
    """Get current user from client using provided JWT, return user object or None"""
    try:
        # Prefer explicitly passing the JWT to avoid relying on client-side session state
        if token:
            jwt_token = token.replace(
                "Bearer ", "") if token.startswith("Bearer ") else token
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
            return True, user
        return False, None
    except Exception as e:
        logging.error(f"Token validation failed: {str(e)}")
        return False, None


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
        logging.error(f"Extend session failed: {str(e)}")
        return None


async def check_auth_service_health():
    """
    Check the health status of the authentication service
    Return (is available, status message)
    """
    health_url = f'{SUPABASE_URL}/auth/v1/health'
    headers = {'apikey': SUPABASE_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(health_url, headers=headers) as response:
            if not response.ok:
                raise ConnectionError("Auth service is unavailable")

            data = await response.json()
            # Check if the service is available by verifying the name field equals "GoTrue"
            if not data or data.get("name", "") != "GoTrue":
                logging.error("Auth service is unavailable")
                raise ConnectionError("Auth service is unavailable")


async def signup_user(email: EmailStr,
                      password: str,
                      is_admin: Optional[bool] = False,
                      invite_code: Optional[str] = None):
    """User registration"""
    client = get_supabase_client()
    logging.info(
        f"Receive registration request: email={email}, is_admin={is_admin}")
    if is_admin:
        await verify_invite_code(invite_code)

    # Set user metadata, including role information
    response = client.auth.sign_up({
        "email": email,
        "password": password,
        "options": {
            "data": {"role": "admin" if is_admin else "user"}
        }
    })

    if response.user:
        user_id = response.user.id
        user_role = "admin" if is_admin else "user"
        tenant_id = user_id if is_admin else "tenant_id"

        # Create user tenant relationship
        insert_user_tenant(user_id=user_id, tenant_id=tenant_id, user_email=email)

        logging.info(
            f"User {email} registered successfully, role: {user_role}, tenant: {tenant_id}")

        if is_admin:
            await generate_tts_stt_4_admin(tenant_id, user_id)

        # Initialize tool list for the new tenant (only once per tenant)
        await init_tool_list_for_tenant(tenant_id, user_id)

        return await parse_supabase_response(is_admin, response, user_role)
    else:
        logging.error(
            "Supabase registration request returned no user object")
        raise UserRegistrationException(
            "Registration service is temporarily unavailable, please try again later")


async def signup_user_with_invitation(email: EmailStr,
                                      password: str,
                                      invite_code: Optional[str] = None):
    """User registration with invitation code support"""
    client = get_supabase_client()
    logging.info(
        f"Receive registration request: email={email}, invite_code={'provided' if invite_code else 'not provided'}")

    # Default user role is USER
    user_role = "USER"
    invitation_info = None

    # Validate invitation code if provided (without using it yet)
    if invite_code:
        try:
            # Convert invite code to upper case for consistency
            invite_code = invite_code.upper()

            # Check if invitation is available
            if not check_invitation_available(invite_code):
                raise IncorrectInviteCodeException(
                    f"Invitation code {invite_code} is not available")

            # Get invitation code details
            invitation_info = get_invitation_by_code(invite_code)
            if not invitation_info:
                raise IncorrectInviteCodeException(
                    f"Invitation code {invite_code} not found")

            # Determine user role based on invitation code type
            code_type = invitation_info["code_type"]
            if code_type == "ADMIN_INVITE":
                user_role = "ADMIN"
            elif code_type == "DEV_INVITE":
                user_role = "DEV"

            logging.info(
                f"Invitation code {invite_code} validated successfully, will assign role: {user_role}")

        except IncorrectInviteCodeException:
            raise
        except Exception as e:
            logging.error(
                f"Invitation code {invite_code} validation failed: {str(e)}")
            raise IncorrectInviteCodeException(
                f"Invalid invitation code: {str(e)}")

    # Set user metadata, including role information
    response = client.auth.sign_up({
        "email": email,
        "password": password
    })

    if response.user:
        user_id = response.user.id

        # Determine tenant_id based on invitation code
        if invitation_info:
            tenant_id = invitation_info["tenant_id"]
        else:
            tenant_id = DEFAULT_TENANT_ID

        # Create user tenant relationship
        logging.debug(f"Creating user tenant relationship: user_id={user_id}, tenant_id={tenant_id}, user_role={user_role}")
        insert_user_tenant(
            user_id=user_id, tenant_id=tenant_id, user_role=user_role, user_email=email)
        logging.debug(f"User tenant relationship created successfully for user {user_id}")

        # Use invitation code now that we have the real user_id
        if invitation_info:
            try:
                invitation_result = use_invitation_code(invite_code, user_id)
                logging.debug(
                    f"Invitation code {invite_code} used successfully for user {user_id}")

                # Add user to groups specified in invitation code
                group_ids = invitation_result.get("group_ids", [])
                if group_ids:
                    try:
                        # Convert group_ids from string to list if needed
                        if isinstance(group_ids, str):
                            from utils.str_utils import convert_string_to_list
                            group_ids = convert_string_to_list(group_ids)

                        if group_ids:
                            group_results = add_user_to_groups(user_id, group_ids, user_id)
                            successful_adds = [
                                r for r in group_results if not r.get("error")]
                            logging.info(
                                f"User {user_id} added to {len(successful_adds)} groups from invitation code")

                    except Exception as e:
                        logging.error(
                            f"Failed to add user {user_id} to invitation groups: {str(e)}")

            except Exception as e:
                # If using invitation code fails after registration, log error but don't fail registration
                logging.error(
                    f"Failed to use invitation code {invite_code} for user {user_id}: {str(e)}")

        logging.info(
            f"User {email} registered successfully, role: {user_role}, tenant: {tenant_id}")

        if user_role == "ADMIN":
            await generate_tts_stt_4_admin(tenant_id, user_id)

        # Initialize tool list for the new tenant (only once per tenant)
        await init_tool_list_for_tenant(tenant_id, user_id)

        return await parse_supabase_response(False, response, user_role)
    else:
        logging.error(
            "Supabase registration request returned no user object")
        raise UserRegistrationException(
            "Registration service is temporarily unavailable, please try again later")


async def parse_supabase_response(is_admin, response, user_role):
    """Parse Supabase response and build standardized user registration response"""
    user_data = {
        "id": response.user.id,
        "email": response.user.email,
        "role": user_role
    }

    session_data = None
    if response.session:
        session_data = {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_at": calculate_expires_at(response.session.access_token),
            "expires_in_seconds": get_jwt_expiry_seconds(response.session.access_token)
        }

    return {
        "user": user_data,
        "session": session_data,
        "registration_type": "admin" if is_admin else "user"
    }


async def generate_tts_stt_4_admin(tenant_id, user_id):
    tts_model_data = {
        "model_repo": "",
        "model_name": "volcano_tts",
        "model_factory": "OpenAI-API-Compatible",
        "model_type": "tts",
        "api_key": "",
        "base_url": "",
        "max_tokens": 0,
        "used_token": 0,
        "display_name": "volcano_tts",
        "connect_status": "unavailable",
        "delete_flag": "N"
    }
    stt_model_data = {
        "model_repo": "",
        "model_name": "volcano_stt",
        "model_factory": "OpenAI-API-Compatible",
        "model_type": "stt",
        "api_key": "",
        "base_url": "",
        "max_tokens": 0,
        "used_token": 0,
        "display_name": "volcano_stt",
        "connect_status": "unavailable",
        "delete_flag": "N"
    }
    create_model_record(tts_model_data, user_id, tenant_id)
    create_model_record(stt_model_data, user_id, tenant_id)


async def verify_invite_code(invite_code):
    logging.info(
        "detect admin registration request, start verifying invite code")
    logging.info(f"The INVITE_CODE obtained from consts.const: {INVITE_CODE}")
    if not INVITE_CODE:
        logging.error("please check the INVITE_CODE environment variable")
        raise NoInviteCodeException(
            "The system has not configured the admin invite code, please contact technical support")
    logging.info(f"User provided invite code: {invite_code}")
    if not invite_code:
        logging.warning("User did not provide invite code")
        raise IncorrectInviteCodeException("Please enter the invite code")
    if invite_code != INVITE_CODE:
        logging.warning(
            f"Admin invite code verification failed: user provided='{invite_code}', system configured='{INVITE_CODE}'")
        raise IncorrectInviteCodeException(
            "Please enter the correct admin invite code")
    logging.info("Admin invite code verification successful")


async def signin_user(email: EmailStr,
                      password: str):
    """User login"""
    client = get_supabase_client()

    response = client.auth.sign_in_with_password({
        "email": email,
        "password": password
    })

    # Get actual expiration time from access_token
    expiry_seconds = get_jwt_expiry_seconds(response.session.access_token)
    expires_at = calculate_expires_at(response.session.access_token)

    # Get role information from user metadata
    user_role = "user"  # Default role
    if 'role' in response.user.user_metadata:  # Adapt to historical user data
        user_role = response.user.user_metadata['role']

    logging.info(
        f"User {email} logged in successfully, session validity is {expiry_seconds} seconds, role: {user_role}")

    return {
        "message": f"Login successful, session validity is {expiry_seconds} seconds",
        "data": {
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
    }


async def refresh_user_token(authorization, refresh_token: str):
    client = get_authorized_client(authorization)
    session_info = extend_session(client, refresh_token)
    if not session_info:
        logging.error("Refresh token failed, the token may have expired")
        raise ValueError("Refresh token failed, the token may have expired")

    logging.info(
        f"Token refresh successful: session validity is {session_info['expires_in_seconds']} seconds")
    return session_info


async def get_session_by_authorization(authorization):
    # Extract clean token from authorization header
    clean_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

    # Use the unified token validation function
    is_valid, user = validate_token(clean_token)
    if is_valid and user:
        user_role = "user"  # Default role
        if user.user_metadata and 'role' in user.user_metadata:
            user_role = user.user_metadata['role']
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "role": user_role
            }
        }
    else:
        # Use domain-specific exception for invalid/expired token
        raise UnauthorizedError("Session is invalid or expired")


async def get_user_info(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user information including user ID, group IDs, tenant ID, user role, permissions, and accessible routes.
    All information is retrieved from PostgreSQL database.

    Args:
        user_id (str): User ID to query

    Returns:
        Optional[Dict[str, Any]]: User information dictionary containing:
            - user: User object with user_id, group_ids, tenant_id, user_email, user_role, permissions, accessibleRoutes
        Returns None if user not found
    """
    try:
        # Get user tenant relationship
        user_tenant = get_user_tenant_by_user_id(user_id)
        if not user_tenant:
            return None

        tenant_id = user_tenant["tenant_id"]
        user_role = user_tenant["user_role"]
        user_email = user_tenant["user_email"]

        # Get group IDs
        group_ids = query_group_ids_by_user(user_id)

        # Get user permissions directly from database
        with get_db_session() as session:
            permission_records = session.query(RolePermission).filter(
                RolePermission.user_role == user_role
            ).all()
            permissions = [as_dict(record) for record in permission_records]

        permissions_data = format_role_permissions(permissions)

        return {
            "user": {
                "user_id": user_id,
                "group_ids": group_ids,
                "tenant_id": tenant_id,
                "user_email": user_email,
                "user_role": user_role,
                "permissions": permissions_data["permissions"],
                "accessibleRoutes": permissions_data["accessibleRoutes"]
            }
        }

    except Exception as e:
        logging.error(
            f"Failed to get user info for user {user_id}: {str(e)}")
        return None


def format_role_permissions(permissions: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Format role permissions into permissions and accessibleRoutes lists.

    - permissions: List of permission strings (permission_type:permission_subtype for RESOURCE category)
    - accessibleRoutes: List of accessible route subtypes (permission_subtype for LEFT_NAV_MENU permission_type)

    Args:
        permissions (List[Dict[str, Any]]): Raw permission records from database

    Returns:
        Dict[str, List[str]]: Dictionary containing permissions and accessibleRoutes lists
    """
    formatted_permissions = []
    accessible_routes = []

    for perm in permissions:
        permission_category = perm.get("permission_category", "")
        permission_type = perm.get("permission_type", "")
        permission_subtype = perm.get("permission_subtype", "")

        if permission_category == "RESOURCE" and permission_type and permission_subtype:
            # Format as "permission_type:permission_subtype"
            formatted_permissions.append(
                f"{permission_type}:{permission_subtype}")
        elif permission_type == "LEFT_NAV_MENU" and permission_subtype:
            # Add permission_subtype to accessible routes for LEFT_NAV_MENU type
            accessible_routes.append(permission_subtype)

    return {
        "permissions": formatted_permissions,
        "accessibleRoutes": accessible_routes
    }
