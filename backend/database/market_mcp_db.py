import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, text as sa_text

from database.client import as_dict, filter_property, get_db_session
from database.db_models import McpMarketRecord

logger = logging.getLogger("market_mcp_db")


def _apply_group_permission_filter(query, user_id: str, user_group_ids: List[int]):
    """Apply group-based visibility filter to a market record query.

    Users see MCPs where:
    - They are the creator, OR
    - The MCP has no group restriction (group_ids IS NULL/empty), OR
    - They belong to at least one of the MCP's allowed groups
    """
    conditions = [
        McpMarketRecord.user_id == user_id,
        McpMarketRecord.group_ids.is_(None),
        McpMarketRecord.group_ids == "",
    ]
    if user_group_ids:
        group_ids_str = ",".join(str(g) for g in user_group_ids)
        conditions.append(
            sa_text(
                f"string_to_array(group_ids, ',') && ARRAY[{group_ids_str}]::text[]"
            )
        )
    return query.filter(or_(*conditions))


def get_mcp_market_records(
    *,
    tenant_id: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
    user_id: str | None = None,
    user_group_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Cursor-paginated listing of shared (approved) market records scoped to a tenant."""
    with get_db_session() as session:
        query = session.query(McpMarketRecord).filter(
            McpMarketRecord.delete_flag != "Y",
            McpMarketRecord.review_status == "shared",
        )

        if tenant_id:
            query = query.filter(McpMarketRecord.tenant_id == tenant_id)

        if transport_type:
            query = query.filter(McpMarketRecord.transport_type == transport_type)

        if tag:
            query = query.filter(McpMarketRecord.tags.any(tag))

        if search:
            keyword = f"%{search}%"
            query = query.filter(
                or_(
                    McpMarketRecord.mcp_name.ilike(keyword),
                    McpMarketRecord.description.ilike(keyword),
                    func.array_to_string(McpMarketRecord.tags, ",").ilike(keyword),
                )
            )

        cursor_id: int | None = None
        if cursor:
            try:
                cursor_id = int(cursor)
            except ValueError:
                cursor_id = None

        if cursor_id is not None:
            query = query.filter(McpMarketRecord.market_id < cursor_id)

        if user_id is not None and user_group_ids is not None:
            query = _apply_group_permission_filter(query, user_id, user_group_ids)

        rows: List[McpMarketRecord] = (
            query.order_by(McpMarketRecord.market_id.desc())
            .limit(limit + 1)
            .all()
        )

        has_next = len(rows) > limit
        page_rows = rows[:limit]

        next_cursor = None
        if has_next and page_rows:
            next_cursor = str(page_rows[-1].market_id)

        return {
            "count": len(page_rows),
            "nextCursor": next_cursor,
            "items": [as_dict(row) for row in page_rows],
        }


def get_mcp_market_tag_stats() -> List[Dict[str, Any]]:
    """Aggregate tag statistics from all shared market records."""
    with get_db_session() as session:
        rows = (
            session.query(
                func.unnest(McpMarketRecord.tags).label("tag"),
                func.count(McpMarketRecord.market_id).label("count"),
            )
            .filter(
                McpMarketRecord.delete_flag != "Y",
                McpMarketRecord.review_status == "shared",
            )
            .group_by("tag")
            .order_by(func.count(McpMarketRecord.market_id).desc(), "tag")
            .all()
        )
        return [{"tag": str(row.tag), "count": int(row.count)} for row in rows if row.tag]


def create_mcp_market_record(mcp_data: Dict[str, Any], tenant_id: str, user_id: str) -> int:
    """Create a new market record. Returns the new market_id."""
    with get_db_session() as session:
        mcp_data.update({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_by": user_id,
            "updated_by": user_id,
            "delete_flag": "N",
            "source": "community",
        })
        if "review_status" not in mcp_data:
            mcp_data["review_status"] = "not_shared"
        new_record = McpMarketRecord(**filter_property(mcp_data, McpMarketRecord))
        session.add(new_record)
        session.flush()
        return int(new_record.market_id)


def get_mcp_market_record_by_id(market_id: int) -> Dict[str, Any] | None:
    """Fetch a single market record by ID (any status, non-deleted)."""
    with get_db_session() as session:
        record = session.query(McpMarketRecord).filter(
            McpMarketRecord.market_id == market_id,
            McpMarketRecord.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def check_mcp_market_name_exists(mcp_name: str) -> bool:
    """Check if a shared market record with the given name already exists.

    Matches the partial unique index uq_mcp_market_name_active:
      WHERE delete_flag = 'N' AND review_status = 'shared'
    """
    with get_db_session() as session:
        record = session.query(McpMarketRecord).filter(
            McpMarketRecord.mcp_name == mcp_name,
            McpMarketRecord.delete_flag != "Y",
            McpMarketRecord.review_status == "shared",
        ).first()
        return record is not None


def update_mcp_market_record(
    *,
    market_id: int,
    user_id: str,
    mcp_name: str | None = None,
    description: str | None = None,
    tags: List[str] | None = None,
    registry_json: Dict[str, Any] | None = None,
    mcp_server: str | None = None,
    config_json: Dict[str, Any] | None = None,
    transport_type: str | None = None,
    group_ids: str | None = None,
    ingroup_permission: str | None = None,
    shared_fields: dict | None = None,
) -> None:
    """Update editable fields on a market record (does not change status)."""
    update_fields: Dict[str, Any] = {"updated_by": user_id}
    if mcp_name is not None:
        update_fields["mcp_name"] = mcp_name
    if description is not None:
        update_fields["description"] = description
    if tags is not None:
        update_fields["tags"] = tags
    if registry_json is not None:
        update_fields["registry_json"] = registry_json
    if mcp_server is not None:
        update_fields["mcp_server"] = mcp_server
    if config_json is not None:
        update_fields["config_json"] = config_json
    if transport_type is not None:
        update_fields["transport_type"] = transport_type
    if group_ids is not None:
        update_fields["group_ids"] = group_ids
    if ingroup_permission is not None:
        update_fields["ingroup_permission"] = ingroup_permission
    if shared_fields is not None:
        update_fields["shared_fields"] = shared_fields

    with get_db_session() as session:
        session.query(McpMarketRecord).filter(
            McpMarketRecord.market_id == market_id,
            McpMarketRecord.delete_flag != "Y",
        ).update(update_fields)


def update_mcp_market_status(
    *,
    market_id: int,
    user_id: str,
    review_status: str,
    submitted_by: str | None = None,
) -> None:
    """Atomically update the review_status, optionally recording the submitter."""
    update_fields: Dict[str, Any] = {"updated_by": user_id, "review_status": review_status}
    if submitted_by is not None:
        update_fields["submitted_by"] = submitted_by

    with get_db_session() as session:
        session.query(McpMarketRecord).filter(
            McpMarketRecord.market_id == market_id,
            McpMarketRecord.delete_flag != "Y",
        ).update(update_fields)


def delete_mcp_market_record_by_id(*, market_id: int, user_id: str) -> None:
    """Soft-delete a market record."""
    with get_db_session() as session:
        session.query(McpMarketRecord).filter(
            McpMarketRecord.market_id == market_id,
            McpMarketRecord.delete_flag != "Y",
        ).update({"delete_flag": "Y", "updated_by": user_id})


def list_mcp_market_records_by_tenant_and_user(tenant_id: str, user_id: str) -> List[Dict[str, Any]]:
    """List all market records (all statuses) for a specific tenant+user."""
    with get_db_session() as session:
        rows = session.query(McpMarketRecord).filter(
            McpMarketRecord.tenant_id == tenant_id,
            McpMarketRecord.user_id == user_id,
            McpMarketRecord.delete_flag != "Y",
        ).order_by(McpMarketRecord.market_id.desc()).all()
        return [as_dict(row) for row in rows]


def list_mcp_market_records_by_status(
    *,
    tenant_id: str | None = None,
    review_status: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Cursor-paginated listing of market records filtered by review status (review queue)."""
    with get_db_session() as session:
        query = session.query(McpMarketRecord).filter(
            McpMarketRecord.delete_flag != "Y",
        )

        if tenant_id is not None:
            query = query.filter(McpMarketRecord.tenant_id == tenant_id)
        if review_status:
            query = query.filter(McpMarketRecord.review_status == review_status)
        if transport_type:
            query = query.filter(McpMarketRecord.transport_type == transport_type)
        if tag:
            query = query.filter(McpMarketRecord.tags.any(tag))
        if search:
            keyword = f"%{search}%"
            query = query.filter(
                or_(
                    McpMarketRecord.mcp_name.ilike(keyword),
                    McpMarketRecord.description.ilike(keyword),
                    func.array_to_string(McpMarketRecord.tags, ",").ilike(keyword),
                )
            )

        cursor_id: int | None = None
        if cursor:
            try:
                cursor_id = int(cursor)
            except ValueError:
                cursor_id = None
        if cursor_id is not None:
            query = query.filter(McpMarketRecord.market_id < cursor_id)

        rows: List[McpMarketRecord] = (
            query.order_by(McpMarketRecord.market_id.desc())
            .limit(limit + 1)
            .all()
        )
        has_next = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = str(page_rows[-1].market_id) if has_next and page_rows else None

        return {
            "count": len(page_rows),
            "nextCursor": next_cursor,
            "items": [as_dict(row) for row in page_rows],
        }


def increment_mcp_market_download_count(market_id: int) -> None:
    """Atomically increment the download counter on a market record."""
    with get_db_session() as session:
        session.query(McpMarketRecord).filter(
            McpMarketRecord.market_id == market_id,
            McpMarketRecord.delete_flag != "Y",
        ).update(
            {McpMarketRecord.download_count: McpMarketRecord.download_count + 1},
            synchronize_session=False,
        )


def get_mcp_market_tag_stats_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Tag stats scoped to a specific tenant from shared records only."""
    with get_db_session() as session:
        rows = (
            session.query(
                func.unnest(McpMarketRecord.tags).label("tag"),
                func.count(McpMarketRecord.market_id).label("count"),
            )
            .filter(
                McpMarketRecord.tenant_id == tenant_id,
                McpMarketRecord.delete_flag != "Y",
                McpMarketRecord.review_status == "shared",
            )
            .group_by("tag")
            .order_by(func.count(McpMarketRecord.market_id).desc(), "tag")
            .all()
        )
        return [{"tag": str(row.tag), "count": int(row.count)} for row in rows if row.tag]
