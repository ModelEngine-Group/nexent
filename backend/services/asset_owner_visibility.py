"""ASSET_OWNER tenant visibility filters and response post-processing."""

import hashlib
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Query

from consts.const import (
    AGENT_PROMPTS_HIDDEN_FLAG,
    ASSET_OWNER_ATTACHMENTS_PREFIX,
    ASSET_OWNER_ROLE,
    ASSET_OWNER_TENANT_ID,
    PERMISSION_EDIT,
    PERMISSION_READ,
)

# Prefabricated skill records use source=custom (global, not tenant-owned).
PREFAB_SKILL_SOURCE = "custom"

_PROMPT_FIELDS = ("duty_prompt", "constraint_prompt", "few_shots_prompt")


_PREVIEW_CACHE_PREFIXES = ("preview/converted/", "preview/converting/")
_PREVIEW_HASH_PATTERN = re.compile(r"^(.+)_[0-9a-f]{8}(\.pdf|\.pdf\.tmp)?$")
_OFFICE_EXTENSIONS = (".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls")


def _parse_preview_cache_object_name(preview_object_name: str) -> Optional[str]:
    """
    Recover the source object_name from a preview cache key, if possible.

    Cache layout matches resolve_preview_file:
    preview/converted/{source_without_ext}_{md5(source)[:8]}.pdf
    """
    for prefix in _PREVIEW_CACHE_PREFIXES:
        if not preview_object_name.startswith(prefix):
            continue
        remainder = preview_object_name[len(prefix):]
        match = _PREVIEW_HASH_PATTERN.match(remainder)
        if not match:
            return None
        source_without_ext = match.group(1)
        hash_suffix = remainder.rsplit("_", 1)[-1][:8]
        for ext in _OFFICE_EXTENSIONS:
            candidate = f"{source_without_ext}{ext}"
            expected_hash = hashlib.md5(candidate.encode()).hexdigest()[:8]
            if expected_hash == hash_suffix:
                return candidate
        return None
    return None


def _is_legacy_root_attachment(object_name: str) -> bool:
    """True for attachments/filename (no user_id subdirectory)."""
    if not object_name.startswith("attachments/"):
        return False
    return "/" not in object_name.replace("attachments/", "", 1)


def can_access_file(
    object_name: str,
    caller_user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
) -> bool:
    """
    Return True when the caller may read a MinIO object.

    Rules (in order):
    - No caller_user_id -> False
    - preview cache paths -> delegate to source object access
    - attachments/asset_owner/{user_id}/* -> ASSET_OWNER tenant and matching user_id
    - knowledge_base/* -> all authenticated users
    - attachments/{caller_user_id}/* -> owner only
    - legacy attachments/filename -> all authenticated users (backward compatible)
    - otherwise -> False
    """
    if not caller_user_id:
        return False

    if any(object_name.startswith(prefix) for prefix in _PREVIEW_CACHE_PREFIXES):
        source = _parse_preview_cache_object_name(object_name)
        if source is None:
            return False
        return can_access_file(source, caller_user_id, caller_tenant_id)

    asset_owner_prefix = f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/"
    if object_name.startswith(asset_owner_prefix):
        if caller_tenant_id != ASSET_OWNER_TENANT_ID:
            return False
        remainder = object_name[len(asset_owner_prefix):]
        path_user_id = remainder.split("/", 1)[0] if remainder else ""
        return path_user_id == str(caller_user_id)

    if object_name.startswith("knowledge_base/"):
        return True

    if object_name.startswith(f"attachments/{caller_user_id}/"):
        return True

    if _is_legacy_root_attachment(object_name):
        return True

    return False


def can_view_skill(caller_tenant_id: Optional[str], skill_tenant_id: Optional[str]) -> bool:
    """
    Return True when the caller may view a skill and its files.

    ASSET_OWNER-scoped skills (tenant_id asset_owner_tenant_id or legacy "") are
    visible only to callers in the ASSET_OWNER virtual tenant.
    """

    if skill_tenant_id == ASSET_OWNER_TENANT_ID:
        return caller_tenant_id == ASSET_OWNER_TENANT_ID
    return True


def _is_asset_owner_scoped_tenant(tenant_id: Optional[str]) -> bool:
    """Return True when a record belongs to the ASSET_OWNER virtual tenant scope."""
    return tenant_id in (ASSET_OWNER_TENANT_ID, "")


def resolve_agent_list_permission(
    user_role: str,
    agent: Dict[str, Any],
    user_id: str,
    can_edit_all: bool,
) -> str:
    """
    Resolve list-item permission for an agent.

    Highest priority: ASSET_OWNER-scoped agents are READ_ONLY for callers whose
    user_role is not ASSET_OWNER (overrides can_edit_all, creator, ingroup_permission).
    """
    role = (user_role or "").upper()
    if _is_asset_owner_scoped_tenant(agent.get("tenant_id")) and role != ASSET_OWNER_ROLE:
        return PERMISSION_READ
    if can_edit_all or str(agent.get("created_by")) == str(user_id):
        return PERMISSION_EDIT
    ingroup_permission = agent.get("ingroup_permission")
    return ingroup_permission if ingroup_permission is not None else PERMISSION_READ


def apply_agent_detail_prompt_visibility(
    caller_tenant_id: Optional[str],
    agent_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Mask system prompt fields when a non-ASSET_OWNER caller views an ASSET_OWNER-scoped agent.

    Sets duty_prompt, constraint_prompt, and few_shots_prompt to None and adds
    prompts_hidden=True so clients can render a permission-denied state.
    """
    result = dict(agent_info)
    if caller_tenant_id == ASSET_OWNER_TENANT_ID:
        return result
    if not _is_asset_owner_scoped_tenant(result.get("tenant_id")):
        return result
    for field in _PROMPT_FIELDS:
        result[field] = None
    result[AGENT_PROMPTS_HIDDEN_FLAG] = True
    return result


def postprocess_agent_visibility(
    items: List[Dict[str, Any]],
    caller_role: Optional[str],
    caller_tenant_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Return agent records after visibility post-processing (no-op for now)."""
    _ = (caller_role, caller_tenant_id)
    return items


def postprocess_knowledge_visibility(
    items: List[Dict[str, Any]],
    caller_role: Optional[str],
    caller_tenant_id: Optional[str],
) -> List[Dict[str, Any]]:
    """Return knowledge records after visibility post-processing (no-op for now)."""
    _ = (caller_role, caller_tenant_id)
    return items
