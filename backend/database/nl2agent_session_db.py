"""Database repository for durable NL2AGENT session snapshots."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.client import as_dict, get_db_session
from database.db_models import (
    AgentInfo,
    AgentRelation,
    ConversationMessage,
    ConversationMessageUnit,
    ConversationRecord,
    ConversationSourceImage,
    ConversationSourceSearch,
    Nl2AgentCatalogSnapshot,
    Nl2AgentSession,
    SkillInstance,
    ToolInstance,
)
from utils.nl2agent_catalog_snapshot import catalog_snapshot_id

NL2AGENT_SESSION_ACTIVE = "active"
NL2AGENT_SESSION_COMPLETED = "completed"
NL2AGENT_SESSION_ABANDONED = "abandoned"


def _delete_orphan_catalog_snapshots(session, records: List[Nl2AgentSession]) -> int:
    """Soft-delete candidate snapshots that no live session still references."""
    candidates = {(record.tenant_id, record.catalog_snapshot_id) for record in records}
    if not candidates:
        return 0
    candidate_filter = or_(
        *(
            and_(
                Nl2AgentCatalogSnapshot.tenant_id == tenant_id,
                Nl2AgentCatalogSnapshot.snapshot_id == snapshot_id,
            )
            for tenant_id, snapshot_id in candidates
        )
    )
    live_reference = (
        session.query(Nl2AgentSession.session_id)
        .filter(
            Nl2AgentSession.tenant_id == Nl2AgentCatalogSnapshot.tenant_id,
            Nl2AgentSession.catalog_snapshot_id == Nl2AgentCatalogSnapshot.snapshot_id,
            Nl2AgentSession.delete_flag != "Y",
        )
        .exists()
    )
    return (
        session.query(Nl2AgentCatalogSnapshot)
        .filter(
            candidate_filter,
            ~live_reference,
            Nl2AgentCatalogSnapshot.delete_flag != "Y",
        )
        .update(
            {"delete_flag": "Y", "updated_by": "nl2agent_cleanup"},
            synchronize_session=False,
        )
    )


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
    session_context = (
        get_db_session(db_session) if db_session is not None else get_db_session()
    )
    with session_context as session:
        snapshot_id = catalog_snapshot_id(session_catalogs)
        snapshot_insert = pg_insert(Nl2AgentCatalogSnapshot).values(
            tenant_id=tenant_id,
            snapshot_id=snapshot_id,
            schema_version=1,
            catalogs=session_catalogs,
            created_by=user_id,
            updated_by=user_id,
            delete_flag="N",
        )
        session.execute(
            snapshot_insert.on_conflict_do_update(
                index_elements=["tenant_id", "snapshot_id"],
                set_={
                    "schema_version": snapshot_insert.excluded.schema_version,
                    "catalogs": snapshot_insert.excluded.catalogs,
                    "updated_by": user_id,
                    "delete_flag": "N",
                },
            )
        )
        record = Nl2AgentSession(
            tenant_id=tenant_id,
            user_id=user_id,
            draft_agent_id=draft_agent_id,
            conversation_id=conversation_id,
            status=NL2AGENT_SESSION_ACTIVE,
            workflow_schema_version=workflow_schema_version,
            workflow_revision=int(workflow_state.get("revision", 0)),
            catalog_snapshot_id=snapshot_id,
            workflow_state=workflow_state,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(record)
        session.flush()
        return as_dict(record)


def get_nl2agent_session_snapshot(
    tenant_id: str,
    draft_agent_id: int,
) -> Optional[Dict[str, Any]]:
    """Load a session together with its shared immutable catalog payload."""
    with get_db_session() as session:
        record = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.draft_agent_id == draft_agent_id,
                Nl2AgentSession.delete_flag != "Y",
            )
            .first()
        )
        if record is None:
            return None
        snapshot = (
            session.query(Nl2AgentCatalogSnapshot)
            .filter(
                Nl2AgentCatalogSnapshot.tenant_id == tenant_id,
                Nl2AgentCatalogSnapshot.snapshot_id == record.catalog_snapshot_id,
                Nl2AgentCatalogSnapshot.delete_flag != "Y",
            )
            .first()
        )
        if snapshot is None:
            return None
        result = as_dict(record)
        result["catalog_snapshot"] = as_dict(snapshot)["catalogs"]
        return result


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


def get_nl2agent_session_by_conversation(
    tenant_id: str,
    user_id: str,
    conversation_id: int,
    *,
    status: Optional[str] = NL2AGENT_SESSION_ACTIVE,
) -> Optional[Dict[str, Any]]:
    """Load one owner-scoped session by its conversation."""
    with get_db_session() as session:
        query = session.query(Nl2AgentSession).filter(
            Nl2AgentSession.tenant_id == tenant_id,
            Nl2AgentSession.user_id == user_id,
            Nl2AgentSession.conversation_id == conversation_id,
            Nl2AgentSession.delete_flag != "Y",
        )
        if status is not None:
            query = query.filter(Nl2AgentSession.status == status)
        record = query.first()
        return as_dict(record) if record else None


def list_nl2agent_sessions(
    tenant_id: str,
    user_id: str,
    *,
    status: str = NL2AGENT_SESSION_ACTIVE,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List recent owner-scoped sessions with a bounded result size."""
    bounded_limit = max(1, min(100, int(limit)))
    with get_db_session() as session:
        records = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.user_id == user_id,
                Nl2AgentSession.status == status,
                Nl2AgentSession.delete_flag != "Y",
            )
            .order_by(Nl2AgentSession.update_time.desc())
            .limit(bounded_limit)
            .all()
        )
        return [as_dict(record) for record in records]


def update_nl2agent_workflow_state(
    *,
    tenant_id: str,
    draft_agent_id: int,
    expected_revision: int,
    workflow_schema_version: int,
    workflow_state: Dict[str, Any],
    user_id: Optional[str] = None,
) -> bool:
    """Replace workflow state iff the active row still has the expected revision."""
    next_revision = int(workflow_state.get("revision", -1))
    if next_revision != expected_revision + 1:
        raise ValueError("workflow_state revision must advance exactly once")
    with get_db_session() as session:
        values = {
            "workflow_schema_version": workflow_schema_version,
            "workflow_revision": next_revision,
            "workflow_state": workflow_state,
        }
        if user_id is not None:
            values["updated_by"] = user_id
        updated = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.draft_agent_id == draft_agent_id,
                Nl2AgentSession.status == NL2AGENT_SESSION_ACTIVE,
                Nl2AgentSession.workflow_revision == expected_revision,
                Nl2AgentSession.delete_flag != "Y",
            )
            .update(values, synchronize_session=False)
        )
        return updated == 1


def cleanup_abandoned_nl2agent_sessions(
    *,
    abandoned_before: datetime,
    limit: int,
) -> int:
    """Soft-delete a bounded batch of abandoned sessions and their draft roots."""
    bounded_limit = max(1, min(500, int(limit)))
    with get_db_session() as session:
        records = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.status == NL2AGENT_SESSION_ABANDONED,
                Nl2AgentSession.update_time < abandoned_before,
                Nl2AgentSession.delete_flag != "Y",
            )
            .order_by(Nl2AgentSession.update_time.asc())
            .with_for_update(skip_locked=True)
            .limit(bounded_limit)
            .all()
        )
        if not records:
            return 0

        draft_agent_ids = [record.draft_agent_id for record in records]
        conversation_ids = [record.conversation_id for record in records]
        session.query(AgentInfo).filter(
            AgentInfo.agent_id.in_(draft_agent_ids),
            AgentInfo.version_no == 0,
            AgentInfo.name.like("draft_%"),
            AgentInfo.delete_flag != "Y",
        ).update(
            {"delete_flag": "Y", "updated_by": "nl2agent_cleanup"},
            synchronize_session=False,
        )
        for model in (ToolInstance, SkillInstance):
            session.query(model).filter(
                model.agent_id.in_(draft_agent_ids),
                model.delete_flag != "Y",
            ).update(
                {"delete_flag": "Y", "updated_by": "nl2agent_cleanup"},
                synchronize_session=False,
            )
        session.query(AgentRelation).filter(
            or_(
                AgentRelation.parent_agent_id.in_(draft_agent_ids),
                AgentRelation.selected_agent_id.in_(draft_agent_ids),
            ),
            AgentRelation.delete_flag != "Y",
        ).update(
            {"delete_flag": "Y", "updated_by": "nl2agent_cleanup"},
            synchronize_session=False,
        )
        for model in (
            ConversationRecord,
            ConversationMessage,
            ConversationMessageUnit,
            ConversationSourceSearch,
            ConversationSourceImage,
        ):
            session.query(model).filter(
                model.conversation_id.in_(conversation_ids),
                model.delete_flag != "Y",
            ).update(
                {"delete_flag": "Y", "updated_by": "nl2agent_cleanup"},
                synchronize_session=False,
            )
        for record in records:
            record.delete_flag = "Y"
            record.updated_by = "nl2agent_cleanup"
        session.flush()
        _delete_orphan_catalog_snapshots(session, records)
        return len(records)


def abandon_stale_active_nl2agent_sessions(
    *, active_before: datetime, limit: int
) -> int:
    """Move a bounded batch of inactive active sessions to abandoned."""
    bounded_limit = max(1, min(500, int(limit)))
    with get_db_session() as session:
        records = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.status == NL2AGENT_SESSION_ACTIVE,
                Nl2AgentSession.update_time < active_before,
                Nl2AgentSession.delete_flag != "Y",
            )
            .order_by(Nl2AgentSession.update_time.asc())
            .with_for_update(skip_locked=True)
            .limit(bounded_limit)
            .all()
        )
        for record in records:
            record.status = NL2AGENT_SESSION_ABANDONED
            record.updated_by = "nl2agent_cleanup"
        return len(records)


def cleanup_completed_nl2agent_sessions(
    *, completed_before: datetime, limit: int
) -> int:
    """Prune completed workflow rows and release unreferenced catalog snapshots."""
    bounded_limit = max(1, min(500, int(limit)))
    with get_db_session() as session:
        records = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.status == NL2AGENT_SESSION_COMPLETED,
                Nl2AgentSession.update_time < completed_before,
                Nl2AgentSession.delete_flag != "Y",
            )
            .order_by(Nl2AgentSession.update_time.asc())
            .with_for_update(skip_locked=True)
            .limit(bounded_limit)
            .all()
        )
        if not records:
            return 0
        for record in records:
            record.delete_flag = "Y"
            record.updated_by = "nl2agent_cleanup"
        session.flush()
        _delete_orphan_catalog_snapshots(session, records)
        return len(records)


def update_nl2agent_session_status(
    *,
    tenant_id: str,
    draft_agent_id: int,
    status: str,
    user_id: str,
    db_session=None,
) -> bool:
    """Move an active session to one terminal lifecycle state."""
    if status not in {NL2AGENT_SESSION_COMPLETED, NL2AGENT_SESSION_ABANDONED}:
        raise ValueError("NL2AGENT session status must be terminal")
    session_context = (
        get_db_session(db_session) if db_session is not None else get_db_session()
    )
    with session_context as session:
        updated = (
            session.query(Nl2AgentSession)
            .filter(
                Nl2AgentSession.tenant_id == tenant_id,
                Nl2AgentSession.draft_agent_id == draft_agent_id,
                Nl2AgentSession.user_id == user_id,
                Nl2AgentSession.status == NL2AGENT_SESSION_ACTIVE,
                Nl2AgentSession.delete_flag != "Y",
            )
            .update(
                {"status": status, "updated_by": user_id},
                synchronize_session=False,
            )
        )
        return updated == 1
