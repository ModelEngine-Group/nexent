import logging
from typing import Optional, Any, Tuple

import aiohttp
from fastapi import Header
from supabase import Client
from pydantic import EmailStr

from utils.auth_utils import (
    get_supabase_client,
    get_supabase_admin_client,
    calculate_expires_at,
    get_jwt_expiry_seconds,
)
from consts.const import INVITE_CODE, SUPABASE_URL, SUPABASE_KEY
from consts.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException, UnauthorizedError

from database.model_management_db import create_model_record
from database.user_tenant_db import insert_user_tenant, soft_delete_user_tenant_by_user_id
from database.memory_config_db import soft_delete_all_configs_by_user_id
from database.conversation_db import soft_delete_all_conversations_by_user
from utils.memory_utils import build_memory_config
from nexent.memory.memory_service import clear_memory


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
        insert_user_tenant(user_id=user_id, tenant_id=tenant_id)

        logging.info(
            f"User {email} registered successfully, role: {user_role}, tenant: {tenant_id}")

        if is_admin:
            await generate_tts_stt_4_admin(tenant_id, user_id)

        return await parse_supabase_response(is_admin, response, user_role)
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


async def revoke_regular_user(user_id: str, tenant_id: str) -> None:
    """Revoke a regular user's account and purge related data.

    Steps:
    1) Soft-delete user-tenant relation rows and memory user configs, and all conversations for the user in PostgreSQL.
    2) Clear user-level memories in memory store (levels: "user" and "user_agent").
    3) Permanently delete the user from Supabase using service role key (admin API).
    """
    try:
        logging.debug(f"Start deleting user {user_id} related data...")
        # 1) PostgreSQL soft-deletes
        try:
            soft_delete_user_tenant_by_user_id(user_id, actor=user_id)
            logging.debug("\tTenant relationship deleted.")
        except Exception as e:
            logging.error(
                f"Failed soft-deleting user-tenant for user {user_id}: {e}")

        try:
            soft_delete_all_configs_by_user_id(user_id, actor=user_id)
            logging.debug("\tMemory user configs deleted.")
        except Exception as e:
            logging.error(
                f"Failed soft-deleting memory user configs for user {user_id}: {e}")

        try:
            deleted_convs = soft_delete_all_conversations_by_user(user_id)
            logging.debug(f"\t{deleted_convs} conversations deleted")
        except Exception as e:
            logging.error(
                f"Failed soft-deleting conversations for user {user_id}: {e}")

        # 2) Clear memory records
        try:
            memory_config = build_memory_config(tenant_id)
            # Clear user-level memory
            await clear_memory(
                memory_level="user",
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            # Also clear user_agent-level memory for all agents (API clears by user + any agent)
            await clear_memory(
                memory_level="user_agent",
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            logging.debug(
                "\tMemories under current embedding configuration deleted")
        except Exception as e:
            logging.error(f"Failed clearing memory for user {user_id}: {e}")

        # 3) Delete Supabase user using admin API
        try:
            admin_client = get_supabase_admin_client()
            if admin_client and hasattr(admin_client.auth, "admin"):
                admin_client.auth.admin.delete_user(user_id)
            else:
                raise RuntimeError("Supabase admin client not available")
            logging.debug("\tUser account deleted.")
        except Exception as e:
            logging.error(f"Failed deleting supabase user {user_id}: {e}")
            # prior steps already purged local data
        logging.info(f"Account {user_id} has been successfully deleted")
    except Exception as e:
        logging.error(
            f"Unexpected error in revoke_regular_user for {user_id}: {e}")
        # swallow to keep idempotent behavior
