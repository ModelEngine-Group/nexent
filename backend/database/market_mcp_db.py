import logging
from typing import Any, Dict, List

from sqlalchemy import func, or_

from database.client import as_dict, filter_property, get_db_session
from database.db_models import McpMarketRecord

logger = logging.getLogger("market_mcp_db")


def get_mcp_market_records(
    *,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Cursor-paginated listing of approved market records (Repository tab).

    All records in mcp_market_record_t are approved, so no review_status filter needed.
    """
    with get_db_session() as session:
        query = session.query(McpMarketRecord).filter(
            McpMarketRecord.delete_flag != "Y",
        )

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

        next_cursor = None
        if has_next and page_rows:
            next_cursor = str(page_rows[-1].market_id)

        return {
            "count": len(page_rows),
            "nextCursor": next_cursor,
            "items": [as_dict(row) for row in page_rows],
        }


def get_mcp_market_tag_stats() -> List[Dict[str, Any]]:
    """Aggregate tag statistics from all approved market records."""
    with get_db_session() as session:
        rows = (
            session.query(
                func.unnest(McpMarketRecord.tags).label("tag"),
                func.count(McpMarketRecord.market_id).label("count"),
            )
            .filter(
                McpMarketRecord.delete_flag != "Y",
            )
            .group_by("tag")
            .order_by(func.count(McpMarketRecord.market_id).desc(), "tag")
            .all()
        )
        return [{"tag": str(row.tag), "count": int(row.count)} for row in rows if row.tag]


def create_mcp_market_record(mcp_data: Dict[str, Any], tenant_id: str, user_id: str) -> int:
    """Create a new approved market record. Returns the new market_id."""
    with get_db_session() as session:
        mcp_data.update({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_by": user_id,
            "updated_by": user_id,
            "delete_flag": "N",
            "source": "community",
        })
        new_record = McpMarketRecord(**filter_property(mcp_data, McpMarketRecord))
        session.add(new_record)
        session.flush()
        return int(new_record.market_id)


def get_mcp_market_record_by_id(market_id: int) -> Dict[str, Any] | None:
    """Fetch a single market record by ID."""
    with get_db_session() as session:
        record = session.query(McpMarketRecord).filter(
            McpMarketRecord.market_id == market_id,
            McpMarketRecord.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def update_mcp_market_record_version(
    *,
    market_id: int,
    version: str,
    registry_json: Dict[str, Any] | None = None,
    user_id: str,
) -> None:
    """Update the version (and optional registry_json) on an approved market record."""
    update_fields: Dict[str, Any] = {"version": version, "updated_by": user_id}
    if registry_json is not None:
        update_fields["registry_json"] = registry_json

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
    """List all market records for a specific tenant+user."""
    with get_db_session() as session:
        rows = session.query(McpMarketRecord).filter(
            McpMarketRecord.tenant_id == tenant_id,
            McpMarketRecord.user_id == user_id,
            McpMarketRecord.delete_flag != "Y",
        ).order_by(McpMarketRecord.market_id.desc()).all()
        return [as_dict(row) for row in rows]


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
    """Tag stats scoped to a specific tenant."""
    with get_db_session() as session:
        rows = (
            session.query(
                func.unnest(McpMarketRecord.tags).label("tag"),
                func.count(McpMarketRecord.market_id).label("count"),
            )
            .filter(
                McpMarketRecord.tenant_id == tenant_id,
                McpMarketRecord.delete_flag != "Y",
            )
            .group_by("tag")
            .order_by(func.count(McpMarketRecord.market_id).desc(), "tag")
            .all()
        )
        return [{"tag": str(row.tag), "count": int(row.count)} for row in rows if row.tag]
