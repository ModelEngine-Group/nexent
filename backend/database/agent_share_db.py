"""Persistence helpers for login-gated Agent sharing."""

from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import select, text, update

from database.client import as_dict, filter_property, get_db_session
from database.db_models import AgentShare, AgentShareSession, ConversationRecord


def create_agent_share(
    share_data: Dict[str, Any],
    *,
    manager_user_id: str,
) -> Dict[str, Any]:
    """Persist one active Agent share with manager-owned audit fields."""
    with get_db_session() as session:
        payload = filter_property(share_data, AgentShare)
        payload.update(
            {
                "status": "active",
                "delete_flag": "N",
                "created_by": manager_user_id,
                "updated_by": manager_user_id,
            }
        )
        record = AgentShare(**payload)
        session.add(record)
        session.flush()
        session.refresh(record)
        return as_dict(record)


def get_active_agent_share(tenant_id: str, agent_id: int) -> Optional[Dict[str, Any]]:
    """Return the single active share owned by a tenant Agent."""
    with get_db_session() as session:
        statement = select(AgentShare).where(
            AgentShare.tenant_id == tenant_id,
            AgentShare.agent_id == agent_id,
            AgentShare.status == "active",
            AgentShare.delete_flag == "N",
        )
        record = session.scalars(statement).first()
        return None if record is None else as_dict(record)


def get_agent_share_by_public_id(public_share_id: str) -> Optional[Dict[str, Any]]:
    """Resolve an active share record by its non-secret public id."""
    with get_db_session() as session:
        statement = select(AgentShare).where(
            AgentShare.public_share_id == public_share_id,
            AgentShare.status == "active",
            AgentShare.delete_flag == "N",
        )
        record = session.scalars(statement).first()
        return None if record is None else as_dict(record)


def get_agent_share_session(*, agent_share_id: int, visitor_user_id: str) -> Optional[Dict[str, Any]]:
    """Return one visitor's active session without creating a conversation."""
    with get_db_session() as session:
        statement = select(AgentShareSession).where(
            AgentShareSession.agent_share_id == agent_share_id,
            AgentShareSession.visitor_user_id == visitor_user_id,
            AgentShareSession.delete_flag == "N",
        )
        record = session.scalars(statement).first()
        return None if record is None else as_dict(record)


def get_or_create_agent_share_session(
    *,
    agent_share_id: int,
    visitor_user_id: str,
    agent_id: int,
    agent_version_no: int,
) -> Dict[str, Any]:
    """Atomically create one hidden conversation for each share and user pair."""
    with get_db_session() as session:
        lock_key = f"agent-share-session:{agent_share_id}:{visitor_user_id}"
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
        existing = session.scalars(
            select(AgentShareSession).where(
                AgentShareSession.agent_share_id == agent_share_id,
                AgentShareSession.visitor_user_id == visitor_user_id,
                AgentShareSession.delete_flag == "N",
            )
        ).first()
        if existing is not None:
            return as_dict(existing)

        conversation = ConversationRecord(
            conversation_title="Shared Agent",
            agent_id=agent_id,
            is_agent_share=True,
            chat_mode="execution",
            created_by=visitor_user_id,
            updated_by=visitor_user_id,
            delete_flag="N",
        )
        session.add(conversation)
        session.flush()
        record = AgentShareSession(
            share_session_id=str(uuid4()),
            agent_share_id=agent_share_id,
            visitor_user_id=visitor_user_id,
            conversation_id=conversation.conversation_id,
            agent_version_no=agent_version_no,
            created_by=visitor_user_id,
            updated_by=visitor_user_id,
            delete_flag="N",
        )
        session.add(record)
        session.flush()
        session.refresh(record)
        return as_dict(record)


def revoke_agent_share(agent_share_id: int, manager_user_id: str) -> bool:
    """Revoke an active share only when it belongs to the managing user."""
    with get_db_session() as session:
        statement = (
            update(AgentShare)
            .where(
                AgentShare.agent_share_id == agent_share_id,
                AgentShare.owner_user_id == manager_user_id,
                AgentShare.status == "active",
                AgentShare.delete_flag == "N",
            )
            .values(status="revoked", updated_by=manager_user_id)
        )
        return session.execute(statement).rowcount > 0


def rotate_agent_share(agent_share_id: int, *, manager_user_id: str, token_nonce: str) -> bool:
    """Invalidate existing links by advancing the generation under owner scope."""
    with get_db_session() as session:
        statement = (
            update(AgentShare)
            .where(
                AgentShare.agent_share_id == agent_share_id,
                AgentShare.owner_user_id == manager_user_id,
                AgentShare.status == "active",
                AgentShare.delete_flag == "N",
            )
            .values(
                token_generation=AgentShare.token_generation + 1,
                token_nonce=token_nonce,
                updated_by=manager_user_id,
            )
        )
        return session.execute(statement).rowcount > 0
