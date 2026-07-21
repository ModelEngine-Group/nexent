import logging
from typing import Any, Collection, Dict, FrozenSet, List, Optional, Tuple

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
from consts.exceptions import UnauthorizedError
from consts.model import AgentRepositorySnapshot
from consts.notification import EVENT_TYPE_REPOSITORY_REVIEW_PENDING, RESOURCE_TYPE_AGENT_REPOSITORY
from database.agent_db import search_agent_info_by_agent_id
from database.agent_version_db import search_version_by_version_no
from database.agent_repository_db import (
    fetch_draft_agent_mine_metadata,
    get_agent_repository_by_agent_id,
    get_agent_repository_by_id,
    increment_agent_repository_downloads,
    insert_agent_repository_record,
    list_agent_repository_by_agent_ids,
    list_agent_repository_summaries,
    reset_agent_repository_status,
    sum_agent_repository_downloads_by_agent_ids,
    update_agent_repository_by_id,
    update_agent_repository_status_by_id,
)
from database.user_tenant_db import get_user_tenant_by_user_id
from services.agent_service import (
    collect_skill_zip_entries,
    export_agent_dict_for_repository_impl,
    import_agent_impl,
    import_agent_with_skills_impl,
    list_all_agent_info_impl,
)
from services.notification_service import (
    create_repository_pending_review_notification,
    create_repository_review_notification,
    deactivate_notifications,
)
from services.repository_import_precheck import build_repository_import_precheck

logger = logging.getLogger("agent_repository_service")

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


def _to_summary_item(
    record: Dict[str, Any],
    *,
    download_total: Optional[int] = None,
) -> Dict[str, Any]:
    """Map a DB record to a lightweight marketplace summary item."""
    agent_id = record.get("agent_id")
    downloads = (
        download_total
        if download_total is not None
        else record.get("downloads") or 0
    )
    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": agent_id,
        "author": record.get("author"),
        "submitted_by": record.get("submitted_by"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "status": record.get("status"),
        "tags": record.get("tags") or [],
        "tool_count": record.get("tool_count") or 0,
        "version_label": record.get("version_name"),
        "icon": record.get("icon"),
        "downloads": downloads,
        "content": record.get("content"),
    }


def _get_agent_download_totals(agent_ids: Collection[int]) -> Dict[int, int]:
    """Return total downloads summed across all repository rows per agent_id."""
    normalized_ids = {
        int(agent_id)
        for agent_id in agent_ids
        if agent_id is not None
    }
    if not normalized_ids:
        return {}
    return sum_agent_repository_downloads_by_agent_ids(list(normalized_ids))


def _matches_repository_listing_search_filter(record: dict, search: str) -> bool:
    """Return whether a listing matches a case-insensitive marketplace search."""
    query = search.strip().lower()
    if not query:
        return True
    name = str(record.get("display_name") or record.get("name") or "").lower()
    description = str(record.get("description") or "").lower()
    tags = record.get("tags") or []
    tag_text = " ".join(str(tag).lower() for tag in tags if isinstance(tag, str))
    return (
        query in name
        or query in description
        or query in tag_text
    )


def list_agent_repository_listings_impl(
    tenant_id: str,
    *,
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """List repository listings for the caller tenant with optional status filter."""
    if status is not None and status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )
    records = list_agent_repository_summaries(
        publisher_tenant_id=tenant_id,
        status=status,
        agent_id=agent_id,
    )
    if search and search.strip():
        records = [
            record
            for record in records
            if _matches_repository_listing_search_filter(record, search)
        ]
    total = len(records)
    start = (page - 1) * page_size
    paged_records = records[start: start + page_size]
    paged_agent_ids = [
        int(record["agent_id"])
        for record in paged_records
        if record.get("agent_id") is not None
    ]
    download_totals = _get_agent_download_totals(paged_agent_ids)
    return {
        "items": [
            _to_summary_item(
                record,
                download_total=download_totals.get(int(record["agent_id"]), 0)
                if record.get("agent_id") is not None
                else 0,
            )
            for record in paged_records
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        },
    }


def _normalize_listing_tags(tags: Any) -> List[str]:
    """Trim, deduplicate, and validate marketplace listing tags."""
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

    if not normalized:
        raise ValueError("tags must contain at least one non-empty tag")
    if len(normalized) > _MAX_LISTING_TAGS:
        raise ValueError(f"tags must contain at most {_MAX_LISTING_TAGS} items")
    return normalized


def _validate_card_fields(repository_data: Dict[str, Any]) -> None:
    """Validate marketplace card fields required for listing submission."""
    icon = repository_data.get("icon")
    if not icon or not isinstance(icon, str) or not icon.strip():
        raise ValueError("icon is required and must be a non-empty string")
    if len(icon.strip()) > _MAX_LISTING_ICON_LENGTH:
        raise ValueError(
            f"icon must be at most {_MAX_LISTING_ICON_LENGTH} characters"
        )

    tags = repository_data.get("tags")
    if tags is None:
        raise ValueError("tags is required for marketplace listing submission")
    repository_data["tags"] = _normalize_listing_tags(tags)


_MY_AGENT_REPOSITORY_STATUSES = frozenset({
    STATUS_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
})


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


def _to_repository_info_item(record: Dict[str, Any]) -> Dict[str, Any]:
    """Map a repository DB row to a my-agents repository_info entry."""
    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "status": record.get("status"),
        "version_no": record.get("version_no"),
        "version_label": record.get("version_name"),
        "create_time": _serialize_created_at(record.get("create_time")),
        "content": record.get("content"),
    }


def _matches_mine_ownership_filter(
    created_by: Any,
    user_id: str,
    ownership_filter: str,
) -> bool:
    """Return whether an agent matches the mine-tab ownership filter."""
    if ownership_filter == OWNERSHIP_ALL:
        return True
    is_creator = str(created_by) == str(user_id)
    if ownership_filter == OWNERSHIP_CREATED:
        return is_creator
    if ownership_filter == OWNERSHIP_OTHERS:
        return not is_creator
    return True


def _compute_mine_ownership_counts(
    agents: List[dict],
    meta_by_id: Dict[int, dict],
    user_id: str,
) -> Dict[str, int]:
    """Count visible draft agents grouped by ownership for mine-tab badges."""
    created = 0
    for agent in agents:
        agent_id = agent.get("agent_id")
        if agent_id is None:
            continue
        meta = meta_by_id.get(int(agent_id), {})
        if str(meta.get("created_by")) == str(user_id):
            created += 1
    total = len(agents)
    return {
        "all": total,
        "created": created,
        "others": total - created,
    }


def _matches_mine_search_filter(agent: dict, search: str) -> bool:
    """Return whether an agent matches a case-insensitive name/description search."""
    query = search.strip().lower()
    if not query:
        return True
    name = str(agent.get("display_name") or agent.get("name") or "").lower()
    description = str(agent.get("description") or "").lower()
    return query in name or query in description


def _paginate_mine_agents_with_optional_padding(
    filtered_agents: List[tuple],
    page: int,
    page_size: int,
    include_padding: bool,
) -> tuple[List[Any], int]:
    """Paginate mine agents with an optional create-agent placeholder at virtual index 0."""
    agent_count = len(filtered_agents)
    total = agent_count + 1 if include_padding else agent_count
    if total == 0:
        return [], 0

    offset = (page - 1) * page_size
    paged_entries: List[Any] = []
    for slot in range(offset, min(offset + page_size, total)):
        if include_padding and slot == 0:
            paged_entries.append({"new_agent_padding": True})
        else:
            agent_index = slot - 1 if include_padding else slot
            paged_entries.append(filtered_agents[agent_index])
    return paged_entries, total


async def list_my_editable_agents_impl(
    tenant_id: str,
    user_id: str,
    ownership: str = OWNERSHIP_ALL,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    new_agent_padding: bool = False,
    agent_id: Optional[int] = None,
) -> Dict[str, Any]:
    """List visible draft agents for the current user with repository listing info."""
    normalized_ownership = (ownership or OWNERSHIP_ALL).strip().lower()
    if normalized_ownership not in VALID_OWNERSHIP_FILTERS:
        raise ValueError(
            f"Invalid ownership filter: {ownership}. "
            f"Allowed values: {', '.join(sorted(VALID_OWNERSHIP_FILTERS))}."
        )

    all_agents = await list_all_agent_info_impl(tenant_id=tenant_id, user_id=user_id)
    agent_ids = [
        int(agent["agent_id"])
        for agent in all_agents
        if agent.get("agent_id") is not None
    ]
    meta_by_id = fetch_draft_agent_mine_metadata(tenant_id, agent_ids)
    counts = _compute_mine_ownership_counts(all_agents, meta_by_id, user_id)

    filtered_agents = []
    for agent in all_agents:
        current_agent_id = agent.get("agent_id")
        if current_agent_id is None:
            continue
        meta = meta_by_id.get(int(current_agent_id), {})
        if not _matches_mine_ownership_filter(
            meta.get("created_by"),
            user_id,
            normalized_ownership,
        ):
            continue
        filtered_agents.append((agent, meta))

    if search and search.strip():
        filtered_agents = [
            (agent, meta)
            for agent, meta in filtered_agents
            if _matches_mine_search_filter(agent, search)
        ]

    if agent_id is not None:
        filtered_agents = [
            (agent, meta)
            for agent, meta in filtered_agents
            if agent.get("agent_id") is not None and int(agent["agent_id"]) == agent_id
        ]

    include_padding = (
        new_agent_padding
        and normalized_ownership == OWNERSHIP_ALL
        and not (search and search.strip())
        and agent_id is None
    )
    paged_entries, total = _paginate_mine_agents_with_optional_padding(
        filtered_agents,
        page=page,
        page_size=page_size,
        include_padding=include_padding,
    )
    paged_agent_ids = [
        int(entry[0]["agent_id"])
        for entry in paged_entries
        if not (isinstance(entry, dict) and entry.get("new_agent_padding"))
    ]

    repository_by_agent_id: Dict[int, List[Dict[str, Any]]] = {}
    if paged_agent_ids:
        repository_records = list_agent_repository_by_agent_ids(
            paged_agent_ids,
            statuses=_MY_AGENT_REPOSITORY_STATUSES,
            publisher_tenant_id=tenant_id,
        )
        for record in repository_records:
            record_agent_id = record.get("agent_id")
            if record_agent_id is None:
                continue
            repository_by_agent_id.setdefault(int(record_agent_id), []).append(
                _to_repository_info_item(record)
            )

    download_totals = _get_agent_download_totals(paged_agent_ids)

    items: List[Dict[str, Any]] = []
    for entry in paged_entries:
        if isinstance(entry, dict) and entry.get("new_agent_padding"):
            items.append({"new_agent_padding": True})
            continue
        agent, meta = entry
        entry_agent_id = int(agent["agent_id"])
        items.append(
            {
                "agent_id": agent.get("agent_id"),
                "name": agent.get("display_name") or agent.get("name"),
                "description": agent.get("description"),
                "current_version_no": meta.get("current_version_no"),
                "version_label": meta.get("version_name"),
                "version_create_time": _serialize_created_at(
                    meta.get("version_create_time")
                ),
                "permission": agent.get("permission"),
                "downloads": download_totals.get(entry_agent_id, 0),
                "repository_info": repository_by_agent_id.get(entry_agent_id, []),
            }
        )

    return {
        "items": items,
        "counts": counts,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        },
    }


def _resolve_submitter_email(user_id: str) -> Optional[str]:
    """Resolve submitter email from user_tenant_t for pending_review listings."""
    user_tenant = get_user_tenant_by_user_id(user_id) or {}
    email = str(user_tenant.get("user_email") or "").strip()
    return email or None


def _extract_root_agent_from_snapshot(agent_info_json: Any) -> Dict[str, Any]:
    """Resolve the root agent entry from a frozen repository snapshot."""
    if not isinstance(agent_info_json, dict):
        return {}
    root_agent_id = agent_info_json.get("agent_id")
    agent_info_map = agent_info_json.get("agent_info")
    if root_agent_id is None or not isinstance(agent_info_map, dict):
        return {}
    return (
        agent_info_map.get(str(root_agent_id))
        or agent_info_map.get(root_agent_id)
        or {}
    )


def _extract_tool_names(root_agent: Dict[str, Any]) -> List[str]:
    """Collect display tool names from a root agent snapshot entry."""
    tools: List[str] = []
    for tool in root_agent.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("origin_name") or tool.get("name")
        if name:
            tools.append(str(name))
    return tools


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


def get_agent_repository_listing_detail_impl(
    agent_repository_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Load a repository listing and return a detail payload for the UI."""
    record = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError("Repository listing not found")

    root_agent = _extract_root_agent_from_snapshot(record.get("agent_info_json"))
    agent_id = record.get("agent_id")
    download_total = 0
    if agent_id is not None:
        download_total = _get_agent_download_totals([int(agent_id)]).get(
            int(agent_id),
            0,
        )

    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": agent_id,
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "author": record.get("author"),
        "submitted_by": record.get("submitted_by"),
        "icon": record.get("icon"),
        "status": record.get("status"),
        "version_label": record.get("version_name"),
        "downloads": download_total,
        "created_at": _serialize_created_at(record.get("create_time")),
        "model_name": root_agent.get("model_name"),
        "duty_prompt": root_agent.get("duty_prompt"),
        "tools": _extract_tool_names(root_agent),
    }


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


def _validate_repository_status_transition(
    *,
    user_role: str,
    current_status: str,
    new_status: str,
    record: Dict[str, Any],
    user_id: str,
    tenant_id: str,
) -> Optional[Dict[str, str]]:
    """Validate role, ownership, and allowed status transition.

    Returns publisher fields to update when not_shared -> pending_review,
    otherwise None.
    """
    transition = (current_status, new_status)

    if user_role == "SU":
        if transition not in _SU_STATUS_TRANSITIONS:
            raise ValueError(
                f"Invalid status transition from '{current_status}' to '{new_status}'"
            )
        return None

    if user_role in ("ADMIN", "DEV"):
        if record.get("publisher_tenant_id") != tenant_id:
            raise UnauthorizedError(
                "Not authorized to update this repository listing"
            )
        if user_role == "DEV" and record.get("publisher_user_id") != user_id:
            raise UnauthorizedError(
                "Not authorized to update this repository listing"
            )
        if (
            user_role == "ADMIN"
            and transition in _ADMIN_REVIEW_STATUS_TRANSITIONS
        ):
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

    raise UnauthorizedError(
        f"User role {user_role} not authorized to update repository status"
    )


def update_agent_repository_status_impl(
    *,
    agent_repository_id: int,
    status: str,
    user_id: str,
    tenant_id: str,
    notify_content: Optional[str] = None,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a repository listing status by primary key."""
    if status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )

    record = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError("Repository listing not found")

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

    rows_affected = update_agent_repository_status_by_id(
        repository_id=agent_repository_id,
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
        raise ValueError("Repository listing not found")

    _reset_repository_peer_statuses(
        agent_repository_id=agent_repository_id,
        agent_id=record["agent_id"],
        status=status,
        publisher_tenant_id=tenant_id,
    )

    updated = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not updated:
        raise ValueError("Failed to load repository listing after update")

    _handle_review_status_notifications(
        current_status=current_status,
        new_status=status,
        updated=updated,
        agent_repository_id=agent_repository_id,
        user_id=user_id,
        content=content,
        notify_content=notify_content,
    )

    return _to_summary_item(updated)


def _handle_review_status_notifications(
    *,
    current_status: str,
    new_status: str,
    updated: Dict[str, Any],
    agent_repository_id: int,
    user_id: str,
    content: Optional[str] = None,
    notify_content: Optional[str] = None,
) -> None:
    """Send review-result notification and deactivate pending-review notification."""
    if current_status != new_status and new_status in (STATUS_SHARED, STATUS_REJECTED):
        details: Dict[str, Any] = {
            "name": updated.get("display_name") or updated.get("name"),
            "agent_repository_id": agent_repository_id,
            "agent_id": updated.get("agent_id"),
        }
        review_reason = content or notify_content
        if review_reason:
            details["reason"] = review_reason
        create_repository_review_notification(
            resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
            review_status=new_status,
            receiver_user_id=updated["publisher_user_id"],
            details=details,
            tenant_id=updated.get("publisher_tenant_id"),
            unique_id=agent_repository_id,
            created_by=user_id,
        )

    if current_status == STATUS_PENDING_REVIEW:
        deactivate_notifications(
            event_type=EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
            resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
            unique_id=agent_repository_id,
            updated_by=user_id,
        )


def _to_list_item(record: Dict[str, Any]) -> Dict[str, Any]:
    """Map a DB record to a marketplace list item (without heavy JSON blobs)."""
    return {
        "id": record.get("agent_repository_id"),
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": record.get("agent_id"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "author": record.get("author"),
        "submitted_by": record.get("submitted_by"),
        "tags": record.get("tags") or [],
        "tool_count": record.get("tool_count"),
        "version_label": record.get("version_name"),
        "icon": record.get("icon"),
        "downloads": record.get("downloads") or 0,
        "status": record.get("status"),
        "version_no": record.get("version_no"),
        "publisher_tenant_id": record.get("publisher_tenant_id"),
        "created_at": record.get("create_time"),
        "updated_at": record.get("update_time"),
        "content": record.get("content"),
    }


def _to_detail_item(
    record: Dict[str, Any],
    *,
    include_bundles: bool = True,
    is_updated: Optional[bool] = None,
) -> Dict[str, Any]:
    """Map a DB record to a marketplace detail payload."""
    detail = _to_list_item(record)
    if include_bundles:
        detail["agent_info_json"] = record.get("agent_info_json")
    if is_updated is not None:
        detail["is_updated"] = is_updated
    return detail


def _validate_create_payload(repository_data: Dict[str, Any]) -> None:
    """Validate required fields before inserting a repository listing."""
    required_fields = (
        "agent_id",
        "version_no",
        "name",
        "agent_info_json",
    )
    missing = [
        field for field in required_fields
        if field not in repository_data or repository_data[field] is None
    ]
    if missing:
        raise ValueError(f"Missing required repository fields: {', '.join(missing)}")
    if not repository_data.get("name"):
        raise ValueError("name must be a non-empty string")

    agent_info_json = repository_data.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("agent_info_json must be a JSON object")
    for key in ("agent_id", "agent_info", "mcp_info"):
        if key not in agent_info_json:
            raise ValueError(f"agent_info_json must contain '{key}'")

    _validate_card_fields(repository_data)


async def _build_agent_info_json(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
) -> dict:
    """Build marketplace snapshot JSON via the agent export pipeline."""
    export_dict = await export_agent_dict_for_repository_impl(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )
    skills = collect_skill_zip_entries(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
    )
    snapshot = AgentRepositorySnapshot(
        **export_dict,
        skills=skills or None,
    )
    return snapshot.model_dump()


async def _build_repository_data_from_agent(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
    *,
    card_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a repository upsert payload from a published agent version snapshot."""
    agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
    _validate_create_listing_permission(user_id=user_id, agent_info=agent_info)

    agent_info_json = await _build_agent_info_json(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )

    version_meta = search_version_by_version_no(agent_id, tenant_id, version_no)
    version_name = (
        version_meta.get("version_name")
        if version_meta and version_meta.get("version_name")
        else f"V{version_no}"
    )

    repository_data: Dict[str, Any] = {
        "agent_id": agent_id,
        "version_no": version_no,
        "name": agent_info["name"],
        "display_name": agent_info.get("display_name"),
        "description": agent_info.get("description"),
        "author": agent_info.get("author"),
        "submitted_by": _resolve_submitter_email(user_id),
        "version_name": version_name,
        "agent_info_json": agent_info_json,
        "status": STATUS_PENDING_REVIEW,
        "tool_count": _count_tools_in_snapshot(agent_info_json),
    }

    if card_fields:
        for key in ("icon", "downloads", "tool_count", "content"):
            if key in card_fields and card_fields[key] is not None:
                repository_data[key] = card_fields[key]
        if "tags" in card_fields and card_fields["tags"] is not None:
            repository_data["tags"] = _normalize_listing_tags(card_fields["tags"])

    return repository_data


async def create_agent_repository_listing_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
    *,
    card_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create or update a repository listing from a published agent version.

    Loads agent metadata and builds agent_info_json via the export pipeline,
    then inserts or updates the marketplace table.

    When a listing for the same agent version already exists, its status is
    updated to pending_review along with icon and tags when provided.
    """
    if version_no < 0:
        raise ValueError("version_no must be >= 0")

    repository_data = await _build_repository_data_from_agent(
        agent_id,
        tenant_id,
        user_id,
        version_no,
        card_fields=card_fields,
    )
    repository_data["content"] = (card_fields or {}).get("content") or ""
    _validate_create_payload(repository_data)

    existing = get_agent_repository_by_agent_id(
        agent_id,
        version_no,
        publisher_tenant_id=tenant_id,
    )
    if not existing:
        repository_id = insert_agent_repository_record(
            repository_data=repository_data,
            publisher_tenant_id=tenant_id,
            publisher_user_id=user_id,
        )
        is_updated = False
    else:
        repository_id = int(existing["agent_repository_id"])
        updates: Dict[str, Any] = {
            "status": STATUS_PENDING_REVIEW,
            "content": repository_data["content"],
        }
        for key in ("icon", "tags", "tool_count"):
            if key in repository_data:
                updates[key] = repository_data[key]
        affected = update_agent_repository_by_id(
            repository_id=repository_id,
            publisher_tenant_id=tenant_id,
            user_id=user_id,
            updates=updates,
        )
        if affected == 0:
            raise ValueError("Failed to update repository listing")
        is_updated = True

    record = get_agent_repository_by_id(
        repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError("Failed to load repository listing after write")
    _reset_repository_peer_statuses(
        agent_repository_id=repository_id,
        agent_id=agent_id,
        status=repository_data["status"],
        publisher_tenant_id=tenant_id,
    )
    create_repository_pending_review_notification(
        resource_type=RESOURCE_TYPE_AGENT_REPOSITORY,
        tenant_id=tenant_id,
        unique_id=repository_id,
        details={
            "name": record.get("display_name") or record.get("name"),
            "agent_repository_id": repository_id,
            "agent_id": record.get("agent_id"),
            "content": record.get("content") or "",
        },
        created_by=user_id,
    )
    return _to_detail_item(record, is_updated=is_updated)


def check_repository_import_precheck_impl(
    agent_repository_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Check whether the current tenant can import a shared repository listing."""
    record = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError("Repository listing not found")

    if record.get("status") != STATUS_SHARED:
        raise ValueError("Repository listing is not available for import")

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Repository listing has no agent snapshot")

    snapshot = AgentRepositorySnapshot.model_validate(agent_info_json)
    display_name = (
        str(record.get("display_name") or "").strip()
        or str(record.get("name") or "").strip()
        or "Agent"
    )
    result = build_repository_import_precheck(
        agent_repository_id=agent_repository_id,
        display_name=display_name,
        snapshot=snapshot,
        tenant_id=tenant_id,
    )
    return result.model_dump()


async def import_agent_from_repository_impl(
    agent_repository_id: int,
    tenant_id: str,
    authorization: str,
) -> Dict[int, int]:
    """Import an agent tree from a marketplace repository listing into the current tenant."""
    record = get_agent_repository_by_id(
        agent_repository_id,
        tenant_id,
    )
    if not record:
        raise ValueError("Repository listing not found")

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Repository listing has no agent snapshot")

    snapshot = AgentRepositorySnapshot.model_validate(agent_info_json)
    if snapshot.skills:
        result = await import_agent_with_skills_impl(
            snapshot,
            snapshot.skills,
            authorization,
        )
    else:
        result = await import_agent_impl(snapshot, authorization)

    affected = increment_agent_repository_downloads(agent_repository_id)
    if affected == 0:
        logger.warning(
            "Failed to increment repository downloads after import "
            "(agent_repository_id=%s)",
            agent_repository_id,
        )
    return result
