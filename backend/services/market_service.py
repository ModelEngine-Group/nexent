"""Unified market service — business orchestration layer.

Translates database results into the frontend API response format,
and bridges between the agent repository snapshot and the recipe/template page.
"""

import logging
from typing import Any, Dict, List, Optional

from database import market_db
from services.recipe_service import extract_recipe_from_snapshot

logger = logging.getLogger("market_service")

# Entity type used for reviews/ratings on agent listings
_AGENT_ENTITY_TYPE = "agent"


def list_market_agents_impl(
    *,
    page: int = 1,
    page_size: int = 20,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "latest",
    source: Optional[str] = None,
    lang: str = "zh",
) -> Dict[str, Any]:
    """List market agents and assemble the frontend list response.

    Returns ``{items, pagination, featured_items}``.
    """
    result = market_db.list_market_agents(
        page=page,
        page_size=page_size,
        category=category,
        tag=tag,
        search=search,
        sort=sort,
        source=source,
    )

    items = result["items"]
    total = result["total"]

    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

    # Resolve localized category display_name based on lang
    for item in items:
        _localize_category(item.get("category"), lang)

    # Featured items
    featured_items = market_db.list_featured_agents(limit=6)

    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
        "featured_items": featured_items,
    }


def get_market_agent_detail_impl(
    agent_repository_id: int,
    tenant_id: str,
    lang: str = "zh",
) -> Dict[str, Any]:
    """Load a market agent detail and assemble the frontend detail response.

    Parses ``agent_info_json`` to extract tools, mcp_servers, duty_prompt, etc.
    Also attaches a ``recipe`` field for the template detail page.
    """
    record = market_db.get_market_agent_detail(agent_repository_id)
    if not record:
        raise ValueError("Market agent listing not found")

    agent_info_json = record.get("agent_info_json")
    root_agent = _extract_root_agent_from_snapshot(agent_info_json)

    # Extract tools from snapshot
    tools = _extract_tools_from_snapshot(root_agent)

    # Extract mcp_servers from snapshot
    mcp_servers = _extract_mcp_servers_from_snapshot(agent_info_json)

    # Build category dict
    category = None
    category_id = record.get("category_id")
    if category_id:
        categories = market_db.list_categories(entity_type=_AGENT_ENTITY_TYPE)
        for cat in categories:
            if str(cat.get("id")) == str(category_id) or cat.get("name") == category_id:
                category = cat
                break
        _localize_category(category, lang)

    # Tags
    tags = _format_tags(record.get("tags"))

    # Rating summary
    rating_summary = market_db.get_rating_summary(_AGENT_ENTITY_TYPE, agent_repository_id)

    # Recipe field for template detail page
    recipe = extract_recipe_from_snapshot(agent_info_json, root_agent)

    # Build detail response
    detail = {
        "id": record.get("agent_repository_id"),
        "agent_id": record.get("agent_id"),
        "name": record.get("name"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "author": record.get("author"),
        "category": category,
        "tags": tags,
        "download_count": record.get("downloads") or 0,
        "is_featured": record.get("is_featured") or False,
        "created_at": _serialize_dt(record.get("create_time")),
        "icon": record.get("icon"),
        "source": record.get("source") or "community",
        "is_official_template": record.get("is_official_template") or False,
        # Extended fields from snapshot
        "business_description": root_agent.get("business_description", ""),
        "max_steps": root_agent.get("max_steps", 20),
        "provide_run_summary": root_agent.get("provide_run_summary", True),
        "duty_prompt": root_agent.get("duty_prompt", ""),
        "constraint_prompt": root_agent.get("constraint_prompt", ""),
        "few_shots_prompt": root_agent.get("few_shots_prompt", ""),
        "enabled": root_agent.get("enabled", True),
        "model_id": _first_or_none(root_agent.get("model_ids")),
        "model_name": _first_or_none(root_agent.get("model_names")),
        "business_logic_model_id": root_agent.get("business_logic_model_id"),
        "business_logic_model_name": root_agent.get("business_logic_model_name"),
        "tools": tools,
        "mcp_servers": mcp_servers,
        "updated_at": _serialize_dt(record.get("update_time")),
        "agent_json": agent_info_json if isinstance(agent_info_json, dict) else {},
        # Template detail fields
        "default_init_prompt": record.get("default_init_prompt"),
        "quick_prompts": record.get("quick_prompts"),
        "members_info": record.get("members_info"),
        "expert_type": record.get("expert_type") or "agent",
        # Recipe for template detail page
        "recipe": recipe,
        # Rating
        "average_rating": rating_summary.get("average_rating", 0.0),
        "total_reviews": rating_summary.get("total_reviews", 0),
    }

    return detail


def list_categories_impl(
    lang: str = "zh",
    entity_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List categories with localized display name."""
    categories = market_db.list_categories(entity_type=entity_type)
    for cat in categories:
        _localize_category(cat, lang)
    return categories


def list_tags_impl() -> List[Dict[str, Any]]:
    """List all market tags with usage counts."""
    return market_db.list_tags()


def get_agent_mcp_servers_impl(agent_repository_id: int) -> List[Dict[str, Any]]:
    """Extract mcp_info from the agent snapshot for the mcp_servers endpoint."""
    record = market_db.get_market_agent_detail(agent_repository_id)
    if not record:
        raise ValueError("Market agent listing not found")
    return _extract_mcp_servers_from_snapshot(record.get("agent_info_json"))


def create_review_impl(
    agent_repository_id: int,
    *,
    rating: int,
    comment: str,
    user_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """Create or update a review for a market agent listing."""
    # Verify the listing exists
    record = market_db.get_market_agent_detail(agent_repository_id)
    if not record:
        raise ValueError("Market agent listing not found")

    return market_db.create_review(
        entity_type=_AGENT_ENTITY_TYPE,
        entity_id=agent_repository_id,
        tenant_id=tenant_id,
        user_id=user_id,
        rating=rating,
        comment=comment,
    )


def list_reviews_impl(
    agent_repository_id: int,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """List reviews for a market agent listing with summary."""
    # Verify the listing exists
    record = market_db.get_market_agent_detail(agent_repository_id)
    if not record:
        raise ValueError("Market agent listing not found")

    return market_db.list_reviews(
        entity_type=_AGENT_ENTITY_TYPE,
        entity_id=agent_repository_id,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _extract_tools_from_snapshot(root_agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract and format tools from a root agent snapshot entry."""
    tools: List[Dict[str, Any]] = []
    raw_tools = root_agent.get("tools")
    if not isinstance(raw_tools, list):
        return tools
    for tool in raw_tools:
        if not isinstance(tool, dict):
            continue
        tools.append({
            "id": tool.get("id"),
            "class_name": tool.get("class_name", ""),
            "name": tool.get("name", tool.get("origin_name", "")),
            "description": tool.get("description", ""),
            "output_type": tool.get("output_type", "str"),
            "params": tool.get("params", {}),
            "source": tool.get("source", "local"),
            "usage": tool.get("usage"),
            "tool_metadata": tool.get("tool_metadata"),
        })
    return tools


def _extract_mcp_servers_from_snapshot(agent_info_json: Any) -> List[Dict[str, Any]]:
    """Extract mcp_info list from the snapshot."""
    if not isinstance(agent_info_json, dict):
        return []
    mcp_info = agent_info_json.get("mcp_info")
    if not isinstance(mcp_info, list):
        return []
    result = []
    for mcp in mcp_info:
        if not isinstance(mcp, dict):
            continue
        result.append({
            "id": mcp.get("id", 0),
            "mcp_server_name": mcp.get("mcp_server_name", ""),
            "mcp_url": mcp.get("mcp_url", ""),
        })
    return result


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


def _localize_category(category: Optional[Dict[str, Any]], lang: str) -> None:
    """Add a ``display_label`` field to the category dict based on lang.

    The ``name`` field always keeps the programmatic name. The frontend
    can use ``display_name`` / ``display_name_zh`` for localized display.
    This helper adds a convenience ``display_label`` field.
    """
    if not category or not isinstance(category, dict):
        return
    if lang == "zh":
        category["display_label"] = category.get("display_name_zh") or category.get("display_name") or category.get("name", "")
    else:
        category["display_label"] = category.get("display_name") or category.get("display_name_zh") or category.get("name", "")


def _first_or_none(lst: Any) -> Any:
    """Return the first element of a list, or None if empty/None."""
    if isinstance(lst, list) and len(lst) > 0:
        return lst[0]
    return None


def _serialize_dt(dt: Any) -> Optional[str]:
    """Serialize a datetime value to ISO string with 'Z' suffix."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        iso = dt.isoformat()
        # Naive datetime (no tzinfo) gets a 'Z' suffix for API consumers
        tz = getattr(dt, "tzinfo", None)
        return iso if tz else iso + "Z"
    return str(dt)
