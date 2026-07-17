"""Database repository for durable NL2AGENT session snapshots."""

from typing import Any, Dict, Optional

from database.client import as_dict, get_db_session
from database.db_models import Nl2AgentSession

NL2AGENT_SESSION_ACTIVE = "active"
NL2AGENT_SESSION_COMPLETED = "completed"
NL2AGENT_SESSION_ABANDONED = "abandoned"


def create_nl2agent_session(
    *,
    tenant_id: str,
    user_id: str,
    draft_agent_id: int,
    conversation_id: int,
    workflow_schema_version: int,
    workflow_state: Dict[str, Any],
    session_catalogs: Dict[str, Any],
    db_session=None,
) -> Dict[str, Any]:
    """Create the durable session row inside an optional caller transaction."""
    session_context = get_db_session(db_session) if db_session is not None else get_db_session()
    with session_context as session:
        record = Nl2AgentSession(
            tenant_id=tenant_id,
            user_id=user_id,
            draft_agent_id=draft_agent_id,
            conversation_id=conversation_id,
            status=NL2AGENT_SESSION_ACTIVE,
            workflow_schema_version=workflow_schema_version,
            workflow_revision=int(workflow_state.get("revision", 0)),
            catalog_revision=0,
            workflow_state=workflow_state,
            session_catalogs=session_catalogs,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(record)
        session.flush()
        return as_dict(record)


def get_nl2agent_session(
    tenant_id: str,
    draft_agent_id: int,
    *,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load one non-deleted session, optionally enforcing its owner."""
    with get_db_session() as session:
        query = session.query(Nl2AgentSession).filter(
            Nl2AgentSession.tenant_id == tenant_id,
            Nl2AgentSession.draft_agent_id == draft_agent_id,
            Nl2AgentSession.delete_flag != "Y",
        )
        if user_id is not None:
            query = query.filter(Nl2AgentSession.user_id == user_id)
        record = query.first()
        return as_dict(record) if record else None


def update_nl2agent_workflow_state(
    *,
    tenant_id: str,
    draft_agent_id: int,
    expected_revision: int,
    workflow_schema_version: int,
    workflow_state: Dict[str, Any],
    user_id: str,
) -> bool:
    """Replace workflow state iff the active row still has the expected revision."""
    next_revision = int(workflow_state.get("revision", -1))
    if next_revision != expected_revision + 1:
        raise ValueError("workflow_state revision must advance exactly once")
    with get_db_session() as session:
        updated = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.draft_agent_id == draft_agent_id,
                Nl2AgentSession.status == NL2AGENT_SESSION_ACTIVE,
                Nl2AgentSession.workflow_revision == expected_revision,
                Nl2AgentSession.delete_flag != "Y",
            )
            .update(
                {
                    "workflow_schema_version": workflow_schema_version,
                    "workflow_revision": next_revision,
                    "workflow_state": workflow_state,
                    "updated_by": user_id,
                },
                synchronize_session=False,
            )
        )
        return updated == 1


def update_nl2agent_session_catalogs(
    *,
    tenant_id: str,
    draft_agent_id: int,
    expected_revision: int,
    session_catalogs: Dict[str, Any],
    user_id: str,
) -> bool:
    """Replace catalogs iff the active row still has the expected revision."""
    with get_db_session() as session:
        updated = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.draft_agent_id == draft_agent_id,
                Nl2AgentSession.status == NL2AGENT_SESSION_ACTIVE,
                Nl2AgentSession.catalog_revision == expected_revision,
                Nl2AgentSession.delete_flag != "Y",
            )
            .update(
                {
                    "catalog_revision": expected_revision + 1,
                    "session_catalogs": session_catalogs,
                    "updated_by": user_id,
                },
                synchronize_session=False,
            )
        )
        return updated == 1


def update_nl2agent_session_status(
    *,
    tenant_id: str,
    draft_agent_id: int,
    status: str,
    user_id: str,
) -> bool:
    """Move an active session to one terminal lifecycle state."""
    if status not in {NL2AGENT_SESSION_COMPLETED, NL2AGENT_SESSION_ABANDONED}:
        raise ValueError("NL2AGENT session status must be terminal")
    with get_db_session() as session:
        updated = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.draft_agent_id == draft_agent_id,
                Nl2AgentSession.status == NL2AGENT_SESSION_ACTIVE,
                Nl2AgentSession.delete_flag != "Y",
            )
            .update(
                {"status": status, "updated_by": user_id},
                synchronize_session=False,
            )
        )
        return updated == 1
