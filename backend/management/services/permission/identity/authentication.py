# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from types import SimpleNamespace
from sqlalchemy import select
from typing import Optional, Any, Tuple, Dict, List

from management.db.identity.token import create_token as create_token_record, generate_access_key, list_tokens_by_user as list_tokens_by_user_record, delete_token as delete_token_record

from pydantic import EmailStr

from gateway.authentication.auth import (
    get_current_user_id,
    generate_session_jwt,
    require_active_account,
    calculate_expires_at,
    get_jwt_expiry_seconds,
    ensure_cas_session_active_from_authorization,
    resolve_tenant_id_from_user_tenant_record,
)
from contracts.constants.environment import INVITE_CODE, JWT_SECRET
from contracts.constants.constants import ASSET_OWNER_TENANT_ID, ASSET_OWNER_INVITE_CODE_TYPE, ASSET_OWNER_ROLE, ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL

from management.services.permission.asset_owner import (
    filter_accessible_routes_for_asset_owner_feature,
    require_asset_owner_enabled,
)
from contracts.errors.exceptions import NoInviteCodeException, IncorrectInviteCodeException, UserRegistrationException, UnauthorizedError, TenantResourceLimitError, ValidationError
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException

from management.db.model.repository import create_model_record
from management.db.identity.user_tenant import insert_user_tenant, get_user_tenant_by_user_id
from management.db.identity.oauth_account import list_oauth_accounts_by_user_id
from management.db.identity.group import query_group_ids_by_user
from management.utils.orm import as_dict
from management.db.client import get_db_session
from management.db.models import RolePermission, UserAccount
from management.db.identity.account import create_account, get_account_by_email, change_password
from infrastructure.security.passwords import hash_password, verify_password
from management.services.permission.identity.invitations import use_invitation_code, check_invitation_available, get_invitation_by_code
from management.services.permission.identity.groups import add_user_to_groups
from management.services.tool.configuration import init_tool_list_for_tenant
from management.services.skill.transfer import init_skill_list_for_tenant


logging.getLogger("user_management_service").setLevel(logging.INFO)


def get_provider_username(user_id: str, provider: str) -> Optional[str]:
    """Return a non-empty username stored for a linked authentication provider."""
    try:
        accounts = list_oauth_accounts_by_user_id(user_id)
    except Exception as e:
        logging.warning(
            "Failed to load %s username for user %s: %s", provider, user_id, e
        )
        return None

    for account in accounts:
        if account.get("provider") != provider:
            continue
        username = str(account.get("provider_username") or "").strip()
        if username:
            return username
    return None




def build_token_response(user_id: str) -> dict:
    """Keep the existing response object without a server-side session store."""
    token = generate_session_jwt(user_id)
    return {"access_token": token, "refresh_token": "", "expires_at": calculate_expires_at(token),
            "expires_in_seconds": get_jwt_expiry_seconds(token)}


async def check_auth_service_health():
    if not JWT_SECRET:
        raise ConnectionError("JWT signing is not configured")
    try:
        with get_db_session() as session:
            session.execute(select(UserAccount.account_id).limit(1))
    except Exception as exc:
        raise ConnectionError("Local account store is unavailable") from exc


async def signup_user_with_invitation(email: EmailStr,
                                      password: str,
                                      invite_code: Optional[str] = None,
                                      auto_login: Optional[bool] = True):
    """User registration with invitation code support"""
    if not isinstance(invite_code, str) or not invite_code.strip():
        raise ValidationError("INVITE_CODE_REQUIRED")
    invite_code = invite_code.strip().upper()

    # Validate password strength before registration
    if not validate_password_strength(password):
        raise AppException(ErrorCode.PROFILE_PASSWORD_WEAK,
                           "Password must be at least 8 characters with uppercase, lowercase, and digit.")

    logging.info(
        f"Receive registration request: email={email}, invite_code={'provided' if invite_code else 'not provided'}, auto_login={auto_login}")

    # Default user role is USER
    user_role = "USER"
    invitation_info = None

    # Validate invitation code if provided (without using it yet)
    if invite_code:
        try:
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
            elif code_type == ASSET_OWNER_INVITE_CODE_TYPE:
                require_asset_owner_enabled()
                raise ValidationError(ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL)

            logging.info(
                f"Invitation code {invite_code} validated successfully, will assign role: {user_role}")

        except IncorrectInviteCodeException:
            raise
        except ValidationError:
            raise
        except Exception as e:
            logging.error(
                f"Invitation code {invite_code} validation failed: {str(e)}")
            raise IncorrectInviteCodeException(
                f"Invalid invitation code: {str(e)}")

    # Identity and membership share a transaction so resource-limit failures
    # cannot leave a login-capable orphan behind.
    tenant_id = invitation_info["tenant_id"]
    is_asset_owner_registration = user_role == ASSET_OWNER_ROLE
    with get_db_session() as session:
        account = create_account(email, hash_password(password), db_session=session)
        user_id = account["user_id"]
        insert_user_tenant(user_id=user_id, tenant_id=tenant_id, user_role=user_role,
                           user_email=account["email"], db_session=session)

    # Use invitation code now that we have the real user_id
    if invitation_info:
        try:
            invitation_result = use_invitation_code(invite_code, user_id)
            logging.debug(
                f"Invitation code {invite_code} used successfully for user {user_id}")

            # Add user to groups specified in invitation code
            group_ids = invitation_result.get("group_ids", [])
            if group_ids and not is_asset_owner_registration:
                try:
                    # Convert group_ids from string to list if needed
                    if isinstance(group_ids, str):
                        from management.utils.serialization import convert_string_to_list
                        group_ids = convert_string_to_list(group_ids)

                    if group_ids:
                        group_results = add_user_to_groups(
                            user_id, group_ids, user_id)
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
        f"User {email} registered successfully, role: {user_role}, tenant: {tenant_id}, auto_login={auto_login}")


    # Initialize tool list for the new tenant (only once per tenant)
    if not is_asset_owner_registration:
        await init_tool_list_for_tenant(tenant_id, user_id)
        await init_skill_list_for_tenant(tenant_id, user_id)

    return {"user": {"id": user_id, "email": account["email"], "role": user_role},
            "session": build_token_response(user_id) if auto_login else None,
            "registration_type": "user"}


async def verify_invite_code(invite_code):
    logging.info(
        "detect admin registration request, start verifying invite code")
    logging.info(f"The INVITE_CODE obtained from contracts.constants.environment: {INVITE_CODE}")
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


async def signin_user(email: EmailStr, password: str):
    account = get_account_by_email(email)
    # Do password work even for unknown accounts to reduce user enumeration.
    encoded = account.get("password_hash") if account else None
    if not encoded:
        encoded = hash_password("invalid-account-placeholder")
    valid = verify_password(password, encoded)
    if not account or not valid or not account["password_login_enabled"] or not account["email_confirmed_at"]:
        raise UnauthorizedError("Email or password error")
    require_active_account(account["user_id"])
    membership = get_user_tenant_by_user_id(account["user_id"])
    if not membership:
        raise UnauthorizedError("No active tenant relationship")
    if membership.get("user_role") == ASSET_OWNER_ROLE:
        require_asset_owner_enabled()
    return {"message": "Login successful", "data": {
        "user": {"id": account["user_id"], "email": account["email"], "role": membership["user_role"]},
        "session": build_token_response(account["user_id"]),
    }}


async def refresh_user_token(authorization, refresh_token: str):
    # Preserve the route, but never exchange legacy refresh tokens for local JWTs.
    raise UnauthorizedError("Token refresh is unavailable; please log in again")




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
            logging.warning("User has no active tenant membership")
            return None

        tenant_id = resolve_tenant_id_from_user_tenant_record(user_tenant)
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
                "accessibleRoutes": permissions_data["accessibleRoutes"],
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
            # Normalize to lower-case "type:subtype" so backend RBAC, frontend
            # Can checks, and user info responses share one permission format.
            formatted_permissions.append(
                f"{permission_type}:{permission_subtype}".lower())
        elif permission_type == "LEFT_NAV_MENU" and permission_subtype:
            # Add permission_subtype to accessible routes for LEFT_NAV_MENU type
            accessible_routes.append(permission_subtype)

    accessible_routes = filter_accessible_routes_for_asset_owner_feature(
        accessible_routes
    )

    return {
        "permissions": formatted_permissions,
        "accessibleRoutes": accessible_routes,
    }


# -----------------------------
# Token Management
# -----------------------------

def create_token(user_id: str) -> Dict[str, Any]:
    """Create a new API token for the specified user.

    Args:
        user_id: The user ID who owns this token.

    Returns:
        Dictionary containing the API token information including token_id.
    """
    from management.db.client import get_db_session
    from management.db.identity.token import soft_delete_tokens_by_user

    access_key = generate_access_key()
    with get_db_session() as session:
        soft_delete_tokens_by_user(user_id, user_id, session)
        token = create_token_record(access_key, user_id, created_by=user_id, db_session=session)
    return {**token, "can_copy": True}


def _mask_access_key(access_key: str) -> str:
    """Keep the key prefix and suffix visible while hiding its secret middle."""
    if len(access_key) <= 8:
        return "*" * len(access_key)
    prefix_length = min(10, len(access_key) - 5)
    return f"{access_key[:prefix_length]}{'*' * (len(access_key) - prefix_length - 4)}{access_key[-4:]}"


def list_tokens_by_user(user_id: str, actor_role: str) -> List[Dict[str, Any]]:
    """List all tokens for the specified user.

    Args:
        user_id: The user ID to query token pairs for.
        actor_role: Role of the authenticated user requesting the list.

    Returns:
        List of token information. Administrators can view and copy complete
        keys; other roles receive masked, non-copyable values.
    """
    can_copy = (actor_role or "").upper() in {"ADMIN", "SU"}
    tokens = list_tokens_by_user_record(user_id)
    return [
        {
            **token,
            "access_key": token["access_key"] if can_copy else _mask_access_key(token["access_key"]),
            "can_copy": can_copy,
        }
        for token in tokens
    ]


def delete_token(token_id: int, user_id: str) -> bool:
    """Soft delete a token.

    Args:
        token_id: The token ID to delete.
        user_id: The user ID who owns this token (for authorization).

    Returns:
        True if the token was deleted, False if not found or not owned by user.
    """
    return delete_token_record(token_id, user_id)


# -----------------------------
# Password Management
# -----------------------------

def validate_password_strength(password: str) -> bool:
    """Validate password meets minimum security requirements.

    Args:
        password: The password to validate.

    Returns:
        True if password meets requirements, False otherwise.
    """
    if len(password) < 8 or len(password.encode("utf-8")) > 1024:
        return False
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_upper and has_lower and has_digit


async def update_password(user_id: str, old_password: str, new_password: str) -> bool:
    """Update user password with old password verification.

    This method first re-authenticates the user with their old password,
    then updates to the new password.

    Args:
        user_id: The user ID to update password for.
        old_password: The current password for verification.
        new_password: The new password to set.

    Returns:
        True if password was updated successfully.

    Raises:
        UnauthorizedError: If old password is incorrect.
        AppException (PROFILE_PASSWORD_WEAK): If new password does not meet requirements.
        AppException (PROFILE_PASSWORD_SAME_AS_OLD): If new password is the same as old password.
    """
    if not validate_password_strength(new_password):
        raise AppException(ErrorCode.PROFILE_PASSWORD_WEAK)

    if old_password == new_password:
        raise AppException(ErrorCode.PROFILE_PASSWORD_SAME_AS_OLD)

    account = require_active_account(user_id)
    if not account["password_login_enabled"] or not verify_password(old_password, account.get("password_hash") or ""):
        raise UnauthorizedError("Invalid old password")
    if not change_password(user_id, account["password_hash"], hash_password(new_password)):
        raise UnauthorizedError("Credentials changed concurrently; please log in again")
    return True
