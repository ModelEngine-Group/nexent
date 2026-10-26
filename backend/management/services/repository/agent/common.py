# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from typing import FrozenSet, Tuple

from contracts.constants.constants import STATUS_NOT_SHARED, STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED

logger = logging.getLogger("agent_repository_service")

_SU_STATUS_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
    {
        (STATUS_PENDING_REVIEW, STATUS_REJECTED),
        (STATUS_PENDING_REVIEW, STATUS_SHARED),
        (STATUS_SHARED, STATUS_NOT_SHARED),
    }
)

_PUBLISHER_STATUS_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
    {
        (STATUS_NOT_SHARED, STATUS_PENDING_REVIEW),
        (STATUS_REJECTED, STATUS_PENDING_REVIEW),
        (STATUS_PENDING_REVIEW, STATUS_NOT_SHARED),
        (STATUS_REJECTED, STATUS_NOT_SHARED),
        (STATUS_SHARED, STATUS_NOT_SHARED),
    }
)

_PUBLISHER_RESUBMIT_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
    {
        (STATUS_NOT_SHARED, STATUS_PENDING_REVIEW),
        (STATUS_REJECTED, STATUS_PENDING_REVIEW),
    }
)

_ADMIN_REVIEW_STATUS_TRANSITIONS: FrozenSet[Tuple[str, str]] = frozenset(
    {(STATUS_PENDING_REVIEW, STATUS_REJECTED), (STATUS_PENDING_REVIEW, STATUS_SHARED)}
)

_MAX_LISTING_TAGS = 5

_MAX_LISTING_TAG_LENGTH = 20

_MAX_LISTING_ICON_LENGTH = 1024

_MY_AGENT_REPOSITORY_STATUSES = frozenset(
    {STATUS_SHARED, STATUS_PENDING_REVIEW, STATUS_REJECTED}
)

import uuid


def _repository_icon_url(agent_id: int, version_no: int, image_id: str) -> str:
    return f"/api/repository/agent/{agent_id}/versions/{version_no}/icon/{image_id}"


def _repository_icon_object_name(
    tenant_id: str, agent_id: int, version_no: int, image_id: str
) -> str:
    return f"agent-repository-icons/{tenant_id}/{agent_id}/{version_no}/{image_id}"


def _repository_image_id(icon_url: str, agent_id: int, version_no: int) -> str:
    prefix = f"/api/repository/agent/{agent_id}/versions/{version_no}/icon/"
    if not icon_url.startswith(prefix):
        raise ValueError("Invalid repository icon URL")
    image_id = icon_url[len(prefix) :]
    try:
        if str(uuid.UUID(image_id)) != image_id:
            raise ValueError("Invalid repository icon URL")
    except ValueError as exc:
        raise ValueError("Invalid repository icon URL") from exc
    return image_id


from typing import Any, Dict

from contracts.errors.exceptions import UnauthorizedError
from management.db.identity.user_tenant import get_user_tenant_by_user_id


def _get_user_role(user_id: str) -> str:
    """Resolve user role from user_tenant_t; default to USER when unset."""
    user_tenant = get_user_tenant_by_user_id(user_id)
    if not user_tenant:
        return "USER"
    return str(user_tenant.get("user_role") or "USER")


def _validate_create_listing_permission(
    *,
    user_id: str,
    agent_info: Dict[str, Any],
) -> None:
    """Only ADMIN, or DEV who created the agent, may share to marketplace."""
    user_role = _get_user_role(user_id)
    if user_role == "ADMIN":
        return
    if user_role == "DEV":
        agent_created_by = agent_info.get("created_by")
        if agent_created_by is not None and str(agent_created_by) == str(user_id):
            return
        raise UnauthorizedError("Not authorized to create repository listing")
    raise UnauthorizedError(
        f"User role {user_role} not authorized to create repository listing"
    )


from typing import Any, Dict, List, Optional

from contracts.constants.constants import STATUS_PENDING_REVIEW, STATUS_REJECTED
from contracts.constants.constants import SYSTEM_TENANT_ID
from management.db.agent.catalog import reset_agent_repository_status
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.services.permission.identity.display import repository_identity_fields


def _to_summary_item(
    record: Dict[str, Any],
    *,
    download_total: Optional[int] = None,
) -> Dict[str, Any]:
    """Map a DB record to a lightweight marketplace summary item."""
    agent_id = record.get("agent_id")
    downloads = (
        download_total if download_total is not None else record.get("downloads") or 0
    )
    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": agent_id,
        "author": record.get("author"),
        **repository_identity_fields(record),
        "submitted_by": record.get("submitted_by"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "status": record.get("status"),
        "tags": record.get("tags") or [],
        "tool_count": record.get("tool_count") or 0,
        "version_label": record.get("version_name"),
        "version_no": record.get("version_no"),
        "create_time": _serialize_created_at(record.get("create_time")),
        "icon_url": record.get("icon_url"),
        "downloads": downloads,
        "content": record.get("content"),
        "publisher_tenant_id": record.get("publisher_tenant_id"),
        "is_official": record.get("publisher_tenant_id") == SYSTEM_TENANT_ID,
        "is_main_agent": record.get("is_main_agent", True),
    }


def _normalize_listing_tags(tags: Any) -> List[str]:
    """Trim, deduplicate, and validate optional marketplace listing tags."""
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
    """Validate marketplace card fields for listing submission.

    Tags are optional: a listing may be submitted without any tag. When tags
    are provided they are normalized and bounded by the listing limits.
    """
    icon_url = repository_data.get("icon_url")
    if icon_url is not None and (
        not isinstance(icon_url, str)
        or not icon_url.strip()
        or len(icon_url) > _MAX_LISTING_ICON_LENGTH
    ):
        raise ValueError(
            f"icon_url must be a non-empty URL up to {_MAX_LISTING_ICON_LENGTH} characters"
        )

    tags = repository_data.get("tags")
    repository_data["tags"] = _normalize_listing_tags([] if tags is None else tags)


def _reset_repository_peer_statuses(
    *,
    agent_repository_id: int,
    agent_id: int,
    status: str,
    publisher_tenant_id: str,
) -> None:
    """Reset peer listings with the same status; also clear rejected when submitting."""
    reset_agent_repository_status(
        agent_repository_id=agent_repository_id,
        agent_id=agent_id,
        status=status,
        publisher_tenant_id=publisher_tenant_id,
    )
    if status == STATUS_PENDING_REVIEW:
        reset_agent_repository_status(
            agent_repository_id=agent_repository_id,
            agent_id=agent_id,
            status=STATUS_REJECTED,
            publisher_tenant_id=publisher_tenant_id,
        )


def _resolve_submitter_email(user_id: str) -> Optional[str]:
    """Resolve submitter email from user_tenant_t for pending_review listings."""
    user_tenant = get_user_tenant_by_user_id(user_id) or {}
    email = str(user_tenant.get("user_email") or "").strip()
    return email or None


def _count_tools_in_snapshot(agent_info_json: Any) -> int:
    """Count tools across all agents in a frozen repository snapshot."""
    if not isinstance(agent_info_json, dict):
        return 0
    agent_info_map = agent_info_json.get("agent_info")
    if not isinstance(agent_info_map, dict):
        return 0

    total = 0
    for agent in agent_info_map.values():
        if not isinstance(agent, dict):
            continue
        tools = agent.get("tools")
        if isinstance(tools, list):
            total += len(tools)
    return total


def _serialize_created_at(create_time: Any) -> Optional[str]:
    """Serialize DB create_time to an ISO string for API consumers."""
    if create_time is None:
        return None
    if hasattr(create_time, "isoformat"):
        return create_time.isoformat()
    return str(create_time)
