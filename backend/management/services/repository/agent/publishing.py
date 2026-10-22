# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, Dict, Optional

from contracts.constants.agent import STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED, VALID_REPOSITORY_STATUSES
from contracts.constants.identity import SYSTEM_TENANT_ID
from contracts.errors.exceptions import UnauthorizedError
from contracts.agent import AgentRepositorySnapshot
from contracts.constants.notification import EVENT_TYPE_REPOSITORY_REVIEW_PENDING, RESOURCE_TYPE_AGENT_REPOSITORY
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.agent.catalog import get_agent_repository_by_agent_id, get_agent_repository_by_id, insert_agent_repository_record, update_agent_repository_by_id, update_agent_repository_status_by_id
from management.db.agent.version import search_version_by_version_no
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.services.agent.icon import read_icon_image
from management.services.agent.service import (
    collect_skill_zip_entries,
    export_agent_dict_for_repository_impl,
)
from management.services.notification.service import (
    create_repository_pending_review_notification,
    create_repository_review_notification,
    deactivate_notifications,
)
from management.services.permission.identity.display import (
    enrich_repository_identities,
    repository_identity_fields,
)
from management.services.repository.agent.common import (
    _ADMIN_REVIEW_STATUS_TRANSITIONS,
    _PUBLISHER_RESUBMIT_TRANSITIONS,
    _PUBLISHER_STATUS_TRANSITIONS,
    _SU_STATUS_TRANSITIONS,
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
            raise UnauthorizedError("Not authorized to update this repository listing")
        if user_role == "DEV" and record.get("publisher_user_id") != user_id:
            raise UnauthorizedError("Not authorized to update this repository listing")
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
        record = get_agent_repository_by_id(
            agent_repository_id,
            SYSTEM_TENANT_ID,
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
            publisher_updates["publisher_tenant_id"] if publisher_updates else None
        ),
        publisher_user_id=(
            publisher_updates["publisher_user_id"] if publisher_updates else None
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

    enrich_repository_identities([updated], "agent")
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
            details["content"] = review_reason
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
        **repository_identity_fields(record),
        "submitted_by": record.get("submitted_by"),
        "tags": record.get("tags") or [],
        "tool_count": record.get("tool_count"),
        "version_label": record.get("version_name"),
        "icon_url": record.get("icon_url"),
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
    enrich_repository_identities([record], "agent")
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
        field
        for field in required_fields
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
        for key in ("icon_url", "downloads", "tool_count", "content"):
            if key in card_fields and (
                key == "icon_url" or card_fields[key] is not None
            ):
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
    updated to pending_review along with icon_url and tags when provided.
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
    icon_url = repository_data.get("icon_url")
    if icon_url is not None:
        image_id = _repository_image_id(icon_url, agent_id, version_no)
        try:
            read_icon_image(
                _repository_icon_object_name(tenant_id, agent_id, version_no, image_id)
            )
        except FileNotFoundError as exc:
            raise ValueError("Repository icon upload not found") from exc

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
        for key in ("icon_url", "tags", "tool_count"):
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


from management.services.repository.agent.common import (
    _count_tools_in_snapshot,
    _get_user_role,
    _normalize_listing_tags,
    _repository_icon_object_name,
    _repository_image_id,
    _reset_repository_peer_statuses,
    _resolve_submitter_email,
    _to_summary_item,
    _validate_card_fields,
    _validate_create_listing_permission,
)
