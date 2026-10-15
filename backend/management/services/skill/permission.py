"""Skill visibility, editing and access-change policy."""

from typing import Any, Dict, Optional

from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    PERMISSION_EDIT,
    PERMISSION_PRIVATE,
    PERMISSION_READ,
)
from consts.exceptions import ForbiddenError
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.str_utils import convert_list_to_string

_SKILL_ACCESS_UPDATE_FORBIDDEN_MESSAGE = "Not authorized to update skill access"


def _to_group_id_set(group_ids: Any) -> set[int]:
    if isinstance(group_ids, str):
        return {
            int(group_id.strip())
            for group_id in group_ids.split(",")
            if group_id.strip().isdigit()
        }
    if isinstance(group_ids, list):
        return {
            int(group_id) for group_id in group_ids if str(group_id).strip().isdigit()
        }
    return set()


def can_view_skill(
    *,
    skill: Dict[str, Any],
    user_id: str,
    user_role: str,
    user_group_ids: set[int],
) -> bool:
    """Return whether a skill is available to the current user."""
    if skill.get("source") == "official":
        return True
    if user_role in CAN_EDIT_ALL_USER_ROLES:
        return True
    if str(skill.get("created_by")) == str(user_id):
        return True
    if skill.get("ingroup_permission") == PERMISSION_PRIVATE:
        return False
    return bool(user_group_ids.intersection(_to_group_id_set(skill.get("group_ids"))))


def resolve_skill_permission(
    *,
    skill: Dict[str, Any],
    user_id: str,
    user_role: str,
    user_group_ids: set[int],
) -> str:
    """Resolve whether the current user can edit or only use a visible skill."""
    if user_role in CAN_EDIT_ALL_USER_ROLES:
        return PERMISSION_EDIT
    if str(skill.get("created_by")) == str(user_id):
        return PERMISSION_EDIT
    if skill.get("ingroup_permission") != PERMISSION_EDIT:
        return PERMISSION_READ
    return (
        PERMISSION_EDIT
        if user_group_ids.intersection(_to_group_id_set(skill.get("group_ids")))
        else PERMISSION_READ
    )


def _apply_default_skill_permission_fields(
    skill_data: Dict[str, Any],
    user_id: Optional[str],
) -> None:
    """Default user-created skills to the creator's groups with edit permission."""
    if not user_id:
        return
    if skill_data.get("group_ids") is None:
        skill_data["group_ids"] = convert_list_to_string(
            query_group_ids_by_user(user_id)
        )
    if not skill_data.get("ingroup_permission"):
        skill_data["ingroup_permission"] = PERMISSION_EDIT


def _get_user_role(user_id: Optional[str]) -> str:
    if not user_id:
        return "USER"
    user_tenant = get_user_tenant_by_user_id(user_id)
    if not user_tenant:
        return "USER"
    return str(user_tenant.get("user_role") or "USER")


def _can_edit_skill(skill: Dict[str, Any], user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    user_role = _get_user_role(user_id)
    user_group_ids = set(query_group_ids_by_user(user_id) or [])
    return (
        resolve_skill_permission(
            skill=skill,
            user_id=user_id,
            user_role=user_role,
            user_group_ids=user_group_ids,
        )
        == PERMISSION_EDIT
    )


def _can_manage_skill_access(skill: Dict[str, Any], user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    return _get_user_role(user_id) in CAN_EDIT_ALL_USER_ROLES or str(
        skill.get("created_by")
    ) == str(user_id)


def _has_skill_access_changes(
    existing: Dict[str, Any], skill_data: Dict[str, Any]
) -> bool:
    if "group_ids" in skill_data and _to_group_id_set(
        skill_data.get("group_ids")
    ) != _to_group_id_set(existing.get("group_ids")):
        return True
    return "ingroup_permission" in skill_data and skill_data.get(
        "ingroup_permission"
    ) != existing.get("ingroup_permission")


def _validate_skill_access_update(
    existing: Dict[str, Any], skill_data: Dict[str, Any], user_id: Optional[str]
) -> None:
    if (
        user_id
        and _has_skill_access_changes(existing, skill_data)
        and not _can_manage_skill_access(existing, user_id)
    ):
        raise ForbiddenError(_SKILL_ACCESS_UPDATE_FORBIDDEN_MESSAGE)
