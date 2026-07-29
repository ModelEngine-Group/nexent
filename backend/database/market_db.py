"""Unified market database query layer.

Provides listing, detail, category, tag, review, and rating summary queries
for the unified market page and template detail page.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, func, or_

from database.client import as_dict, get_db_session
from database.db_models import (
    AgentRepository,
    MarketCategory,
    MarketRatingSummary,
    MarketReview,
    MarketTag,
    UserTenant,
)

logger = logging.getLogger("market_db")

# Entity type constants (avoid circular import with consts.market)
_ENTITY_AGENT = "agent"


def list_market_agents(
    *,
    page: int = 1,
    page_size: int = 20,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "latest",
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """List shared/official market agent listings with pagination and filters.

    Returns a dict with ``items`` and ``total`` keys.
    """
    with get_db_session() as session:
        query = session.query(AgentRepository).filter(
            AgentRepository.delete_flag != "Y",
            or_(
                AgentRepository.status == "shared",
                AgentRepository.is_official_template.is_(True),
            ),
        )

        # Category filter
        if category:
            query = query.filter(AgentRepository.category_id == category)

        # Tag filter (array contains)
        if tag:
            query = query.filter(AgentRepository.tags.any(tag))

        # Search filter
        if search:
            keyword = f"%{search}%"
            query = query.filter(
                or_(
                    AgentRepository.name.ilike(keyword),
                    AgentRepository.display_name.ilike(keyword),
                    AgentRepository.description.ilike(keyword),
                    func.array_to_string(AgentRepository.tags, ",").ilike(keyword),
                )
            )

        # Source filter
        if source:
            query = query.filter(AgentRepository.source == source)

        # Sort
        if sort == "popular":
            query = query.order_by(desc(AgentRepository.downloads), desc(AgentRepository.agent_repository_id))
        elif sort == "name":
            query = query.order_by(AgentRepository.display_name, AgentRepository.name)
        else:
            # default: latest
            query = query.order_by(desc(AgentRepository.agent_repository_id))

        # Total count before pagination
        total = query.count()

        # Pagination
        offset = (page - 1) * page_size
        rows = query.offset(offset).limit(page_size).all()

        items = []
        for row in rows:
            agent_count, skill_count, mcp_count = _count_composition(row.agent_info_json)
            items.append({
                "id": row.agent_repository_id,
                "agent_id": row.agent_id,
                "name": row.name,
                "display_name": row.display_name,
                "description": row.description,
                "author": row.author,
                "category": _resolve_category_for_agent(row, session),
                "tags": _format_tags(row.tags),
                "download_count": row.downloads or 0,
                "created_at": _serialize_dt(row.create_time),
                "tool_count": row.tool_count or 0,
                "is_featured": row.is_featured or False,
                "icon": row.icon,
                "source": row.source or "community",
                "is_official_template": row.is_official_template or False,
                # Solution composition: how many Agents/Skills/MCPs this
                # four-dim package bundles. Parsed from the frozen snapshot.
                "agent_count": agent_count,
                "skill_count": skill_count,
                "mcp_count": mcp_count,
            })

        return {"items": items, "total": total}


def list_featured_agents(limit: int = 6) -> List[Dict[str, Any]]:
    """Return a small set of featured agent listings for the market banner."""
    with get_db_session() as session:
        rows = (
            session.query(AgentRepository)
            .filter(
                AgentRepository.delete_flag != "Y",
                AgentRepository.is_featured.is_(True),
                or_(
                    AgentRepository.status == "shared",
                    AgentRepository.is_official_template.is_(True),
                ),
            )
            .order_by(desc(AgentRepository.featured_weight), desc(AgentRepository.downloads))
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.agent_repository_id,
                "agent_id": row.agent_id,
                "name": row.name,
                "display_name": row.display_name,
                "description": row.description,
                "author": row.author,
                "icon": row.icon,
                "download_count": row.downloads or 0,
                "is_featured": True,
            }
            for row in rows
        ]


def get_market_agent_detail(agent_repository_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single market agent listing by ID (includes agent_info_json)."""
    with get_db_session() as session:
        record = (
            session.query(AgentRepository)
            .filter(
                AgentRepository.agent_repository_id == agent_repository_id,
                AgentRepository.delete_flag != "Y",
                or_(
                    AgentRepository.status == "shared",
                    AgentRepository.is_official_template.is_(True),
                ),
            )
            .first()
        )
        if not record:
            return None
        return as_dict(record)


def get_market_agent_id_by_name(name: str) -> Optional[int]:
    """Resolve an official/shared template's repository ID by name."""
    with get_db_session() as session:
        record = (
            session.query(AgentRepository)
            .filter(
                AgentRepository.name == name,
                AgentRepository.delete_flag != "Y",
                or_(
                    AgentRepository.status == "shared",
                    AgentRepository.is_official_template.is_(True),
                ),
            )
            .first()
        )
        return int(record.agent_repository_id) if record else None


def list_categories(
    entity_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List all active market categories, optionally filtered by entity type."""
    with get_db_session() as session:
        query = session.query(MarketCategory).filter(
            MarketCategory.delete_flag != "Y",
            MarketCategory.is_active.is_(True),
        )
        if entity_type:
            query = query.filter(MarketCategory.entity_type == entity_type)
        rows = query.order_by(MarketCategory.sort_order, MarketCategory.category_id).all()
        return [
            {
                "id": row.category_id,
                "entity_type": row.entity_type,
                "name": row.name,
                "display_name": row.display_name,
                "display_name_zh": row.display_name_zh,
                "description": row.description,
                "description_zh": row.description_zh,
                "icon": row.icon,
                "sort_order": row.sort_order or 0,
                "created_at": _serialize_dt(row.create_time),
            }
            for row in rows
        ]


def list_tags() -> List[Dict[str, Any]]:
    """Aggregate tags from ag_agent_repository_t and mcp_market_record_t, deduplicated.

    Returns a list of dicts with ``id``, ``name``, ``display_name``, ``count``.
    """
    from database.db_models import McpMarketRecord

    with get_db_session() as session:
        # Agent repository tags
        agent_tag_rows = (
            session.query(
                func.unnest(AgentRepository.tags).label("tag"),
                func.count(AgentRepository.agent_repository_id).label("count"),
            )
            .filter(
                AgentRepository.delete_flag != "Y",
                or_(
                    AgentRepository.status == "shared",
                    AgentRepository.is_official_template.is_(True),
                ),
            )
            .group_by("tag")
            .all()
        )

        # MCP market tags
        mcp_tag_rows = (
            session.query(
                func.unnest(McpMarketRecord.tags).label("tag"),
                func.count(McpMarketRecord.market_id).label("count"),
            )
            .filter(
                McpMarketRecord.delete_flag != "Y",
                McpMarketRecord.review_status == "shared",
            )
            .group_by("tag")
            .all()
        )

        # Merge and deduplicate
        tag_map: Dict[str, int] = {}
        for row in agent_tag_rows + mcp_tag_rows:
            if row.tag:
                tag_str = str(row.tag).strip()
                if not tag_str:
                    continue
                tag_map[tag_str] = tag_map.get(tag_str, 0) + int(row.count)

        # Also include any tags from market_tag_t that have no usage
        defined_tags = (
            session.query(MarketTag)
            .filter(MarketTag.delete_flag != "Y")
            .all()
        )
        defined_names = {t.name: t for t in defined_tags}

        # Build sorted result (by count desc, then name asc)
        sorted_tags = sorted(tag_map.items(), key=lambda x: (-x[1], x[0]))
        result = []
        for idx, (tag_name, count) in enumerate(sorted_tags, start=1):
            defined = defined_names.get(tag_name)
            result.append({
                "id": defined.tag_id if defined else idx,
                "name": tag_name,
                "display_name": defined.display_name if defined and defined.display_name else tag_name,
                "description": defined.description if defined else None,
                "count": count,
                "created_at": _serialize_dt(defined.create_time) if defined else None,
            })

        # Add any defined tags not yet used
        used_names = set(tag_map.keys())
        for defined in defined_tags:
            if defined.name not in used_names:
                result.append({
                    "id": defined.tag_id,
                    "name": defined.name,
                    "display_name": defined.display_name or defined.name,
                    "description": defined.description,
                    "count": 0,
                    "created_at": _serialize_dt(defined.create_time),
                })

        return result


def create_review(
    *,
    entity_type: str,
    entity_id: int,
    tenant_id: str,
    user_id: str,
    rating: int,
    comment: str,
) -> Dict[str, Any]:
    """Insert a review/rating and update the rating summary.

    Enforces uniqueness: one review per user per entity.
    Returns a dict with ``review_id`` and ``status``.
    """
    with get_db_session() as session:
        # Check if user already reviewed this entity
        existing = (
            session.query(MarketReview)
            .filter(
                MarketReview.entity_type == entity_type,
                MarketReview.entity_id == entity_id,
                MarketReview.user_id == user_id,
                MarketReview.delete_flag != "Y",
            )
            .first()
        )
        if existing:
            # Update existing review
            old_rating = existing.rating
            existing.rating = rating
            existing.comment = comment
            existing.status = "visible"
            existing.updated_by = user_id
            session.flush()
            review_id = int(existing.review_id)

            # Adjust summary: remove old rating, add new
            _adjust_rating_summary(
                session, entity_type, entity_id,
                old_rating=old_rating, new_rating=rating,
                review_delta=0,
            )
        else:
            new_review = MarketReview(
                entity_type=entity_type,
                entity_id=entity_id,
                tenant_id=tenant_id,
                user_id=user_id,
                rating=rating,
                comment=comment,
                status="visible",
                created_by=user_id,
                updated_by=user_id,
                delete_flag="N",
            )
            session.add(new_review)
            session.flush()
            review_id = int(new_review.review_id)

            # Add new rating to summary
            _adjust_rating_summary(
                session, entity_type, entity_id,
                old_rating=None, new_rating=rating,
                review_delta=1,
            )

        return {"review_id": review_id, "status": "visible"}


def list_reviews(
    *,
    entity_type: str,
    entity_id: int,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """List reviews for an entity with user names and rating summary."""
    with get_db_session() as session:
        # Rating summary
        summary_row = (
            session.query(MarketRatingSummary)
            .filter(
                MarketRatingSummary.entity_type == entity_type,
                MarketRatingSummary.entity_id == entity_id,
            )
            .first()
        )
        average_rating = float(summary_row.avg_rating) if summary_row and summary_row.avg_rating else 0.0
        total_reviews = int(summary_row.review_count) if summary_row else 0

        # Reviews with user info (join user_tenant_t for user_email/name)
        query = (
            session.query(MarketReview, UserTenant)
            .outerjoin(
                UserTenant,
                and_(
                    MarketReview.user_id == UserTenant.user_id,
                    UserTenant.delete_flag == "N",
                ),
            )
            .filter(
                MarketReview.entity_type == entity_type,
                MarketReview.entity_id == entity_id,
                MarketReview.delete_flag != "Y",
                MarketReview.status == "visible",
            )
            .order_by(desc(MarketReview.review_id))
        )

        total_count = query.count()
        offset = (page - 1) * page_size
        rows = query.offset(offset).limit(page_size).all()

        reviews = []
        for review, user_tenant in rows:
            user_name = "匿名用户"
            if user_tenant and user_tenant.user_email:
                user_name = user_tenant.user_email
            reviews.append({
                "id": int(review.review_id),
                "user_name": user_name,
                "rating": int(review.rating),
                "content": review.comment or "",
                "created_at": _serialize_dt(review.create_time),
            })

        return {
            "summary": {
                "average_rating": round(average_rating, 2),
                "total_reviews": total_reviews,
                "total_count": total_count,
            },
            "reviews": reviews,
        }


def get_rating_summary(entity_type: str, entity_id: int) -> Dict[str, Any]:
    """Get the rating summary for a single entity."""
    with get_db_session() as session:
        row = (
            session.query(MarketRatingSummary)
            .filter(
                MarketRatingSummary.entity_type == entity_type,
                MarketRatingSummary.entity_id == entity_id,
            )
            .first()
        )
        if not row:
            return {"average_rating": 0.0, "total_reviews": 0, "rating_count": 0}
        return {
            "average_rating": float(row.avg_rating) if row.avg_rating else 0.0,
            "total_reviews": int(row.review_count or 0),
            "rating_count": int(row.rating_count or 0),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_category_for_agent(
    row: AgentRepository,
    session,
) -> Optional[Dict[str, Any]]:
    """Resolve the category dict for an agent listing row."""
    if not row.category_id:
        return None
    try:
        # category_id is a VARCHAR; try numeric match against market_category_t.category_id
        cat_id_str = str(row.category_id)
        if cat_id_str.isdigit():
            cat_row = (
                session.query(MarketCategory)
                .filter(MarketCategory.category_id == int(cat_id_str))
                .first()
            )
            if cat_row:
                return {
                    "id": cat_row.category_id,
                    "name": cat_row.name,
                    "display_name": cat_row.display_name,
                    "display_name_zh": cat_row.display_name_zh,
                    "description": cat_row.description,
                    "description_zh": cat_row.description_zh,
                    "icon": cat_row.icon,
                    "sort_order": cat_row.sort_order or 0,
                    "created_at": _serialize_dt(cat_row.create_time),
                }
        # Fallback: category_id is a name string
        cat_row = (
            session.query(MarketCategory)
            .filter(MarketCategory.name == row.category_id)
            .first()
        )
        if cat_row:
            return {
                "id": cat_row.category_id,
                "name": cat_row.name,
                "display_name": cat_row.display_name,
                "display_name_zh": cat_row.display_name_zh,
                "description": cat_row.description,
                "description_zh": cat_row.description_zh,
                "icon": cat_row.icon,
                "sort_order": cat_row.sort_order or 0,
                "created_at": _serialize_dt(cat_row.create_time),
            }
    except Exception as exc:
        logger.debug("Failed to resolve category %s: %s", row.category_id, exc)
    return None


def _count_composition(agent_info_json: Any) -> tuple:
    """Count (agent_count, skill_count, mcp_count) from a frozen snapshot.

    A solution snapshot stores ``agent_info`` (dict of agents), ``skills``
    (list of SkillZipEntry), and ``mcp_info`` (list of MCPInfo). Returns zeros
    when the snapshot is missing/malformed so the listing never breaks.
    """
    if not isinstance(agent_info_json, dict):
        return 0, 0, 0
    agent_info = agent_info_json.get("agent_info")
    agent_count = len(agent_info) if isinstance(agent_info, dict) else 0
    skills = agent_info_json.get("skills")
    skill_count = len(skills) if isinstance(skills, list) else 0
    mcp_info = agent_info_json.get("mcp_info")
    mcp_count = len(mcp_info) if isinstance(mcp_info, list) else 0
    return agent_count, skill_count, mcp_count


def _format_tags(tags: Any) -> List[Dict[str, Any]]:
    """Format a PostgreSQL TEXT[] tags field into list of dicts."""
    if not tags:
        return []
    result = []
    for idx, tag in enumerate(tags, start=1):
        tag_str = str(tag) if tag else ""
        if not tag_str:
            continue
        result.append({
            "id": str(idx),
            "display_name": tag_str,
        })
    return result


def _serialize_dt(dt: Any) -> Optional[str]:
    """Serialize a datetime value to ISO string with 'Z' suffix for API consumers."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        iso = dt.isoformat()
        return iso if dt.tzinfo else iso + "Z"
    return str(dt)


def _adjust_rating_summary(
    session,
    entity_type: str,
    entity_id: int,
    *,
    old_rating: Optional[int],
    new_rating: Optional[int],
    review_delta: int,
) -> None:
    """Upsert and adjust the rating summary for an entity.

    Handles add (old=None, new=value), update (old=value, new=value),
    and remove (old=value, new=None).
    """
    row = (
        session.query(MarketRatingSummary)
        .filter(
            MarketRatingSummary.entity_type == entity_type,
            MarketRatingSummary.entity_id == entity_id,
        )
        .first()
    )

    if row is None:
        # Create new summary
        if new_rating is not None:
            new_row = MarketRatingSummary(
                entity_type=entity_type,
                entity_id=entity_id,
                avg_rating=new_rating,
                rating_count=1,
                review_count=max(review_delta, 0),
            )
            session.add(new_row)
    else:
        current_total = int(row.rating_count or 0)
        current_sum = float(row.avg_rating or 0) * current_total

        if old_rating is not None:
            current_sum -= old_rating
            current_total -= 1

        if new_rating is not None:
            current_sum += new_rating
            current_total += 1

        row.rating_count = max(current_total, 0)
        row.avg_rating = round(current_sum / current_total, 2) if current_total > 0 else 0.00
        row.review_count = max(int(row.review_count or 0) + review_delta, 0)
        session.flush()
