# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
User service layer - handles user-related business logic
"""

import logging
from typing import Any, Dict, List, Optional

from contracts.errors.exceptions import ForbiddenError, NotFoundException
from contracts.roles import has_any_role, primary_role, roles_from_record
from management.db.conversation.repository import soft_delete_all_conversations_by_user
from management.db.identity.account import delete_account
from management.db.identity.group import (
    query_groups_by_users,
    remove_user_from_all_groups,
)
from management.db.identity.oauth_account import (
    soft_delete_all_oauth_accounts_by_user_id,
)
from management.db.identity.token import soft_delete_tokens_by_user
from management.db.identity.user_tenant import (
    get_user_tenant_by_user_id,
    get_users_by_tenant_id,
    soft_delete_user_tenant_by_user_id,
)
from management.db.knowledge_base.repository import (
    get_private_knowledge_info_by_creator,
)
from management.db.memory.config import soft_delete_all_configs_by_user_id
from management.services.knowledge_base import management as knowledge_management
from management.services.knowledge_base.common import get_vector_db_core
from management.services.permission.identity.display import enrich_cas_usernames
from management.services.permission.identity.roles import replace_roles

logger = logging.getLogger(__name__)


def get_users(tenant_id: str, page: Optional[int] = 1, page_size: Optional[int] = 20,
              sort_by: str = "created_at", sort_order: str = "desc",
              search: Optional[str] = None, roles: Optional[List[str]] = None,
              group_ids: Optional[List[int]] = None, *,
              search_cas_username: bool = False) -> Dict[str, Any]:
    """
    Get users belonging to a specific tenant with pagination and sorting

    Args:
        tenant_id (str): Tenant ID
        page (Optional[int]): Page number (1-based). If None, returns all data
        page_size (Optional[int]): Number of items per page. If None, returns all data
        sort_by (str): Field to sort by
        sort_order (str): Sort order (asc or desc)

    Returns:
        Dict[str, Any]: Dictionary containing users list and pagination info
    """
    # Get user-tenant relationships from database with pagination and sorting
    if search or roles or group_ids:
        result = get_users_by_tenant_id(
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            roles=roles,
            group_ids=group_ids,
            **({"search_cas_username": True} if search_cas_username else {}),
        )
    else:
        result = get_users_by_tenant_id(tenant_id, page, page_size, sort_by, sort_order)

    # Batch fetch group names for all users in a single query
    tenant_user_ids = [r["user_id"] for r in result["users"]]
    user_group_map = query_groups_by_users(tenant_user_ids)

    users = [
        {
            "id": r["user_id"],
            "username": r.get("user_email"),
            "role": r["user_role"],
            "roles": list(roles_from_record(r)),
            "tenant_id": r["tenant_id"],
            "group_names": user_group_map.get(r["user_id"], []),
        }
        for r in result["users"]
    ]

    enrich_cas_usernames(users, {"cas_username": "id"})

    # Calculate pagination info only if pagination is used
    if page is not None and page_size is not None:
        return {
            "users": users,
            "total": result["total"],
            "page": page,
            "page_size": page_size,
            "total_pages": (result["total"] + page_size - 1) // page_size
        }
    return {
        "users": users,
        "total": result["total"]
    }


def get_users_for_requester(
    tenant_id: str,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: Optional[str] = None,
    roles: Optional[List[str]] = None,
    group_ids: Optional[List[int]] = None,
    *,
    requester_tenant_id: str,
    requester_role: str,
    search_cas_username: bool = False,
) -> Dict[str, Any]:
    """List users after enforcing role and tenant boundaries."""
    role = requester_role

    if has_any_role(role, {'SU'}):
        pass
    elif has_any_role(role, {'ADMIN', 'OPS'}) and tenant_id == requester_tenant_id:
        pass
    else:
        raise ForbiddenError("Not authorized to list users for this tenant")

    # Keep the legacy call shape when no filters are supplied. Besides avoiding
    # unnecessary arguments, this preserves compatibility with callers that
    # mock the pre-filter signature.
    if search or roles or group_ids:
        return get_users(
            tenant_id, page, page_size, sort_by, sort_order, search, roles, group_ids,
            **({"search_cas_username": True} if search_cas_username else {}),
        )
    return get_users(tenant_id, page, page_size, sort_by, sort_order)


async def update_user(user_id: str, update_data: Dict[str, Any], updated_by: str) -> Dict[str, Any]:
    """Replace roles atomically; preserve compatibility fields in the response."""
    values = update_data.get("roles")
    legacy = values is None
    if legacy:
        values = update_data.get("role")
    if values is None:
        raise ValueError("Role update is required")
    member = replace_roles(updated_by, user_id, values, legacy=legacy)
    roles = roles_from_record(member)
    result = {"id": user_id, "username": member.get("user_email"),
              "role": primary_role(roles, member.get("user_role")), "roles": list(roles)}
    enrich_cas_usernames([result], {"cas_username": "id"})
    return result


async def update_user_for_requester(
    user_id: str,
    update_data: Dict[str, Any],
    *,
    updated_by: str,
    requester_tenant_id: str,
    requester_role: str,
) -> Dict[str, Any]:
    """Update a user after enforcing management role and tenant boundaries."""
    target_user = get_user_tenant_by_user_id(user_id)
    if not target_user:
        raise NotFoundException(f"User {user_id} not found")

    role = requester_role
    target_role = roles_from_record(target_user)
    target_tenant_id = target_user.get("tenant_id")


    if has_any_role(role, {'SU'}):
        pass
    elif has_any_role(role, {'ADMIN'}) and target_tenant_id == requester_tenant_id and not has_any_role(target_role, {'SU'}):
        pass
    else:
        raise ForbiddenError("Not authorized to update this user")

    return await update_user(user_id, update_data, updated_by)


async def _delete_private_knowledge_bases(user_id: str, tenant_id: str) -> Optional[Dict[str, int]]:
    """Delete PRIVATE knowledge bases created by a user."""
    private_kbs = get_private_knowledge_info_by_creator(tenant_id, user_id)
    if not private_kbs:
        return None


    vdb_core = get_vector_db_core()
    succeeded = 0
    failed = 0
    for kb in private_kbs:
        index_name = kb.get("index_name")
        kb_id = kb.get("knowledge_id")
        if not index_name:
            failed += 1
            logger.error(
                "Personal KB %s for user %s has no index_name",
                kb_id,
                user_id,
            )
            continue
        try:
            await knowledge_management.KnowledgeBaseManagementService.full_delete_knowledge_base(
                index_name, vdb_core, user_id
            )
            succeeded += 1
        except Exception:
            failed += 1
            logger.exception(
                "Failed deleting personal KB for user %s kb_id %s index_name %s",
                user_id,
                kb_id,
                index_name,
            )

    cleanup_result = {
        "total": len(private_kbs),
        "succeeded": succeeded,
        "failed": failed,
    }
    logger.info("Personal KB cleanup for user %s: %s", user_id, cleanup_result)
    return cleanup_result


async def delete_user_and_cleanup(user_id: str, tenant_id: str, *, actor_id: str = None, membership_removed: bool = False) -> None:
    """
    Permanently delete user account and all related data.

    This performs complete cleanup:
    1) Soft-delete user-tenant relation and remove from all groups
    2) Soft-delete memory user configs and all conversations
    3) Clear user-level memories in memory store
    4) Delete personal KBs created by the user
    5) Disable the local authentication account

    Args:
        user_id (str): User ID to delete
        tenant_id (str): Tenant ID for memory operations
    """
    try:
        logger.debug(f"Start permanently deleting user {user_id} and all related data...")
        # 1) Core user deletion (soft-delete user-tenant and groups)
        try:
            tenant_deleted = membership_removed or soft_delete_user_tenant_by_user_id(user_id, actor_id or user_id)
            if not tenant_deleted:
                raise ValueError(f"User {user_id} not found in any tenant")

        except Exception as e:
            logger.error(f"Failed core deletion for user {user_id}: {e}")
            raise

        try:
            remove_user_from_all_groups(user_id, actor_id or user_id)
        except Exception:
            logger.exception("Failed group cleanup for user %s", user_id)

        # 2) Soft-delete memory configs
        try:
            soft_delete_all_configs_by_user_id(user_id, actor=user_id)
            logger.debug("\tMemory user configs deleted.")
        except Exception as e:
            logger.error(f"Failed deleting configs for user {user_id}: {e}")

        # 3) Soft-delete conversations
        try:
            deleted_convs = soft_delete_all_conversations_by_user(user_id)
            logger.debug(f"\t{deleted_convs} conversations deleted.")
        except Exception as e:
            logger.error(f"Failed deleting conversations for user {user_id}: {e}")

        # 4) Memory record cleanup: in the new Memory system this is performed
        # by ``MemoryService.forget_user`` (PG + ES purge). The legacy
        # mem0-era ``clear_memory`` path has been removed; the new path will
        # be wired in once the storage layer lands in Phase 2.
        # 5) Soft-delete OAuth account bindings
        try:
            deleted_oauth = soft_delete_all_oauth_accounts_by_user_id(user_id, user_id)
            logger.debug(f"\t{deleted_oauth} OAuth account bindings deleted.")
        except Exception as e:
            logger.error(f"Failed deleting OAuth accounts for user {user_id}: {e}")

        # 6) Revoke all API keys before the identity is removed.
        try:

            soft_delete_tokens_by_user(user_id, user_id)
            logger.debug("\tUser API keys revoked.")
        except Exception as e:
            logger.error(f"Failed revoking API keys for user {user_id}: {e}")

        # Disable credentials even if a preceding best-effort resource cleanup failed.
        delete_account(user_id)

        # 7) Delete PRIVATE personal KBs created by the user. Shared KBs
        # created by the user are intentionally left untouched.
        cleanup_result = None
        try:
            cleanup_result = await _delete_private_knowledge_bases(user_id, tenant_id)
        except Exception:
            logger.exception("Failed personal KB cleanup for user %s", user_id)

        logger.info(f"Permanently deleted user {user_id} and all related data.")
        return cleanup_result

    except Exception as exc:
        logger.error(f"Unexpected error in delete_user_and_cleanup for {user_id}: {str(exc)}")
        raise
