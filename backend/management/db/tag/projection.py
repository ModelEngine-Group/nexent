# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tenant-scoped persistence for document tag retrieval projections."""

from datetime import datetime, timezone
from typing import Any

from infrastructure.rdb.client import get_db_session
from management.db.models import DocumentTagProjection
from sqlalchemy import or_


def _state_data(record: DocumentTagProjection) -> dict[str, Any]:
    return {
        "tenant_id": record.tenant_id,
        "provider": record.provider,
        "knowledge_base_id": record.knowledge_base_id,
        "provider_document_id": record.provider_document_id,
        "resource_id": record.resource_id,
        "status": record.status,
        "version": record.version,
        "payload": record.payload,
        "retry_count": record.retry_count,
        "last_error": record.last_error,
        "last_attempt_at": record.last_attempt_at,
        "next_attempt_at": record.next_attempt_at,
        "create_time": record.create_time,
        "update_time": record.update_time,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
    }


def get_projection_state(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
) -> dict[str, Any] | None:
    with get_db_session() as session:
        record = (
            session.query(DocumentTagProjection)
            .filter(
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
                DocumentTagProjection.provider_document_id == provider_document_id,
            )
            .first()
        )
        return _state_data(record) if record is not None else None


def upsert_projection_state(
    *,
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
    resource_id: str,
    status: str,
    version: int,
    payload: list[dict[str, Any]],
    retry_count: int | None = None,
    last_error: str | None = None,
    last_attempt_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Idempotently upsert one document projection state row."""

    with get_db_session() as session:
        record = (
            session.query(DocumentTagProjection)
            .filter(
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
                DocumentTagProjection.provider_document_id == provider_document_id,
            )
            .first()
        )
        if record is None:
            record = DocumentTagProjection(
                tenant_id=tenant_id,
                provider=provider,
                knowledge_base_id=knowledge_base_id,
                provider_document_id=provider_document_id,
                resource_id=resource_id,
                status=status,
                version=version,
                payload=payload,
                retry_count=retry_count or 0,
                last_error=last_error,
                last_attempt_at=last_attempt_at,
                next_attempt_at=next_attempt_at,
                created_by=actor_id,
                updated_by=actor_id,
            )
            session.add(record)
        else:
            record.status = status
            record.version = version
            record.payload = payload
            record.last_error = last_error
            record.last_attempt_at = last_attempt_at
            record.next_attempt_at = next_attempt_at
            if retry_count is not None:
                record.retry_count = retry_count
            if actor_id is not None:
                record.updated_by = actor_id
        session.flush()
        return _state_data(record)


def delete_projection_state(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    provider_document_id: str,
) -> bool:
    with get_db_session() as session:
        deleted = (
            session.query(DocumentTagProjection)
            .filter(
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
                DocumentTagProjection.provider_document_id == provider_document_id,
            )
            .delete()
        )
        return bool(deleted)


def delete_projection_states_for_knowledge_base(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
) -> int:
    with get_db_session() as session:
        deleted = (
            session.query(DocumentTagProjection)
            .filter(
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
            )
            .delete()
        )
        return int(deleted or 0)


def list_projection_states_for_knowledge_base(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
) -> dict[str, dict[str, Any]]:
    """Return projection states keyed by provider document id for one knowledge base."""

    with get_db_session() as session:
        rows = (
            session.query(DocumentTagProjection)
            .filter(
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
            )
            .all()
        )
        return {record.provider_document_id: _state_data(record) for record in rows}


def list_due_projection_states(
    tenant_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    with get_db_session() as session:
        query = session.query(DocumentTagProjection).filter(
            DocumentTagProjection.status.in_(("pending", "failed")),
            or_(
                DocumentTagProjection.next_attempt_at.is_(None),
                DocumentTagProjection.next_attempt_at <= now,
            ),
        )
        if tenant_id:
            query = query.filter(DocumentTagProjection.tenant_id == tenant_id)
        query = query.order_by(DocumentTagProjection.update_time.asc()).limit(limit)
        return [_state_data(record) for record in query.all()]
