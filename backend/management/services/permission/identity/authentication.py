# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from pydantic import EmailStr
from sqlalchemy import select

from contracts.constants.constants import (
    ASSET_OWNER_INVITE_CODE_TYPE,
    ASSET_OWNER_ROLE,
    ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL,
    ASSET_OWNER_TENANT_ID,
)
from contracts.constants.environment import INVITE_CODE, JWT_SECRET
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    AppException,
    IncorrectInviteCodeException,
    NoInviteCodeException,
    TenantResourceLimitError,
    UnauthorizedError,
    UserRegistrationException,
    ValidationError,
)
from contracts.roles import (
    has_any_role,
    invitation_roles,
    primary_role,
    roles_from_record,
)
from gateway.authentication.auth import (
    calculate_expires_at,
    ensure_cas_session_active_from_authorization,
    generate_session_jwt,
    get_current_user_id,
    get_jwt_expiry_seconds,
    require_active_account,
    resolve_tenant_id_from_user_tenant_record,
)
from infrastructure.security.passwords import hash_password, verify_password
from management.db.client import get_db_session
from management.db.identity.account import (
    change_password,
    create_account,
    get_account_by_email,
)
from management.db.identity.group import query_group_ids_by_user
from management.db.identity.oauth_account import list_oauth_accounts_by_user_id
from management.db.identity.token import (
    create_token as create_token_record,
)
from management.db.identity.token import (
    delete_token as delete_token_record,
)
from management.db.identity.token import (
    generate_access_key,
    mask_access_key,
    soft_delete_tokens_by_user,
)
from management.db.identity.token import (
    list_tokens_by_user as list_tokens_by_user_record,
)
from management.db.identity.user_tenant import (
    get_user_tenant_by_user_id,
    insert_user_tenant,
)
from management.db.model.repository import create_model_record
from management.db.models import RolePermission, UserAccount
from management.services.permission.asset_owner import (
    filter_accessible_routes_for_asset_owner_feature,
    require_asset_owner_enabled,
)
from management.services.permission.identity.groups import add_user_to_groups
from management.services.permission.identity.invitations import (
    check_invitation_available,
    get_invitation_by_code,
    use_invitation_code,
)
from management.services.permission.identity.registration import (
    register_invited_account,
)
from management.services.skill.transfer import init_skill_list_for_tenant
from management.services.tool.configuration import init_tool_list_for_tenant
from management.utils.orm import as_dict

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


async def signup_user_with_invitation(email: EmailStr, password: str,
                                      invite_code: Optional[str] = None,
                                      auto_login: Optional[bool] = True):
    """Create local account, tenant roles, groups and invitation usage atomically."""
    if not isinstance(invite_code, str) or not invite_code.strip():
        raise ValidationError("INVITE_CODE_REQUIRED")
    if not validate_password_strength(password):
        raise AppException(ErrorCode.PROFILE_PASSWORD_WEAK, "Password is too weak")
    invitation = get_invitation_by_code(invite_code.strip().upper())
    if not invitation:
        raise IncorrectInviteCodeException("Invitation is unavailable")
    if "ASSET_OWNER" in invitation_roles(invitation):
        require_asset_owner_enabled()
        raise ValidationError(ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL)
    account, member = register_invited_account(email, hash_password(password), invite_code)
    user_id, tenant_id = account["user_id"], member["tenant_id"]
    await init_tool_list_for_tenant(tenant_id, user_id)
    await init_skill_list_for_tenant(tenant_id, user_id)
    roles = roles_from_record(member)
    return {"user": {"id": user_id, "email": account["email"], "role": primary_role(roles), "roles": list(roles)},
            "session": build_token_response(user_id) if auto_login else None, "registration_type": "user"}


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
    if has_any_role(roles_from_record(membership), {ASSET_OWNER_ROLE}):
        require_asset_owner_enabled()
    return {"message": "Login successful", "data": {
        "user": {"id": account["user_id"], "email": account["email"], "role": membership["user_role"], "roles": list(roles_from_record(membership))},
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
                RolePermission.user_role.in_(roles_from_record(user_tenant))
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
                "roles": list(roles_from_record(user_tenant)),
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
        "permissions": list(dict.fromkeys(formatted_permissions)),
        "accessibleRoutes": list(dict.fromkeys(accessible_routes)),
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

    access_key = generate_access_key()
    with get_db_session() as session:
        soft_delete_tokens_by_user(user_id, user_id, session)
        token = create_token_record(access_key, user_id, created_by=user_id, db_session=session)
    return {
        **token,
        # The list endpoint returns the same pair, so a client renders the mask
        # and copies the complete key consistently right after a refresh.
        "masked_access_key": mask_access_key(token["access_key"]),
        "can_copy": True,
    }


def list_tokens_by_user(user_id: str, actor_role: str) -> List[Dict[str, Any]]:
    """List all tokens for the specified user.

    Args:
        user_id: The user ID to query token pairs for.
        actor_role: Role of the authenticated user requesting the list.

    Returns:
        List of token information. Display and copy are separate fields:
        ``masked_access_key`` is the masked value every client renders, and
        ``access_key`` holds the stored key only for roles whose
        ``can_copy`` is True. Copying therefore yields the complete key while
        other roles keep seeing a masked, non-copyable value.
    """
    can_copy = has_any_role(actor_role, {'ADMIN','SU'})
    # The persistence layer masks access keys by default, so the stored value is
    # requested here and role-based exposure below stays the single decision
    # point. Requesting the mask instead made can_copy True while the value was
    # already masked, so copying produced "nexent****11bb".
    tokens = list_tokens_by_user_record(user_id, mask=False)

    result: List[Dict[str, Any]] = []
    for token in tokens:
        masked_access_key = mask_access_key(token["access_key"])
        result.append({
            **token,
            # A copy-capable role receives the stored key, every other role
            # receives the masked value, and masked_access_key is what clients
            # display either way.
            "access_key": token["access_key"] if can_copy else masked_access_key,
            "masked_access_key": masked_access_key,
            "can_copy": can_copy,
        })
    return result


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
