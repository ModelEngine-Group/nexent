import logging
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from consts.exceptions import UnauthorizedError
from consts.model import AgentRepositorySnapshot
from database.agent_db import search_agent_info_by_agent_id
from database.agent_version_db import search_version_by_version_no
from database.agent_repository_db import (
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
    OWNERSHIP_ALL,
    VALID_OWNERSHIP_FILTERS,
    VALID_REPOSITORY_STATUSES,
    count_editable_agents_by_ownership,
    get_agent_repository_by_agent_id,
    get_agent_repository_by_id,
    insert_agent_repository_record,
    list_agent_repository_by_agent_ids,
    list_agent_repository_summaries,
    list_editable_agents_for_user,
    reset_agent_repository_status,
    update_agent_repository_by_id,
    update_agent_repository_status_by_id,
)
from database.user_tenant_db import get_user_tenant_by_user_id
from services.agent_service import (
    collect_skill_zip_entries,
    export_agent_dict_for_repository_impl,
    import_agent_impl,
    import_agent_with_skills_impl,
)

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

_REPOSITORY_STATUS_PRIORITY: Dict[str, int] = {
    STATUS_SHARED: 4,
    STATUS_PENDING_REVIEW: 3,
    STATUS_REJECTED: 2,
    STATUS_NOT_SHARED: 1,
}

_MAX_LISTING_TAGS = 5
_MAX_LISTING_TAG_LENGTH = 20
_MAX_LISTING_ICON_LENGTH = 32

_UPDATE_SNAPSHOT_FIELDS = (
    "display_name",
    "description",
    "author",
    "submitted_by",
    "category_id",
    "tags",
    "tool_count",
    "version_name",
    "icon",
    "downloads",
    "version_no",
    "agent_info_json",
    "status",
)


def _to_summary_item(record: Dict[str, Any]) -> Dict[str, Any]:
    """Map a DB record to a lightweight marketplace summary item."""
    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": record.get("agent_id"),
        "author": record.get("author"),
        "submitted_by": record.get("submitted_by"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "status": record.get("status"),
        "category_id": record.get("category_id"),
        "tags": record.get("tags") or [],
        "tool_count": record.get("tool_count"),
        "version_label": record.get("version_name"),
        "icon": record.get("icon"),
        "downloads": record.get("downloads") or 0,
    }


def _deduplicate_repository_summaries_by_agent_id(
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep one repository summary per agent using marketplace status priority."""
    selected_records: Dict[Tuple[str, Any], Dict[str, Any]] = {}

    for record in records:
        agent_id = record.get("agent_id")
        dedupe_key = (
            ("agent", agent_id)
            if agent_id is not None
            else ("repository", record.get("agent_repository_id"))
        )
        current = selected_records.get(dedupe_key)
        if current is None or _repository_summary_rank(record) > _repository_summary_rank(current):
            selected_records[dedupe_key] = record

    return sorted(
        selected_records.values(),
        key=lambda record: int(record.get("agent_repository_id") or 0),
        reverse=True,
    )


def _repository_summary_rank(record: Dict[str, Any]) -> Tuple[int, int]:
    """Rank summaries by status priority, then newest repository ID."""
    return (
        _REPOSITORY_STATUS_PRIORITY.get(str(record.get("status") or ""), 0),
        int(record.get("agent_repository_id") or 0),
    )


def list_agent_repository_listings_impl(
    *,
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
    deduplicate_by_agent_id: bool = True,
    category_id: Optional[int] = None,
) -> Dict[str, Any]:
    """List all repository listings with optional status filter."""
    if status is not None and status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )
    records = list_agent_repository_summaries(
        status=status,
        agent_id=agent_id,
        category_id=category_id,
    )
    if deduplicate_by_agent_id:
        records = _deduplicate_repository_summaries_by_agent_id(records)
    return {"items": [_to_summary_item(record) for record in records]}


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

    category_id = repository_data.get("category_id")
    if category_id is None or not isinstance(category_id, int):
        raise ValueError("category_id is required and must be an integer")

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
) -> None:
    """Reset peer listings with the same status; also clear rejected when submitting."""
    reset_agent_repository_status(
        agent_repository_id=agent_repository_id,
        agent_id=agent_id,
        status=status,
    )
    if status == STATUS_PENDING_REVIEW:
        reset_agent_repository_status(
            agent_repository_id=agent_repository_id,
            agent_id=agent_id,
            status=STATUS_REJECTED,
        )


def _to_repository_info_item(record: Dict[str, Any]) -> Dict[str, Any]:
    """Map a repository DB row to a my-agents repository_info entry."""
    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "status": record.get("status"),
        "version_no": record.get("version_no"),
        "version_label": record.get("version_name"),
        "create_time": _serialize_created_at(record.get("create_time")),
    }


def list_my_editable_agents_impl(
    tenant_id: str,
    user_id: str,
    ownership: str = OWNERSHIP_ALL,
) -> Dict[str, Any]:
    """List editable draft agents for the current user with repository listing info."""
    normalized_ownership = (ownership or OWNERSHIP_ALL).strip().lower()
    if normalized_ownership not in VALID_OWNERSHIP_FILTERS:
        raise ValueError(
            f"Invalid ownership filter: {ownership}. "
            f"Allowed values: {', '.join(sorted(VALID_OWNERSHIP_FILTERS))}."
        )

    user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
    user_role = str(user_tenant_record.get("user_role") or "").upper()

    counts = count_editable_agents_by_ownership(
        tenant_id,
        user_id,
        user_role=user_role,
    )
    agents = list_editable_agents_for_user(
        tenant_id,
        user_id,
        user_role=user_role,
        ownership_filter=normalized_ownership,
    )
    agent_ids = [int(agent["agent_id"]) for agent in agents if agent.get("agent_id") is not None]

    repository_by_agent_id: Dict[int, List[Dict[str, Any]]] = {}
    if agent_ids:
        repository_records = list_agent_repository_by_agent_ids(
            agent_ids,
            statuses=_MY_AGENT_REPOSITORY_STATUSES,
            publisher_tenant_id=tenant_id,
        )
        for record in repository_records:
            agent_id = record.get("agent_id")
            if agent_id is None:
                continue
            repository_by_agent_id.setdefault(int(agent_id), []).append(
                _to_repository_info_item(record)
            )

    items = [
        {
            "agent_id": agent.get("agent_id"),
            "name": agent.get("display_name") or agent.get("name"),
            "description": agent.get("description"),
            "current_version_no": agent.get("current_version_no"),
            "version_label": agent.get("version_name"),
            "version_create_time": _serialize_created_at(agent.get("version_create_time")),
            "repository_info": repository_by_agent_id.get(int(agent["agent_id"]), [])
            if agent.get("agent_id") is not None
            else [],
        }
        for agent in agents
    ]

    return {
        "items": items,
        "counts": counts,
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


def _serialize_created_at(create_time: Any) -> Optional[str]:
    """Serialize DB create_time to an ISO string for API consumers."""
    if create_time is None:
        return None
    if hasattr(create_time, "isoformat"):
        return create_time.isoformat()
    return str(create_time)


def get_agent_repository_listing_detail_impl(
    agent_repository_id: int,
) -> Dict[str, Any]:
    """Load a repository listing and return a detail payload for the UI."""
    record = get_agent_repository_by_id(agent_repository_id)
    if not record:
        raise ValueError("Repository listing not found")

    root_agent = _extract_root_agent_from_snapshot(record.get("agent_info_json"))

    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": record.get("agent_id"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "author": record.get("author"),
        "submitted_by": record.get("submitted_by"),
        "icon": record.get("icon"),
        "status": record.get("status"),
        "version_label": record.get("version_name"),
        "downloads": record.get("downloads") or 0,
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
    """Only ADMIN, or DEV whose email matches agent.author, may share to marketplace."""
    user_role = _get_user_role(user_id)
    if user_role == "ADMIN":
        return
    if user_role == "DEV":
        user_tenant = get_user_tenant_by_user_id(user_id) or {}
        user_email = str(user_tenant.get("user_email") or "").strip()
        agent_author = str(agent_info.get("author") or "").strip()
        if user_email and agent_author and user_email.lower() == agent_author.lower():
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
) -> Dict[str, Any]:
    """Update a repository listing status by primary key."""
    if status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )

    record = get_agent_repository_by_id(agent_repository_id)
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
    )
    if rows_affected == 0:
        raise ValueError("Repository listing not found")

    _reset_repository_peer_statuses(
        agent_repository_id=agent_repository_id,
        agent_id=record["agent_id"],
        status=status,
    )

    updated = get_agent_repository_by_id(agent_repository_id)
    if not updated:
        raise ValueError("Failed to load repository listing after update")
    return _to_summary_item(updated)


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
        "category_id": record.get("category_id"),
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
        else f"v{version_no}"
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
    }

    if card_fields:
        for key in ("icon", "downloads", "category_id", "tool_count"):
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

    When a listing for the same agent version already exists, snapshot fields
    are updated via update_agent_repository_by_id.
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
    _validate_create_payload(repository_data)

    existing = get_agent_repository_by_agent_id(agent_id, version_no)
    if not existing:
        repository_id = insert_agent_repository_record(
            repository_data=repository_data,
            publisher_tenant_id=tenant_id,
            publisher_user_id=user_id,
        )
        is_updated = False
    else:
        repository_id = int(existing["agent_repository_id"])
        updates = {
            key: repository_data[key]
            for key in _UPDATE_SNAPSHOT_FIELDS
            if key in repository_data
        }
        affected = update_agent_repository_by_id(
            repository_id=repository_id,
            publisher_tenant_id=tenant_id,
            user_id=user_id,
            updates=updates,
        )
        if affected == 0:
            raise ValueError("Failed to update repository listing")
        is_updated = True

    record = get_agent_repository_by_id(repository_id)
    if not record:
        raise ValueError("Failed to load repository listing after write")
    _reset_repository_peer_statuses(
        agent_repository_id=repository_id,
        agent_id=agent_id,
        status=repository_data["status"],
    )
    return _to_detail_item(record, is_updated=is_updated)


async def import_agent_from_repository_impl(
    agent_repository_id: int,
    authorization: str,
) -> Dict[int, int]:
    """Import an agent tree from a marketplace repository listing into the current tenant."""
    record = get_agent_repository_by_id(agent_repository_id)
    if not record:
        raise ValueError("Repository listing not found")

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Repository listing has no agent snapshot")

    snapshot = AgentRepositorySnapshot.model_validate(agent_info_json)
    if snapshot.skills:
        return await import_agent_with_skills_impl(
            snapshot,
            snapshot.skills,
            authorization,
        )
    return await import_agent_impl(snapshot, authorization)
