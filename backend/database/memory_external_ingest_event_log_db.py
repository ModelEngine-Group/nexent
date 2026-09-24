from typing import Any, Dict, List, Optional

from database.client import filter_property, get_db_session
from database.db_models import MemoryExternalIngestEventLog


def _to_dict(item: MemoryExternalIngestEventLog) -> Dict[str, Any]:
    return {
        "log_id": item.log_id,
        "provider": item.provider,
        "tenant_id": item.tenant_id,
        "user_id": item.user_id,
        "agent_id": item.agent_id,
        "conversation_id": item.conversation_id,
        "event_id": item.event_id,
        "idempotency_key": item.idempotency_key,
        "unit_ids": item.unit_ids,
        "response_status": item.response_status,
        "response_summary": item.response_summary,
        "sent_at": item.sent_at,
        "create_time": item.create_time,
    }


def insert_event_log(data: Dict[str, Any]) -> Optional[int]:
    with get_db_session() as session:
        try:
            data = filter_property(data, MemoryExternalIngestEventLog)
            obj = MemoryExternalIngestEventLog(**data)
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj.log_id
        except Exception:
            session.rollback()
            return None


def get_event_log_by_idempotency(idempotency_key: str) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        item = session.query(MemoryExternalIngestEventLog).filter(
            MemoryExternalIngestEventLog.idempotency_key == idempotency_key,
            MemoryExternalIngestEventLog.delete_flag == "N",
        ).first()
        return _to_dict(item) if item else None


def list_event_logs(
    tenant_id: str,
    user_id: str = None,
    agent_id: str = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        query = session.query(MemoryExternalIngestEventLog).filter(
            MemoryExternalIngestEventLog.tenant_id == tenant_id,
            MemoryExternalIngestEventLog.delete_flag == "N",
        )
        if user_id is not None:
            query = query.filter(MemoryExternalIngestEventLog.user_id == user_id)
        if agent_id is not None:
            query = query.filter(MemoryExternalIngestEventLog.agent_id == agent_id)
        result = query.order_by(
            MemoryExternalIngestEventLog.sent_at.desc()
        ).limit(limit).all()
        return [_to_dict(item) for item in result]
