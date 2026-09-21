"""Database access for per-tenant official-agent visibility overrides."""

from sqlalchemy import delete

from database.client import get_db_session
from database.db_models import OfficialAgentTenantVisibility


def is_official_agent_hidden(agent_repository_id: int, tenant_id: str) -> bool:
    with get_db_session() as session:
        return session.query(OfficialAgentTenantVisibility.visibility_id).filter(
            OfficialAgentTenantVisibility.agent_repository_id == agent_repository_id,
            OfficialAgentTenantVisibility.tenant_id == tenant_id,
            OfficialAgentTenantVisibility.delete_flag != "Y",
        ).first() is not None


def set_official_agent_visibility(
    agent_repository_id: int,
    tenant_id: str,
    visible: bool,
    user_id: str,
) -> None:
    with get_db_session() as session:
        row = session.query(OfficialAgentTenantVisibility).filter(
            OfficialAgentTenantVisibility.agent_repository_id == agent_repository_id,
            OfficialAgentTenantVisibility.tenant_id == tenant_id,
        ).first()
        if visible:
            if row is not None and row.delete_flag != "Y":
                row.delete_flag = "Y"
                row.updated_by = user_id
            return
        if row is None:
            session.add(OfficialAgentTenantVisibility(
                agent_repository_id=agent_repository_id,
                tenant_id=tenant_id,
                created_by=user_id,
                updated_by=user_id,
                delete_flag="N",
            ))
        else:
            row.delete_flag = "N"
            row.updated_by = user_id


def list_hidden_official_agent_repository_ids(tenant_id: str) -> set[int]:
    with get_db_session() as session:
        rows = session.query(OfficialAgentTenantVisibility.agent_repository_id).filter(
            OfficialAgentTenantVisibility.tenant_id == tenant_id,
            OfficialAgentTenantVisibility.delete_flag != "Y",
        ).all()
        return {int(row[0]) for row in rows}


def delete_visibility_overrides(agent_repository_id: int) -> int:
    with get_db_session() as session:
        result = session.execute(
            delete(OfficialAgentTenantVisibility).where(
                OfficialAgentTenantVisibility.agent_repository_id == agent_repository_id,
            )
        )
        return int(result.rowcount or 0)
