import logging
from typing import Any, Dict, Optional

from consts.const import ASSET_OWNER_TENANT_ID
from consts.model import AgentRepositorySnapshot
from database.agent_db import search_agent_info_by_agent_id
from database.agent_version_db import search_version_by_version_no
from database.agent_repository_db import (
    STATUS_PENDING_REVIEW,
    VALID_REPOSITORY_STATUSES,
    get_agent_repository_by_agent_id,
    get_agent_repository_by_id,
    insert_agent_repository_record,
    list_agent_repository_summaries,
    update_agent_repository_by_id,
    update_agent_repository_status_by_id,
)
from services.agent_service import (
    collect_skill_zip_entries,
    export_agent_dict_for_repository_impl,
    import_agent_impl,
    import_agent_with_skills_impl,
)

logger = logging.getLogger("agent_repository_service")

_UPDATE_SNAPSHOT_FIELDS = (
    "display_name",
    "description",
    "author",
    "category_id",
    "tags",
    "tool_count",
    "version_label",
    "source_version_no",
    "agent_info_json",
    "status",
)


def _to_summary_item(record: Dict[str, Any]) -> Dict[str, Any]:
    """Map a DB record to a lightweight marketplace summary item."""
    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "author": record.get("author"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "status": record.get("status"),
    }


def list_agent_repository_listings_impl(
    *,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """List all repository listings with optional status filter."""
    if status is not None and status not in VALID_REPOSITORY_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'; must be one of: "
            f"{', '.join(sorted(VALID_REPOSITORY_STATUSES))}"
        )
    records = list_agent_repository_summaries(status=status)
    return {"items": [_to_summary_item(record) for record in records]}


def update_agent_repository_status_impl(
    *,
    agent_repository_id: int,
    status: str,
    user_id: str,
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

    rows_affected = update_agent_repository_status_by_id(
        repository_id=agent_repository_id,
        status=status,
        user_id=user_id,
    )
    if rows_affected == 0:
        raise ValueError("Repository listing not found")

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
        "category_id": record.get("category_id"),
        "tags": record.get("tags") or [],
        "tool_count": record.get("tool_count"),
        "version_label": record.get("version_label"),
        "status": record.get("status"),
        "source_version_no": record.get("source_version_no"),
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
        "source_version_no",
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


def _validate_agent_info_json_shareable(agent_info_json: dict) -> None:
    """Reject marketplace share when any agent in the tree belongs to ASSET_OWNER tenant."""
    agent_info_map = agent_info_json.get("agent_info")
    if not isinstance(agent_info_map, dict):
        return
    for entry in agent_info_map.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("tenant_id") == ASSET_OWNER_TENANT_ID:
            raise ValueError("租户管理员智能体无法共享")


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
) -> Dict[str, Any]:
    """Build a repository upsert payload from a published agent version snapshot."""
    agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
    agent_info_json = await _build_agent_info_json(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )
    _validate_agent_info_json_shareable(agent_info_json)

    version_meta = search_version_by_version_no(agent_id, tenant_id, version_no)
    version_label = (
        version_meta.get("version_name")
        if version_meta and version_meta.get("version_name")
        else f"v{version_no}"
    )

    return {
        "agent_id": agent_id,
        "source_version_no": version_no,
        "name": agent_info["name"],
        "display_name": agent_info.get("display_name"),
        "description": agent_info.get("description"),
        "author": agent_info.get("author"),
        "version_label": version_label,
        "agent_info_json": agent_info_json,
        "status": STATUS_PENDING_REVIEW,
    }


async def create_agent_repository_listing_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
) -> Dict[str, Any]:
    """Create or update a repository listing from a published agent version.

    Loads agent metadata and builds agent_info_json via the export pipeline,
    then inserts or updates the marketplace table.

    When a listing for the same agent_id already exists, snapshot fields are
    updated via update_agent_repository_by_id.
    """
    if version_no < 0:
        raise ValueError("version_no must be >= 0")

    repository_data = await _build_repository_data_from_agent(
        agent_id, tenant_id, user_id, version_no
    )
    _validate_create_payload(repository_data)

    existing = get_agent_repository_by_agent_id(agent_id)
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
