import logging
from typing import Any, Dict, List

from sqlalchemy import or_

from database.client import as_dict, filter_property, get_db_session
from database.db_models import McpCommunityRecord

logger = logging.getLogger("community_mcp_db")


def get_mcp_community_records(
    *,
    search: str | None = None,
    transport_type: str | None = None,
    cursor: str | None = None,
    limit: int = 30,
) -> Dict[str, Any]:
    with get_db_session() as session:
        query = session.query(McpCommunityRecord).filter(
            McpCommunityRecord.delete_flag != "Y"
        )

        if transport_type:
            query = query.filter(McpCommunityRecord.transport_type == transport_type)

        if search:
            keyword = f"%{search}%"
            query = query.filter(
                or_(
                    McpCommunityRecord.mcp_name.ilike(keyword),
                    McpCommunityRecord.description.ilike(keyword),
                    McpCommunityRecord.tags.ilike(keyword),
                )
            )

        cursor_id: int | None = None
        if cursor:
            try:
                cursor_id = int(cursor)
            except ValueError:
                cursor_id = None

        if cursor_id is not None:
            query = query.filter(McpCommunityRecord.community_id < cursor_id)

        rows: List[McpCommunityRecord] = (
            query.order_by(McpCommunityRecord.community_id.desc())
            .limit(limit + 1)
            .all()
        )

        has_next = len(rows) > limit
        page_rows = rows[:limit]

        next_cursor = None
        if has_next and page_rows:
            next_cursor = str(page_rows[-1].community_id)

        return {
            "count": len(page_rows),
            "nextCursor": next_cursor,
            "items": [as_dict(row) for row in page_rows],
        }


def create_mcp_community_record(mcp_data: Dict[str, Any], tenant_id: str, user_id: str) -> int:
    with get_db_session() as session:
        mcp_data.update({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_by": user_id,
            "updated_by": user_id,
            "delete_flag": "N",
            "source": "community",
        })
        new_record = McpCommunityRecord(**filter_property(mcp_data, McpCommunityRecord))
        session.add(new_record)
        session.flush()
        return int(new_record.community_id)


def get_mcp_community_record_by_id_and_tenant(community_id: int, tenant_id: str) -> Dict[str, Any] | None:
    with get_db_session() as session:
        record = session.query(McpCommunityRecord).filter(
            McpCommunityRecord.community_id == community_id,
            McpCommunityRecord.tenant_id == tenant_id,
            McpCommunityRecord.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def update_mcp_community_record_by_id(
    *,
    community_id: int,
    tenant_id: str,
    user_id: str,
    name: str | None = None,
    description: str | None = None,
    tags: List[str] | None = None,
    version: str | None = None,
    registry_json: Dict[str, Any] | None = None,
    config_json: Dict[str, Any] | None = None,
) -> None:
    update_fields: Dict[str, Any] = {"updated_by": user_id}

    if name is not None:
        update_fields["mcp_name"] = name
    if description is not None:
        update_fields["description"] = description
    if tags is not None:
        update_fields["tags"] = ",".join(tags)
    if version is not None:
        update_fields["version"] = version
    if registry_json is not None:
        update_fields["registry_json"] = registry_json
    if config_json is not None:
        update_fields["config_json"] = config_json

    with get_db_session() as session:
        session.query(McpCommunityRecord).filter(
            McpCommunityRecord.community_id == community_id,
            McpCommunityRecord.tenant_id == tenant_id,
            McpCommunityRecord.delete_flag != "Y",
        ).update(update_fields)


def delete_mcp_community_record_by_id(*, community_id: int, tenant_id: str, user_id: str) -> None:
    with get_db_session() as session:
        session.query(McpCommunityRecord).filter(
            McpCommunityRecord.community_id == community_id,
            McpCommunityRecord.tenant_id == tenant_id,
            McpCommunityRecord.delete_flag != "Y",
        ).update({"delete_flag": "Y", "updated_by": user_id})


def list_mcp_community_records_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        rows = session.query(McpCommunityRecord).filter(
            McpCommunityRecord.tenant_id == tenant_id,
            McpCommunityRecord.delete_flag != "Y",
        ).order_by(McpCommunityRecord.community_id.desc()).all()
        return [as_dict(row) for row in rows]
