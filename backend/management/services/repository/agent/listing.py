# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
import uuid
from typing import Any, Collection, Dict, FrozenSet, List, Optional, Tuple

from contracts.constants.agent import OWNERSHIP_ALL, OWNERSHIP_CREATED, OWNERSHIP_OTHERS, STATUS_NOT_SHARED, STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED, VALID_OWNERSHIP_FILTERS, VALID_REPOSITORY_STATUSES
from contracts.constants.identity import SYSTEM_TENANT_ID
from contracts.errors.exceptions import UnauthorizedError
from contracts.agent import AgentRepositorySnapshot
from contracts.knowledge import KnowledgeBaseResolution
from contracts.skill import SkillResolution
from contracts.constants.notification import EVENT_TYPE_REPOSITORY_REVIEW_PENDING, RESOURCE_TYPE_AGENT_REPOSITORY
from management.db.agent.repository import delete_agent_by_id, search_agent_info_by_agent_id
from management.db.agent.catalog import fetch_draft_agent_mine_metadata, get_agent_repository_by_agent_id, get_agent_repository_by_id, increment_agent_repository_downloads, insert_agent_repository_record, list_agent_repository_by_agent_ids, list_agent_repository_summaries, reset_agent_repository_status, soft_delete_agent_repository_record, sum_agent_repository_downloads_by_agent_ids, update_agent_repository_by_id, update_agent_repository_status_by_id
from management.db.agent.version import search_version_by_version_no
from management.db.tag.repository import TagManagementDB
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.services.agent.icon import read_icon_image, upload_icon_image
from management.services.agent.service import (
    collect_skill_zip_entries,
    export_agent_dict_for_repository_impl,
    import_agent_impl,
    import_agent_with_skills_impl,
    list_all_agent_info_impl,
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
    _MAX_LISTING_ICON_LENGTH,
    _MAX_LISTING_TAG_LENGTH,
    _MAX_LISTING_TAGS,
    _MY_AGENT_REPOSITORY_STATUSES,
    _PUBLISHER_RESUBMIT_TRANSITIONS,
    _PUBLISHER_STATUS_TRANSITIONS,
    _SU_STATUS_TRANSITIONS,
    logger,
)
from management.services.repository.precheck import build_repository_import_precheck


def _get_agent_download_totals(agent_ids: Collection[int]) -> Dict[int, int]:
    """Return total downloads summed across all repository rows per agent_id."""
    normalized_ids = {int(agent_id) for agent_id in agent_ids if agent_id is not None}
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
    return query in name or query in description or query in tag_text


def _find_agent_ids_matching_any_tag_predicate(
    tenant_id: str,
    agent_ids: Collection[int],
    predicates: Collection[Any],
) -> set[str]:
    """Return visible agents matching any structured tag predicate."""
    if not agent_ids or not predicates:
        return set()

    resource_ids = [str(agent_id) for agent_id in agent_ids]
    matched_ids: set[str] = set()
    for predicate in predicates:
        matched_ids.update(
            TagManagementDB.filter_authorized_resource_ids(
                tenant_id,
                "agent",
                resource_ids,
                [predicate],
            )
        )
    return matched_ids


def _filter_agent_ids_by_tag_predicates(
    tenant_id: str,
    agent_ids: Collection[str],
    predicates: Collection[Any],
) -> set[str]:
    """Return visible agents matching all selected structured tag predicates."""
    if not agent_ids or not predicates:
        return set()

    return set(
        TagManagementDB.filter_authorized_resource_ids(
            tenant_id,
            "agent",
            list(agent_ids),
            list(predicates),
        )
    )


def list_agent_repository_listings_impl(
    tenant_id: str,
    *,
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    search_tag_predicates: Optional[list] = None,
    tag_predicates: Optional[list] = None,
    tag: Optional[str] = None,
    sort_by_update_time: bool = False,
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
    # Summary queries intentionally omit the publisher field. Restore it
    # before mapping the response so official rows can be identified by the
    # client and routed to the official copy flow.
    for record in records:
        record.setdefault("publisher_tenant_id", tenant_id)
    # Official listings are published by the reserved official tenant.  They
    # must remain visible after the standalone deployment command finishes;
    # using OFFICIAL_AGENT_PROFILES here would incorrectly couple visibility to
    # the Nexent container's startup environment.
    if agent_id is None and (status is None or status == STATUS_SHARED):
        official_records = list_agent_repository_summaries(
            publisher_tenant_id=SYSTEM_TENANT_ID,
            status=STATUS_SHARED,
            agent_id=agent_id,
        )
        for record in official_records:
            record["publisher_tenant_id"] = SYSTEM_TENANT_ID
        records.extend(official_records)
        # Keep the response stable if a repository record is visible through
        # both tenant queries (for example during a migration or in tests).
        unique_records = {}
        for record in records:
            unique_records[record.get("agent_repository_id")] = record
        records = list(unique_records.values())
    if tag_predicates:
        record_agent_ids = [
            str(record["agent_id"])
            for record in records
            if record.get("agent_id") is not None
        ]
        matched_agent_ids = _filter_agent_ids_by_tag_predicates(
            tenant_id,
            record_agent_ids,
            tag_predicates,
        )
        records = [
            record
            for record in records
            if str(record.get("agent_id")) in matched_agent_ids
        ]
    search_matched_agent_ids = _find_agent_ids_matching_any_tag_predicate(
        tenant_id,
        [
            int(record["agent_id"])
            for record in records
            if record.get("agent_id") is not None
        ],
        search_tag_predicates or [],
    )
    if search and search.strip():
        records = [
            record
            for record in records
            if _matches_repository_listing_search_filter(record, search)
            or str(record.get("agent_id")) in search_matched_agent_ids
        ]
    if tag and tag.strip():
        records = [
            record for record in records if tag.strip() in (record.get("tags") or [])
        ]
    if sort_by_update_time:
        # Order the merged tenant+official set as one list; ordering only in
        # SQL would interleave the two query blocks incorrectly.
        records = _order_listings_by_publish_time(records)
    total = len(records)
    start = (page - 1) * page_size
    paged_records = records[start : start + page_size]
    enrich_repository_identities(paged_records, "agent")
    paged_agent_ids = [
        int(record["agent_id"])
        for record in paged_records
        if record.get("agent_id") is not None
    ]
    main_flags = _get_agent_main_flags(paged_agent_ids)
    for record in paged_records:
        agent_id = record.get("agent_id")
        record["is_main_agent"] = (
            main_flags.get(int(agent_id), True) if agent_id is not None else True
        )
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


def list_agent_repository_tag_stats_impl(tenant_id: str) -> List[Dict[str, Any]]:
    """Return shared repository tags and their listing counts for one tenant."""
    counts: Dict[str, int] = {}
    for record in list_agent_repository_summaries(
        publisher_tenant_id=tenant_id,
        status=STATUS_SHARED,
    ):
        for raw_tag in record.get("tags") or []:
            tag = str(raw_tag).strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return [
        {"tag": tag, "count": count}
        for tag, count in sorted(counts.items(), key=lambda item: item[0].lower())
    ]


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


def _matches_mine_search_filter(
    agent: dict,
    search: str,
    tags: Collection[str] = (),
) -> bool:
    """Match a mine agent by name, description, or visible tag value."""
    query = search.strip().lower()
    if not query:
        return True
    name = str(agent.get("display_name") or agent.get("name") or "").lower()
    description = str(agent.get("description") or "").lower()
    return (
        query in name
        or query in description
        or any(query in str(tag).lower() for tag in tags)
    )


def _merge_agent_tag_values(
    agent_ids: Collection[int],
    tenant_id: str,
    repository_records: Collection[Dict[str, Any]],
) -> Dict[int, List[str]]:
    """Merge canonical agent assignments with publisher-owned listing tags."""

    try:
        structured = TagManagementDB.list_resource_assignment_display_values_by_ids(
            tenant_id,
            "agent",
            [str(agent_id) for agent_id in agent_ids],
        )
    except Exception as error:  # noqa: BLE001 - repository search keeps legacy fallback
        logger.warning("Failed to load structured agent tags for search: %s", error)
        structured = {}
    merged: Dict[int, List[str]] = {
        int(agent_id): list(structured.get(str(agent_id), [])) for agent_id in agent_ids
    }
    for record in repository_records:
        record_agent_id = record.get("agent_id")
        if record_agent_id is None:
            continue
        target = merged.setdefault(int(record_agent_id), [])
        for value in record.get("tags") or []:
            normalized = str(value).strip()
            if normalized and normalized not in target:
                target.append(normalized)
    return merged


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
    tag_predicates: Optional[list] = None,
    search_tag_predicates: Optional[list] = None,
) -> Dict[str, Any]:
    """List visible draft agents for the current user with repository listing info."""
    normalized_ownership = (ownership or OWNERSHIP_ALL).strip().lower()
    if normalized_ownership not in VALID_OWNERSHIP_FILTERS:
        raise ValueError(
            f"Invalid ownership filter: {ownership}. "
            f"Allowed values: {', '.join(sorted(VALID_OWNERSHIP_FILTERS))}."
        )

    all_agents = await list_all_agent_info_impl(tenant_id=tenant_id, user_id=user_id)
    if tag_predicates:
        agent_ids_for_filter = [
            str(agent["agent_id"])
            for agent in all_agents
            if agent.get("agent_id") is not None
        ]
        matched_ids = set(
            TagManagementDB.filter_authorized_resource_ids(
                tenant_id,
                "agent",
                agent_ids_for_filter,
                tag_predicates,
            )
        )
        all_agents = [
            agent for agent in all_agents if str(agent.get("agent_id")) in matched_ids
        ]
    agent_ids = [
        int(agent["agent_id"])
        for agent in all_agents
        if agent.get("agent_id") is not None
    ]
    search_matched_agent_ids = _find_agent_ids_matching_any_tag_predicate(
        tenant_id,
        agent_ids,
        search_tag_predicates or [],
    )
    meta_by_id = fetch_draft_agent_mine_metadata(tenant_id, agent_ids)
    counts = _compute_mine_ownership_counts(all_agents, meta_by_id, user_id)

    repository_records_for_search: List[Dict[str, Any]] = []
    tags_by_agent_id: Dict[int, List[str]] = {}
    if search and search.strip() and agent_ids:
        repository_records_for_search = list_agent_repository_by_agent_ids(
            agent_ids,
            statuses=_MY_AGENT_REPOSITORY_STATUSES,
            publisher_tenant_id=tenant_id,
        )
        tags_by_agent_id = _merge_agent_tag_values(
            agent_ids,
            tenant_id,
            repository_records_for_search,
        )

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
            if _matches_mine_search_filter(
                agent,
                search,
                tags_by_agent_id.get(int(agent["agent_id"]), []),
            )
            or str(agent["agent_id"]) in search_matched_agent_ids
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
        and not tag_predicates
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
        if repository_records_for_search:
            paged_id_set = set(paged_agent_ids)
            repository_records = [
                record
                for record in repository_records_for_search
                if record.get("agent_id") is not None
                and int(record["agent_id"]) in paged_id_set
            ]
        else:
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
        if not tags_by_agent_id:
            tags_by_agent_id = _merge_agent_tag_values(
                paged_agent_ids,
                tenant_id,
                repository_records,
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
                "tags": tags_by_agent_id.get(entry_agent_id, []),
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
        record = get_agent_repository_by_id(
            agent_repository_id,
            SYSTEM_TENANT_ID,
        )
    if not record:
        raise ValueError("Repository listing not found")
    enrich_repository_identities([record], "agent")
    root_agent = _extract_root_agent_from_snapshot(record.get("agent_info_json"))
    agent_id = record.get("agent_id")
    download_total = 0
    if agent_id is not None:
        download_total = _get_agent_download_totals([int(agent_id)]).get(
            int(agent_id),
            0,
        )
    main_flags = _get_agent_main_flags([int(agent_id)]) if agent_id is not None else {}

    return {
        "agent_repository_id": record.get("agent_repository_id"),
        "agent_id": agent_id,
        "version_no": record.get("version_no"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "author": record.get("author"),
        **repository_identity_fields(record),
        "submitted_by": record.get("submitted_by"),
        "icon_url": record.get("icon_url"),
        "status": record.get("status"),
        "version_label": record.get("version_name"),
        "downloads": download_total,
        "created_at": _serialize_created_at(record.get("create_time")),
        "model_name": root_agent.get("model_name"),
        "duty_prompt": root_agent.get("duty_prompt"),
        "tools": _extract_tool_names(root_agent),
        "is_official": record.get("publisher_tenant_id") == SYSTEM_TENANT_ID,
        "is_main_agent": (
            main_flags.get(int(agent_id), True) if agent_id is not None else True
        ),
    }


from management.services.repository.agent.common import (
    _count_tools_in_snapshot,
    _get_user_role,
    _normalize_listing_tags,
    _repository_icon_object_name,
    _repository_icon_url,
    _repository_image_id,
    _reset_repository_peer_statuses,
    _resolve_submitter_email,
    _serialize_created_at,
    _to_summary_item,
    _validate_card_fields,
    _validate_create_listing_permission,
)
from management.services.repository.agent.icons import (
    get_agent_repository_icon_impl,
    upload_agent_repository_icon_impl,
)
from management.services.repository.agent.installation import (
    check_repository_import_precheck_impl,
    delete_official_agent_impl,
    import_agent_from_repository_impl,
    list_official_agent_management_impl,
)
from management.services.repository.agent.publishing import (
    _build_agent_info_json,
    _build_repository_data_from_agent,
    _handle_review_status_notifications,
    _to_detail_item,
    _to_list_item,
    _validate_create_payload,
    _validate_repository_status_transition,
    create_agent_repository_listing_impl,
    update_agent_repository_status_impl,
)


def _get_agent_main_flags(agent_ids: Collection[int]) -> Dict[int, bool]:
    """Return the main-agent flag per agent_id, degrading to no flags on error.

    The flag is presentational only; when the lookup is unavailable the caller
    falls back to the main-agent default instead of failing the listing request.
    """
    normalized_ids = {int(agent_id) for agent_id in agent_ids if agent_id is not None}
    if not normalized_ids:
        return {}
    try:
        return batch_get_agent_main_flags(list(normalized_ids))
    except Exception as error:  # noqa: BLE001 - degrade to the default flag
        logger.warning(
            "Failed to resolve agent main-agent flags; defaulting to main: %s",
            error,
        )
        return {}


def _repository_id_sort_key(record: Dict[str, Any]) -> int:
    """Return a comparable repository id for ordering, defaulting to -1."""
    try:
        return int(record.get("agent_repository_id"))
    except (TypeError, ValueError):
        return -1


def _publish_time_sort_key(record: Dict[str, Any]) -> float:
    """Return a numeric publish-time key; unparsable values collapse to 0.0."""
    create_time = record.get("create_time")
    if hasattr(create_time, "timestamp"):
        return create_time.timestamp()
    if isinstance(create_time, str):
        try:
            return datetime.fromisoformat(create_time).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _order_listings_by_publish_time(
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Order listings by publish time descending, with undated listings last.

    A repository-id tie-break keeps pagination deterministic across pages.
    """
    dated = [record for record in records if record.get("create_time") is not None]
    undated = [record for record in records if record.get("create_time") is None]
    dated.sort(
        key=lambda record: (
            _publish_time_sort_key(record),
            _repository_id_sort_key(record),
        ),
        reverse=True,
    )
    undated.sort(key=_repository_id_sort_key, reverse=True)
    return dated + undated


from datetime import datetime

from management.db.agent.repository import batch_get_agent_main_flags
