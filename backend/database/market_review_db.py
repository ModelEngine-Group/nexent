import logging
from typing import Any, Dict, List

from sqlalchemy import func, or_

from database.client import as_dict, filter_property, get_db_session
from database.db_models import McpMarketReview

logger = logging.getLogger("market_review_db")


def create_mcp_market_review(mcp_data: Dict[str, Any], tenant_id: str, user_id: str) -> int:
    """Create a new review submission. Returns the new review_id."""
    with get_db_session() as session:
        mcp_data.update({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_by": user_id,
            "updated_by": user_id,
            "delete_flag": "N",
            "source": "community",
        })
        new_review = McpMarketReview(**filter_property(mcp_data, McpMarketReview))
        session.add(new_review)
        session.flush()
        return int(new_review.review_id)


def get_mcp_market_review_by_id(review_id: int, tenant_id: str | None = None) -> Dict[str, Any] | None:
    """Fetch a single review by ID, with optional tenant scope."""
    with get_db_session() as session:
        query = session.query(McpMarketReview).filter(
            McpMarketReview.review_id == review_id,
            McpMarketReview.delete_flag != "Y",
        )
        if tenant_id is not None:
            query = query.filter(McpMarketReview.tenant_id == tenant_id)
        record = query.first()
        return as_dict(record) if record else None


def list_mcp_market_review_records(
    *,
    tenant_id: str | None,
    status: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Cursor-paginated listing of review records (Review Center tab)."""
    with get_db_session() as session:
        query = session.query(McpMarketReview).filter(
            McpMarketReview.delete_flag != "Y",
        )

        if tenant_id is not None:
            query = query.filter(McpMarketReview.tenant_id == tenant_id)
        if status:
            query = query.filter(McpMarketReview.review_status == status)
        if transport_type:
            query = query.filter(McpMarketReview.transport_type == transport_type)
        if tag:
            query = query.filter(McpMarketReview.tags.any(tag))
        if search:
            keyword = f"%{search}%"
            query = query.filter(
                or_(
                    McpMarketReview.mcp_name.ilike(keyword),
                    McpMarketReview.description.ilike(keyword),
                    func.array_to_string(McpMarketReview.tags, ",").ilike(keyword),
                )
            )

        cursor_id: int | None = None
        if cursor:
            try:
                cursor_id = int(cursor)
            except ValueError:
                cursor_id = None
        if cursor_id is not None:
            query = query.filter(McpMarketReview.review_id < cursor_id)

        rows: List[McpMarketReview] = (
            query.order_by(McpMarketReview.review_id.desc())
            .limit(limit + 1)
            .all()
        )
        has_next = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = str(page_rows[-1].review_id) if has_next and page_rows else None

        return {
            "count": len(page_rows),
            "nextCursor": next_cursor,
            "items": [as_dict(row) for row in page_rows],
        }


def list_mcp_market_review_records_by_tenant_and_user(
    tenant_id: str,
    user_id: str,
    include_approved: bool = False,
) -> List[Dict[str, Any]]:
    """List review records for a specific tenant+user."""
    with get_db_session() as session:
        query = session.query(McpMarketReview).filter(
            McpMarketReview.tenant_id == tenant_id,
            McpMarketReview.user_id == user_id,
            McpMarketReview.delete_flag != "Y",
        )
        if not include_approved:
            query = query.filter(McpMarketReview.review_status != "approved")
        rows = query.order_by(McpMarketReview.review_id.desc()).all()
        return [as_dict(row) for row in rows]


def update_mcp_market_review_status(
    *,
    review_id: int,
    tenant_id: str | None,
    user_id: str,
    review_status: str,
) -> None:
    """Update review status on a single record. Tenant scope is optional (admin bypass)."""
    with get_db_session() as session:
        query = session.query(McpMarketReview).filter(
            McpMarketReview.review_id == review_id,
            McpMarketReview.delete_flag != "Y",
        )
        if tenant_id is not None:
            query = query.filter(McpMarketReview.tenant_id == tenant_id)
        query.update({"review_status": review_status, "updated_by": user_id})


def update_mcp_market_review_market_id(
    *,
    review_id: int,
    market_id: int,
    user_id: str,
) -> None:
    """Link a review to its approved market record."""
    with get_db_session() as session:
        session.query(McpMarketReview).filter(
            McpMarketReview.review_id == review_id,
            McpMarketReview.delete_flag != "Y",
        ).update({"market_id": market_id, "updated_by": user_id})


def list_mcp_market_review_records_by_market_id(market_id: int) -> List[Dict[str, Any]]:
    """List all reviews for a given market record."""
    with get_db_session() as session:
        rows = session.query(McpMarketReview).filter(
            McpMarketReview.market_id == market_id,
            McpMarketReview.delete_flag != "Y",
        ).order_by(McpMarketReview.review_id.desc()).all()
        return [as_dict(row) for row in rows]
