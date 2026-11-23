"""Tenant-scoped persistence for document tag retrieval projections."""

from datetime import datetime, timezone
from typing import Any

from database.client import get_db_session
from database.db_models import DocumentTagProjection, ResourceTagAssignment
from sqlalchemy import and_, func, or_

ACTIVE_DELETE_FLAG = "N"
SYNCED_STATUS = "synced"
KNOWLEDGE_DOCUMENT_TYPE = "knowledge_document"


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


def list_synced_document_ids(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
) -> list[str]:
    with get_db_session() as session:
        rows = (
            session.query(DocumentTagProjection.resource_id)
            .filter(
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
                DocumentTagProjection.status == SYNCED_STATUS,
            )
            .all()
        )
        return [row[0] for row in rows]


def filter_document_ids_by_predicates(
    tenant_id: str,
    provider: str,
    knowledge_base_id: str,
    predicates: list[dict[str, Any]],
) -> list[str]:
    # predicates is a list of {"definition_id": int, "value_ids": [int]}.
    # A document matches when, for every predicate group, it has an active
    # assignment to one of that group's values (OR within a group), and groups
    # combine with AND. Only projection-confirmed (synced) documents match, so
    # retrieval never claims a tag filter succeeded while a provider
    # projection is pending or failed.

    effective = [
        predicate
        for predicate in predicates
        if predicate.get("value_ids")
    ]
    if not effective:
        return list_synced_document_ids(tenant_id, provider, knowledge_base_id)

    with get_db_session() as session:
        group_clauses = [
            and_(
                ResourceTagAssignment.definition_id == predicate["definition_id"],
                ResourceTagAssignment.value_id.in_(predicate["value_ids"]),
            )
            for predicate in effective
        ]
        rows = (
            session.query(ResourceTagAssignment.resource_id)
            .join(
                DocumentTagProjection,
                and_(
                    DocumentTagProjection.tenant_id == ResourceTagAssignment.tenant_id,
                    DocumentTagProjection.resource_id == ResourceTagAssignment.resource_id,
                ),
            )
            .filter(
                ResourceTagAssignment.tenant_id == tenant_id,
                ResourceTagAssignment.resource_type == KNOWLEDGE_DOCUMENT_TYPE,
                ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                DocumentTagProjection.tenant_id == tenant_id,
                DocumentTagProjection.provider == provider,
                DocumentTagProjection.knowledge_base_id == knowledge_base_id,
                DocumentTagProjection.status == SYNCED_STATUS,
                or_(*group_clauses),
            )
            .group_by(ResourceTagAssignment.resource_id)
            .having(func.count(func.distinct(ResourceTagAssignment.definition_id)) == len(effective))
            .all()
        )
        return [row[0] for row in rows]
