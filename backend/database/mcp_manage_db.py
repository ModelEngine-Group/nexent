import logging
from typing import Any, Dict, List

from database.client import as_dict, get_db_session
from database.db_models import McpServiceManage

logger = logging.getLogger("mcp_manage_db")


def create_mcp_manage_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    server_url: str,
    source_type: str,
    transport_type: str,
    tags: List[str] | None,
    category: str | None,
    config_json: Dict[str, Any] | None,
    enabled: bool,
    status: bool | None,
) -> None:
    with get_db_session() as session:
        new_record = McpServiceManage(
            tenant_id=tenant_id,
            user_id=user_id,
            mcp_name=name,
            mcp_server=server_url,
            source_type=source_type,
            transport_type=transport_type,
            tags=",".join(tags or []),
            category=category,
            config_json=config_json,
            enabled=enabled,
            status=status,
            created_by=user_id,
            updated_by=user_id,
            delete_flag="N",
        )
        session.add(new_record)


def get_mcp_manage_records(tenant_id: str) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        records = (
            session.query(McpServiceManage)
            .filter(
                McpServiceManage.tenant_id == tenant_id,
                McpServiceManage.delete_flag != "Y",
            )
            .order_by(McpServiceManage.update_time.desc())
            .all()
        )
        return [as_dict(record) for record in records]


def get_mcp_manage_record_by_name(*, tenant_id: str, name: str) -> Dict[str, Any] | None:
    with get_db_session() as session:
        record = (
            session.query(McpServiceManage)
            .filter(
                McpServiceManage.tenant_id == tenant_id,
                McpServiceManage.mcp_name == name,
                McpServiceManage.delete_flag != "Y",
            )
            .first()
        )
        return as_dict(record) if record else None


def check_mcp_manage_name_exists(*, tenant_id: str, name: str) -> bool:
    with get_db_session() as session:
        record = (
            session.query(McpServiceManage)
            .filter(
                McpServiceManage.tenant_id == tenant_id,
                McpServiceManage.mcp_name == name,
                McpServiceManage.delete_flag != "Y",
            )
            .first()
        )
        return record is not None


def update_mcp_manage_service(
    *,
    tenant_id: str,
    user_id: str,
    current_name: str,
    new_name: str,
    description: str | None,
    server_url: str,
    config_json: Dict[str, Any] | None,
    tags: List[str] | None,
) -> None:
    tag_value = ",".join(tags or [])
    with get_db_session() as session:
        session.query(McpServiceManage).filter(
            McpServiceManage.tenant_id == tenant_id,
            McpServiceManage.mcp_name == current_name,
            McpServiceManage.delete_flag != "Y",
        ).update(
            {
                "mcp_name": new_name,
                "mcp_server": server_url,
                "category": description,
                "config_json": config_json,
                "tags": tag_value,
                "updated_by": user_id,
            }
        )


def update_mcp_manage_enabled(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    enabled: bool,
) -> None:
    with get_db_session() as session:
        session.query(McpServiceManage).filter(
            McpServiceManage.tenant_id == tenant_id,
            McpServiceManage.mcp_name == name,
            McpServiceManage.delete_flag != "Y",
        ).update({"enabled": enabled, "updated_by": user_id})


def update_mcp_manage_status(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
    status: bool,
) -> None:
    with get_db_session() as session:
        session.query(McpServiceManage).filter(
            McpServiceManage.tenant_id == tenant_id,
            McpServiceManage.mcp_name == name,
            McpServiceManage.delete_flag != "Y",
        ).update({"status": status, "updated_by": user_id})


def delete_mcp_manage_service(
    *,
    tenant_id: str,
    user_id: str,
    name: str,
) -> None:
    with get_db_session() as session:
        session.query(McpServiceManage).filter(
            McpServiceManage.tenant_id == tenant_id,
            McpServiceManage.mcp_name == name,
            McpServiceManage.delete_flag != "Y",
        ).update({"delete_flag": "Y", "updated_by": user_id})
