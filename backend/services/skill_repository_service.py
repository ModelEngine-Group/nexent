import base64
import logging
import math
import re
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from consts.agent_repository import (
    OWNERSHIP_ALL,
    OWNERSHIP_CREATED,
    OWNERSHIP_OTHERS,
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
    VALID_OWNERSHIP_FILTERS,
    VALID_REPOSITORY_STATUSES,
)
from consts.const import PERMISSION_PRIVATE, PERMISSION_READ
from consts.exceptions import ForbiddenError, SkillDuplicateError, SkillException
from consts.notification import (
    EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
    RESOURCE_TYPE_SKILL_REPOSITORY,
)
from database.skill_repository_db import (
    get_skill_repository_by_id_and_publisher,
    get_skill_repository_by_skill_id,
    increment_skill_repository_downloads,
    insert_skill_repository_record,
    list_skill_repository_by_skill_ids,
    list_skill_repository_summaries,
    reset_skill_repository_status,
    update_skill_repository_by_id,
    update_skill_repository_status_by_id,
)
from database.skill_db import get_skill_by_name
from database.user_tenant_db import get_user_tenant_by_user_id
from services.notification_service import (
    create_repository_pending_review_notification,
    create_repository_review_notification,
    deactivate_notifications,
)
from services.skill_service import SkillService

logger = logging.getLogger("skill_repository_service")
_REPOSITORY_LISTING_NOT_FOUND = "Repository listing not found"

_MY_SKILL_REPOSITORY_STATUSES = frozenset({
    STATUS_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
})

_SU_STATUS_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_PENDING_REVIEW, STATUS_REJECTED),
    (STATUS_PENDING_REVIEW, STATUS_SHARED),
    (STATUS_SHARED, STATUS_NOT_SHARED),
})

_PUBLISHER_STATUS_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_NOT_SHARED, STATUS_PENDING_REVIEW),
    (STATUS_REJECTED, STATUS_PENDING_REVIEW),
    (STATUS_PENDING_REVIEW, STATUS_NOT_SHARED),
    (STATUS_REJECTED, STATUS_NOT_SHARED),
    (STATUS_SHARED, STATUS_NOT_SHARED),
})

_PUBLISHER_RESUBMIT_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_NOT_SHARED, STATUS_PENDING_REVIEW),
    (STATUS_REJECTED, STATUS_PENDING_REVIEW),
})

_ADMIN_REVIEW_STATUS_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset({
    (STATUS_PENDING_REVIEW, STATUS_REJECTED),
    (STATUS_PENDING_REVIEW, STATUS_SHARED),
})

_MAX_LISTING_TAGS = 5
_MAX_LISTING_TAG_LENGTH = 20
_MAX_LISTING_ICON_LENGTH = 32
_MAX_COPY_NAME_LENGTH = 100
_UPDATE_SNAPSHOT_FIELDS = (
    "name",
    "description",
    "source",
    "submitted_by",
    "category_id",
    "tags",
    "icon",
    "downloads",
    "skill_info_json",
    "skill_zip_base64",
    "status",
    "content",
)


def _serialize_created_at(create_time: Any) -> Optional[str]:
    """Serialize DB create_time to an ISO string for API consumers."""
    if create_time is None:
        return None
    if hasattr(create_time, "isoformat"):
        return create_time.isoformat()
    return str(create_time)


def _to_summary_item(
    record: Dict[str, Any],
    *,
    can_take_down: Optional[bool] = None,
) -> Dict[str, Any]:
    """Map a DB record to a lightweight skill marketplace summary item."""
    item = {
        "id": record.get("skill_repository_id"),
        "skill_repository_id": record.get("skill_repository_id"),
        "skill_id": record.get("skill_id"),
        "submitted_by": record.get("submitted_by"),
        "name": record.get("name"),
        "description": record.get("description"),
        "source": record.get("source"),
        "status": record.get("status"),
        "category_id": record.get("category_id"),
        "tags": record.get("tags") or [],
        "icon": record.get("icon"),
        "downloads": record.get("downloads") or 0,
        "created_at": record.get("created_at") or _serialize_created_at(record.get("create_time")),
        "updated_at": record.get("updated_at") or _serialize_created_at(record.get("update_time")),
        "content": record.get("content"),
    }
    if can_take_down is not None:
        item["can_take_down"] = can_take_down
    return item


def _to_detail_item(
    record: Dict[str, Any],
    *,
    is_updated: Optional[bool] = None,
) -> Dict[str, Any]:
    """Map a DB record to a skill marketplace detail payload."""
    snapshot = _as_dict(record.get("skill_info_json"))
    creator_id = str(snapshot.get("created_by") or "").strip()
    creator = get_user_tenant_by_user_id(creator_id) if creator_id else None
    author = str((creator or {}).get("user_email") or "").strip() or None
    detail = {
        "skill_repository_id": record.get("skill_repository_id"),
        "skill_id": record.get("skill_id"),
        "name": record.get("name"),
        "description": record.get("description"),
        "source": record.get("source"),
        "author": author,
        "submitted_by": record.get("submitted_by"),
        "icon": record.get("icon"),
        "status": record.get("status"),
        "category_id": record.get("category_id"),
        "tags": record.get("tags") or _as_list(snapshot.get("tags")),
        "downloads": record.get("downloads") or 0,
        "created_at": _serialize_created_at(record.get("create_time")),
        "updated_at": _serialize_created_at(record.get("update_time")),
        "content": record.get("content"),
        "config_schemas": _as_dict(snapshot.get("config_schemas")),
        "config_values": _as_dict(snapshot.get("config_values")),
        "tool_ids": _as_list(snapshot.get("tool_ids")),
    }
    if is_updated is not None:
        detail["is_updated"] = is_updated
    return detail


def _as_list(value: Any) -> List[Any]:
    """Return list values safely for JSON snapshot fields."""
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    """Return dict values safely for JSON snapshot fields."""
    return value if isinstance(value, dict) else {}


def _to_repository_info_item(record: Dict[str, Any]) -> Dict[str, Any]:
    """Map a repository DB row to a my-skills repository_info entry."""
    return {
        "skill_repository_id": record.get("skill_repository_id"),
        "status": record.get("status"),
        "create_time": _serialize_created_at(record.get("create_time")),
    }


def _matches_ownership(skill: Dict[str, Any], user_id: str, ownership_filter: str) -> bool:
    """Return whether a skill belongs to the requested ownership bucket."""
    if ownership_filter == OWNERSHIP_ALL:
        return True
    is_creator = str(skill.get("created_by")) == str(user_id)
    if ownership_filter == OWNERSHIP_CREATED:
        return is_creator
    if ownership_filter == OWNERSHIP_OTHERS:
        return not is_creator
    return True


def _matches_search(skill: Dict[str, Any], search: Optional[str]) -> bool:
    """Match mine-tab search against skill display fields and tags."""
    keyword = (search or "").strip().lower()
    if not keyword:
        return True

    haystack = [
        skill.get("name"),
        skill.get("description"),
        skill.get("source"),
        skill.get("created_by"),
    ]
    haystack.extend(_as_list(skill.get("tags")))
    return any(keyword in str(value or "").lower() for value in haystack)


def _count_skills_by_ownership(skills: List[Dict[str, Any]], user_id: str) -> Dict[str, int]:
    """Count editable skills in each ownership bucket."""
    created = sum(
        1
        for skill in skills
        if str(skill.get("created_by")) == str(user_id)
    )
    others = len(skills) - created
    return {
        OWNERSHIP_ALL: len(skills),
        OWNERSHIP_CREATED: created,
        OWNERSHIP_OTHERS: others,
    }


def _paginate_mine_skills_with_optional_padding(
    filtered_skills: List[Dict[str, Any]],
    page: int,
    page_size: int,
    include_padding: bool,
) -> Tuple[List[Dict[str, Any]], int]:
    """Paginate mine skills with an optional create-skill placeholder at virtual index 0."""
    skill_count = len(filtered_skills)
    total = skill_count + 1 if include_padding else skill_count
    if total == 0:
        return [], 0

    offset = (page - 1) * page_size
    paged_entries: List[Dict[str, Any]] = []
    for slot in range(offset, min(offset + page_size, total)):
        if include_padding and slot == 0:
            paged_entries.append({"new_skill_padding": True})
        else:
            skill_index = slot - 1 if include_padding else slot
            paged_entries.append(filtered_skills[skill_index])
    return paged_entries, total


def _get_user_role(user_id: str) -> str:
    """Resolve user role from user_tenant_t; default to USER when unset."""
    user_tenant = get_user_tenant_by_user_id(user_id)
    if not user_tenant:
        return "USER"
    return str(user_tenant.get("user_role") or "USER")


def _can_publish_skill(
    *,
    skill: Dict[str, Any],
    user_id: str,
    user_role: str,
) -> bool:
    """Return whether the user may submit the skill to the repository."""
    if user_role == "ADMIN":
        return True
    return (
        user_role == "DEV"
        and str(skill.get("created_by")) == str(user_id)
    )


def _resolve_submitter_email(user_id: str) -> Optional[str]:
    """Resolve submitter email from user_tenant_t for pending_review listings."""
    user_tenant = get_user_tenant_by_user_id(user_id) or {}
    email = str(user_tenant.get("user_email") or "").strip()
    return email or None


def _validate_create_listing_permission(
    *,
    user_id: str,
    skill_info: Dict[str, Any],
) -> None:
    """Only ADMIN, or DEV who created the skill, may share to marketplace."""
    user_role = _get_user_role(user_id)
    if _can_publish_skill(
        skill=skill_info,
        user_id=user_id,
        user_role=user_role,
    ):
        return
    raise ForbiddenError(
        f"User role {user_role} not authorized to create repository listing"
    )


def _normalize_listing_tags(tags: Any) -> List[str]:
    """Trim, deduplicate, and validate marketplace listing tags."""
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise ValueError("tags must be a list of strings")

    normalized: List[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        if not isinstance(raw_tag, str):
            raise ValueError("tags must be a list of strings")
        tag = raw_tag.strip()
        if not tag:
            continue
        if len(tag) > _MAX_LISTING_TAG_LENGTH:
            raise ValueError(
                f"Each tag must be at most {_MAX_LISTING_TAG_LENGTH} characters"
            )
        if tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)

    if len(normalized) > _MAX_LISTING_TAGS:
        raise ValueError(f"tags must contain at most {_MAX_LISTING_TAGS} items")
    return normalized


def _validate_card_fields(repository_data: Dict[str, Any]) -> None:
    """Validate marketplace card fields required for listing submission."""
    icon = repository_data.get("icon") or "skill"
    if not icon or not isinstance(icon, str) or not icon.strip():
        raise ValueError("icon is required and must be a non-empty string")
    if len(icon.strip()) > _MAX_LISTING_ICON_LENGTH:
        raise ValueError(
            f"icon must be at most {_MAX_LISTING_ICON_LENGTH} characters"
        )
    repository_data["icon"] = icon.strip()

    category_id = repository_data.get("category_id")
    if category_id is not None and not isinstance(category_id, int):
        raise ValueError("category_id must be an integer")

    repository_data["tags"] = _normalize_listing_tags(repository_data.get("tags"))


def _build_skill_info_json(skill_info: Dict[str, Any]) -> Dict[str, Any]:
    """Build frozen metadata snapshot for a skill repository listing."""
    return {
        "skill_id": skill_info.get("skill_id"),
        "name": skill_info.get("name"),
        "description": skill_info.get("description"),
        "tags": skill_info.get("tags") or [],
        "content": skill_info.get("content") or "",
        "config_schemas": skill_info.get("config_schemas"),
        "config_values": skill_info.get("config_values"),
        "source": skill_info.get("source"),
        "group_ids": skill_info.get("group_ids") or [],
        "ingroup_permission": skill_info.get("ingroup_permission"),
        "tool_ids": skill_info.get("tool_ids") or [],
        "created_by": skill_info.get("created_by"),
    }


def _export_skill_zip_base64(
    *,
    skill_name: str,
    tenant_id: str,
) -> str:
    """Export a skill ZIP payload as base64 for frozen repository installation."""
    service = SkillService(tenant_id=tenant_id)
    exports = service.export_skills_by_names([skill_name], tenant_id=tenant_id)
    for item in exports:
        if item.get("skill_name") == skill_name and item.get("skill_zip_base64"):
            return item["skill_zip_base64"]
    raise ValueError(f"Failed to export skill ZIP for repository listing: {skill_name}")


def _build_repository_data_from_skill(
    skill_id: int,
    tenant_id: str,
    user_id: str,
    *,
    card_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a repository upsert payload from the current skill snapshot."""
    service = SkillService(tenant_id=tenant_id)
    skill_info = service.get_skill_by_id(skill_id, tenant_id=tenant_id)
    if not skill_info:
        raise ValueError("Skill not found")

    _validate_create_listing_permission(user_id=user_id, skill_info=skill_info)

    skill_name = str(skill_info.get("name") or "").strip()
    if not skill_name:
        raise ValueError("Skill name is required")

    repository_data: Dict[str, Any] = {
        "skill_id": skill_id,
        "name": skill_name,
        "description": skill_info.get("description"),
        "source": skill_info.get("source"),
        "submitted_by": _resolve_submitter_email(user_id),
        "icon": "skill",
        "tags": skill_info.get("tags") or [],
        "skill_info_json": _build_skill_info_json(skill_info),
        "skill_zip_base64": _export_skill_zip_base64(
            skill_name=skill_name,
            tenant_id=tenant_id,
        ),
        "status": STATUS_PENDING_REVIEW,
    }

    if card_fields:
        for key in ("icon", "downloads", "category_id", "content"):
            if key in card_fields and card_fields[key] is not None:
                repository_data[key] = card_fields[key]
        if "tags" in card_fields and card_fields["tags"] is not None:
            repository_data["tags"] = card_fields["tags"]

    repository_data["content"] = (card_fields or {}).get("content") or ""
    return repository_data


def _find_resubmittable_repository_record(
    skill_id: int,
    tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Find an existing review draft that can be refreshed by a new submission."""
    pending = get_skill_repository_by_skill_id(
        skill_id,
        publisher_tenant_id=tenant_id,
        statuses=[STATUS_PENDING_REVIEW],
    )
    if pending:
        return pending
    return get_skill_repository_by_skill_id(
        skill_id,
        publisher_tenant_id=tenant_id,
        statuses=[STATUS_REJECTED],
    )


def _reset_repository_peer_statuses(
    *,
    skill_repository_id: int,
    skill_id: int,
    status: str,
    publisher_tenant_id: str,
) -> None:
    """Reset peer listings with the same status; also clear rejected when submitting."""
    reset_skill_repository_status(
        repository_id=skill_repository_id,
        skill_id=skill_id,
        status=status,
        publisher_tenant_id=publisher_tenant_id,
    )
    if status == STATUS_PENDING_REVIEW:
        reset_skill_repository_status(
            repository_id=skill_repository_id,
            skill_id=skill_id,
            status=STATUS_REJECTED,
            publisher_tenant_id=publisher_tenant_id,
        )


def _validate_create_payload(repository_data: Dict[str, Any]) -> None:
    """Validate required fields before inserting a repository listing."""
    required_fields = (
        "skill_id",
        "name",
        "skill_info_json",
        "skill_zip_base64",
    )
    missing = [
        field for field in required_fields
        if field not in repository_data or repository_data[field] is None
    ]
    if missing:
        raise ValueError(f"Missing required repository fields: {', '.join(missing)}")
    if not repository_data.get("name"):
        raise ValueError("name must be a non-empty string")
    if not isinstance(repository_data.get("skill_info_json"), dict):
        raise ValueError("skill_info_json must be a JSON object")
    if not isinstance(repository_data.get("skill_zip_base64"), str):
        raise ValueError("skill_zip_base64 must be a string")

    _validate_card_fields(repository_data)


def create_skill_repository_listing_impl(
    skill_id: int,
    tenant_id: str,
    user_id: str,
    *,
    card_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create or update a repository listing from the current skill snapshot."""
    repository_data = _build_repository_data_from_skill(
        skill_id,
        tenant_id,
        user_id,
        card_fields=card_fields,
    )
    _validate_create_payload(repository_data)

    existing = _find_resubmittable_repository_record(
        skill_id,
        tenant_id,
    )
    if not existing:
        repository_id = insert_skill_repository_record(
            repository_data=repository_data,
            publisher_tenant_id=tenant_id,
            publisher_user_id=user_id,
        )
        is_updated = False
    else:
        repository_id = int(existing["skill_repository_id"])
        updates = {
            key: repository_data[key]
            for key in _UPDATE_SNAPSHOT_FIELDS
            if key in repository_data
        }
        affected = update_skill_repository_by_id(
            repository_id=repository_id,
            publisher_tenant_id=tenant_id,
            user_id=user_id,
            updates=updates,
        )
        if affected == 0:
            raise ValueError("Failed to update repository listing")
        is_updated = True

    _reset_repository_peer_statuses(
        skill_repository_id=repository_id,
        skill_id=skill_id,
        status=STATUS_PENDING_REVIEW,
        publisher_tenant_id=tenant_id,
    )

    record = get_skill_repository_by_id_and_publisher(
        repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError("Failed to load repository listing after write")
    create_repository_pending_review_notification(
        resource_type=RESOURCE_TYPE_SKILL_REPOSITORY,
        tenant_id=tenant_id,
        unique_id=repository_id,
        details={
            "name": record.get("name"),
            "skill_repository_id": repository_id,
            "skill_id": record.get("skill_id"),
            "content": record.get("content") or "",
        },
        created_by=user_id,
    )
    return _to_detail_item(record, is_updated=is_updated)


def _validate_su_status_transition(
    transition: Tuple[str, str],
    current_status: str,
    new_status: str,
) -> None:
    if transition not in _SU_STATUS_TRANSITIONS:
        raise ValueError(
            f"Invalid status transition from '{current_status}' to '{new_status}'"
        )


def _validate_publisher_status_transition(
    *,
    user_role: str,
    transition: Tuple[str, str],
    current_status: str,
    new_status: str,
    record: Dict[str, Any],
    user_id: str,
    tenant_id: str,
) -> Optional[Dict[str, str]]:
    if record.get("publisher_tenant_id") != tenant_id:
        raise ForbiddenError("Not authorized to update this repository listing")
    if user_role == "DEV" and record.get("publisher_user_id") != user_id:
        raise ForbiddenError("Not authorized to update this repository listing")
    if user_role == "ADMIN" and transition in _ADMIN_REVIEW_STATUS_TRANSITIONS:
        return None
    if transition not in _PUBLISHER_STATUS_TRANSITIONS:
        raise ValueError(
            f"Invalid status transition from '{current_status}' to '{new_status}'"
        )
    if transition in _PUBLISHER_RESUBMIT_TRANSITIONS:
        return {
            "publisher_tenant_id": tenant_id,
            "publisher_user_id": user_id,
        }
    return None


def _validate_repository_status_transition(
    *,
    user_role: str,
    current_status: str,
    new_status: str,
    record: Dict[str, Any],
    user_id: str,
    tenant_id: str,
) -> Optional[Dict[str, str]]:
    """Validate role, ownership, and allowed status transition."""
    transition = (current_status, new_status)

    if user_role == "SU":
        _validate_su_status_transition(transition, current_status, new_status)
        return None

    if user_role in ("ADMIN", "DEV"):
        return _validate_publisher_status_transition(
            user_role=user_role,
            transition=transition,
            current_status=current_status,
            new_status=new_status,
            record=record,
            user_id=user_id,
            tenant_id=tenant_id,
        )

    raise ForbiddenError(
        f"User role {user_role} not authorized to update repository status"
    )


def update_skill_repository_status_impl(
    *,
    skill_repository_id: int,
    status: str,
    user_id: str,
    tenant_id: str,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a skill repository listing status by primary key."""
    if status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )

    record = get_skill_repository_by_id_and_publisher(
        skill_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError(_REPOSITORY_LISTING_NOT_FOUND)

    current_status = record.get("status")
    publisher_updates: Optional[Dict[str, str]] = None
    submitted_by: Optional[str] = None
    if current_status != status:
        user_role = _get_user_role(user_id)
        publisher_updates = _validate_repository_status_transition(
            user_role=user_role,
            current_status=current_status,
            new_status=status,
            record=record,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        if status == STATUS_PENDING_REVIEW:
            submitted_by = _resolve_submitter_email(user_id)

    rows_affected = update_skill_repository_status_by_id(
        repository_id=skill_repository_id,
        status=status,
        user_id=user_id,
        filter_publisher_tenant_id=tenant_id,
        publisher_tenant_id=(
            publisher_updates["publisher_tenant_id"]
            if publisher_updates
            else None
        ),
        publisher_user_id=(
            publisher_updates["publisher_user_id"]
            if publisher_updates
            else None
        ),
        submitted_by=submitted_by,
        content=content,
    )
    if rows_affected == 0:
        raise ValueError(_REPOSITORY_LISTING_NOT_FOUND)

    _reset_repository_peer_statuses(
        skill_repository_id=skill_repository_id,
        skill_id=record["skill_id"],
        status=status,
        publisher_tenant_id=tenant_id,
    )

    updated = get_skill_repository_by_id_and_publisher(
        skill_repository_id,
        tenant_id,
    )
    if not updated:
        raise ValueError("Failed to load repository listing after update")

    _handle_review_status_notifications(
        current_status=current_status,
        new_status=status,
        updated=updated,
        skill_repository_id=skill_repository_id,
        user_id=user_id,
        content=content,
    )

    return _to_summary_item(updated)


def _handle_review_status_notifications(
    *,
    current_status: str,
    new_status: str,
    updated: Dict[str, Any],
    skill_repository_id: int,
    user_id: str,
    content: Optional[str] = None,
) -> None:
    """Send review-result notification and deactivate pending-review notification."""
    if current_status != new_status and new_status in (STATUS_SHARED, STATUS_REJECTED):
        details: Dict[str, Any] = {
            "name": updated.get("name"),
            "skill_repository_id": skill_repository_id,
            "skill_id": updated.get("skill_id"),
        }
        if content:
            details["content"] = content
        create_repository_review_notification(
            resource_type=RESOURCE_TYPE_SKILL_REPOSITORY,
            review_status=new_status,
            receiver_user_id=updated["publisher_user_id"],
            details=details,
            tenant_id=updated.get("publisher_tenant_id"),
            unique_id=skill_repository_id,
            created_by=user_id,
        )

    if current_status == STATUS_PENDING_REVIEW:
        deactivate_notifications(
            event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
            resource_type=RESOURCE_TYPE_SKILL_REPOSITORY,
            unique_id=skill_repository_id,
            updated_by=user_id,
        )


def _extract_duplicate_skill_name(error_message: str) -> Optional[str]:
    """Extract duplicate skill name from existing SkillException messages."""
    match = re.search(r"Skill '([^']+)' already exists", error_message)
    if match:
        return match.group(1)
    return None


def _truncate_copy_base_name(base_name: str, suffix: str) -> str:
    """Trim a copied skill base name so the final name fits the database limit."""
    max_base_length = max(_MAX_COPY_NAME_LENGTH - len(suffix), 1)
    if len(base_name) <= max_base_length:
        return base_name
    return base_name[:max_base_length].rstrip() or base_name[:max_base_length]


def _generate_available_copy_skill_name(
    *,
    base_name: str,
    tenant_id: str,
) -> str:
    """Generate an available skill name for repository copy within the tenant."""
    normalized_base = (base_name or "Skill").strip() or "Skill"
    if not get_skill_by_name(normalized_base, tenant_id):
        return normalized_base

    index = 1
    while True:
        suffix = " 副本" if index == 1 else f" 副本 {index}"
        candidate = f"{_truncate_copy_base_name(normalized_base, suffix)}{suffix}"
        if not get_skill_by_name(candidate, tenant_id):
            return candidate
        index += 1


def install_skill_from_repository_impl(
    *,
    skill_repository_id: int,
    tenant_id: str,
    user_id: str,
    target_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Install a shared skill repository listing into the current tenant."""
    record = get_skill_repository_by_id_and_publisher(
        skill_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError(_REPOSITORY_LISTING_NOT_FOUND)
    if record.get("status") != STATUS_SHARED:
        raise ValueError("Repository listing is not available for install")

    skill_zip_base64 = record.get("skill_zip_base64")
    if not isinstance(skill_zip_base64, str) or not skill_zip_base64.strip():
        raise ValueError("Repository listing has no skill ZIP payload")

    try:
        zip_bytes = base64.b64decode(skill_zip_base64, validate=True)
    except Exception as exc:
        raise ValueError("Repository listing has invalid skill ZIP payload") from exc

    copy_skill_name = str(target_name or "").strip()
    if not copy_skill_name:
        copy_skill_name = _generate_available_copy_skill_name(
            base_name=str(record.get("name") or "").strip(),
            tenant_id=tenant_id,
        )
    if not copy_skill_name:
        raise ValueError("Skill name is required")

    try:
        created_skill = SkillService(tenant_id=tenant_id).create_skill_from_zip_bytes(
            zip_bytes=zip_bytes,
            skill_name=copy_skill_name,
            source="repository",
            user_id=user_id,
            tenant_id=tenant_id,
            ingroup_permission=PERMISSION_READ,
        )
    except SkillException as exc:
        message = str(exc)
        if "already exists" in message.lower():
            duplicate_name = _extract_duplicate_skill_name(message) or copy_skill_name
            raise SkillDuplicateError([duplicate_name]) from exc
        raise

    affected = increment_skill_repository_downloads(
        repository_id=skill_repository_id,
        user_id=user_id,
    )
    if affected == 0:
        logger.warning(
            "Failed to increment skill repository downloads after install "
            "(skill_repository_id=%s)",
            skill_repository_id,
        )

    return {
        "skill_id": created_skill.get("skill_id"),
        "name": created_skill.get("name"),
        "description": created_skill.get("description"),
        "source": created_skill.get("source"),
        "tags": created_skill.get("tags") or [],
    }


def _list_repository_info_by_skill_id(
    paged_skills: List[Dict[str, Any]],
    tenant_id: str,
) -> Dict[int, List[Dict[str, Any]]]:
    skill_ids = [
        int(skill["skill_id"])
        for skill in paged_skills
        if skill.get("skill_id") is not None
    ]
    if not skill_ids:
        return {}

    repository_by_skill_id: Dict[int, List[Dict[str, Any]]] = {}
    repository_records = list_skill_repository_by_skill_ids(
        skill_ids,
        statuses=_MY_SKILL_REPOSITORY_STATUSES,
        publisher_tenant_id=tenant_id,
    )
    for record in repository_records:
        skill_id = record.get("skill_id")
        if skill_id is None:
            continue
        repository_by_skill_id.setdefault(int(skill_id), []).append(
            _to_repository_info_item(record)
        )
    return repository_by_skill_id


def _to_mine_skill_item(
    skill: Dict[str, Any],
    *,
    user_id: str,
    user_role: str,
    repository_by_skill_id: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if skill.get("new_skill_padding"):
        return {"new_skill_padding": True}

    skill_id = skill.get("skill_id")
    repository_info = (
        repository_by_skill_id.get(int(skill_id), [])
        if skill_id is not None
        else []
    )
    return {
        "skill_id": skill_id,
        "name": skill.get("name"),
        "description": skill.get("description"),
        "source": skill.get("source"),
        "tags": skill.get("tags") or [],
        "group_ids": skill.get("group_ids") or [],
        "ingroup_permission": skill.get("ingroup_permission"),
        "created_by": skill.get("created_by"),
        "created_at": skill.get("create_time"),
        "updated_at": skill.get("update_time"),
        "permission": skill.get("permission"),
        "can_publish": _can_publish_skill(
            skill=skill,
            user_id=user_id,
            user_role=user_role,
        ),
        "repository_info": repository_info,
    }


def list_my_editable_skills_impl(
    tenant_id: str,
    user_id: str,
    ownership: str = OWNERSHIP_ALL,
    *,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    new_skill_padding: bool = False,
) -> Dict[str, Any]:
    """List editable skills for the current user with repository listing info."""
    normalized_ownership = (ownership or OWNERSHIP_ALL).strip().lower()
    if normalized_ownership not in VALID_OWNERSHIP_FILTERS:
        raise ValueError(
            f"Invalid ownership filter: {ownership}. "
            f"Allowed values: {', '.join(sorted(VALID_OWNERSHIP_FILTERS))}."
        )

    safe_page = max(int(page or 1), 1)
    safe_page_size = max(int(page_size or 10), 1)

    user_role = _get_user_role(user_id)
    skills = SkillService(tenant_id=tenant_id).list_visible_skills(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    counts = _count_skills_by_ownership(skills, user_id)

    filtered_skills = [
        skill for skill in skills
        if _matches_ownership(skill, user_id, normalized_ownership)
        and _matches_search(skill, search)
    ]
    include_padding = (
        new_skill_padding
        and normalized_ownership == OWNERSHIP_ALL
        and not (search and search.strip())
    )
    paged_skills, total = _paginate_mine_skills_with_optional_padding(
        filtered_skills,
        page=safe_page,
        page_size=safe_page_size,
        include_padding=include_padding,
    )

    repository_by_skill_id = _list_repository_info_by_skill_id(
        paged_skills,
        tenant_id,
    )
    items = [
        _to_mine_skill_item(
            skill,
            user_id=user_id,
            user_role=user_role,
            repository_by_skill_id=repository_by_skill_id,
        )
        for skill in paged_skills
    ]

    return {
        "items": items,
        "counts": counts,
        "pagination": {
            "page": safe_page,
            "page_size": safe_page_size,
            "total": total,
            "total_pages": math.ceil(total / safe_page_size) if total else 0,
        },
    }


def list_skill_repository_listings_impl(
    tenant_id: str,
    *,
    user_id: str,
    status: Optional[str] = None,
    skill_id: Optional[int] = None,
    category_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    sort_by_update_time: bool = False,
) -> Dict[str, Any]:
    """List skill repository listings for the caller tenant with optional filters."""
    if status is not None and status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )

    result = list_skill_repository_summaries(
        publisher_tenant_id=tenant_id,
        status=status,
        skill_id=skill_id,
        category_id=category_id,
        page=page,
        page_size=page_size,
        search=search,
        sort_by_update_time=sort_by_update_time,
    )
    user_role = _get_user_role(user_id)
    return {
        "items": [
            _to_summary_item(
                record,
                can_take_down=(
                    record.get("status") == STATUS_SHARED
                    and (
                        user_role in ("ADMIN", "SU")
                        or (
                            user_role == "DEV"
                            and str(record.get("publisher_user_id")) == str(user_id)
                        )
                    )
                ),
            )
            for record in result.get("items", [])
        ],
        "pagination": result.get("pagination"),
    }


def get_skill_repository_listing_detail_impl(
    skill_repository_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Load a skill repository listing and return a frozen detail payload for the UI."""
    record = get_skill_repository_by_id_and_publisher(
        skill_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError(_REPOSITORY_LISTING_NOT_FOUND)

    return _to_detail_item(record)
