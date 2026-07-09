"""
Knowledge base document record CRUD operations.

Provides persistence for the kb_document_record_t table introduced in Phase 2
of the V4 standard API. All document lifecycle events (upload, status changes,
deletion) are tracked here so the standard API endpoints no longer need to
call ES list_files as primary source of truth.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from database.client import as_dict, get_db_session
from database.db_models import KnowledgeDocumentRecord

logger = logging.getLogger("document_db")


def _new_uuid() -> str:
    return uuid.uuid4().hex


def create_document_record(
    knowledge_id: int,
    tenant_id: str,
    source_uri: str,
    filename: str,
    file_size: Optional[int] = None,
    celery_task_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Insert a new document record with status=indexing.

    Returns the newly created record as a dict.
    """
    try:
        with get_db_session() as session:
            record = KnowledgeDocumentRecord(
                document_uuid=_new_uuid(),
                knowledge_id=knowledge_id,
                tenant_id=tenant_id,
                source_uri=source_uri,
                filename=filename,
                file_size=file_size,
                status="indexing",
                error_message=None,
                chunk_count=0,
                celery_task_id=celery_task_id,
                created_by=user_id,
                updated_by=user_id,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return as_dict(record)
    except SQLAlchemyError:
        logger.exception("Failed to create document record for %s", source_uri)
        raise


def get_document_record_by_uuid(document_uuid: str) -> Optional[Dict[str, Any]]:
    """Fetch one document record by its public UUID."""
    try:
        with get_db_session() as session:
            record = session.query(KnowledgeDocumentRecord).filter(
                KnowledgeDocumentRecord.document_uuid == document_uuid,
                KnowledgeDocumentRecord.delete_flag != "Y",
            ).first()
            return as_dict(record) if record else None
    except SQLAlchemyError:
        logger.exception("get_document_record_by_uuid failed: %s", document_uuid)
        raise


def get_document_record_by_source_uri(
    knowledge_id: int, source_uri: str
) -> Optional[Dict[str, Any]]:
    """Fetch one document record by knowledge_id + source_uri."""
    try:
        with get_db_session() as session:
            record = session.query(KnowledgeDocumentRecord).filter(
                KnowledgeDocumentRecord.knowledge_id == knowledge_id,
                KnowledgeDocumentRecord.source_uri == source_uri,
                KnowledgeDocumentRecord.delete_flag != "Y",
            ).first()
            return as_dict(record) if record else None
    except SQLAlchemyError:
        logger.exception(
            "get_document_record_by_source_uri failed: kb=%s uri=%s", knowledge_id, source_uri
        )
        raise


def list_document_records(
    knowledge_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List document records for a knowledge base with optional filename keyword filter.

    Returns {"records": [...], "total": int}.
    """
    try:
        with get_db_session() as session:
            q = session.query(KnowledgeDocumentRecord).filter(
                KnowledgeDocumentRecord.knowledge_id == knowledge_id,
                KnowledgeDocumentRecord.delete_flag != "Y",
            )
            if keyword:
                q = q.filter(
                    KnowledgeDocumentRecord.filename.ilike(f"%{keyword}%")
                )
            total = q.count()
            records = (
                q.order_by(KnowledgeDocumentRecord.create_time.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "records": [as_dict(r) for r in records],
                "total": total,
            }
    except SQLAlchemyError:
        logger.exception("list_document_records failed for kb %s", knowledge_id)
        raise


def update_document_status(
    knowledge_id: int,
    source_uri: str,
    status: str,
    error_message: Optional[str] = None,
    chunk_count: Optional[int] = None,
    user_id: Optional[str] = None,
) -> bool:
    """
    Update document indexing status by knowledge_id + source_uri.

    Returns True if a row was updated, False if not found.
    """
    valid_statuses = {"indexing", "completed", "failed", "paused"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    try:
        with get_db_session() as session:
            record = session.query(KnowledgeDocumentRecord).filter(
                KnowledgeDocumentRecord.knowledge_id == knowledge_id,
                KnowledgeDocumentRecord.source_uri == source_uri,
                KnowledgeDocumentRecord.delete_flag != "Y",
            ).first()
            if not record:
                return False
            record.status = status
            if error_message is not None:
                record.error_message = error_message
            if chunk_count is not None:
                record.chunk_count = chunk_count
            if user_id:
                record.updated_by = user_id
            session.commit()
            return True
    except SQLAlchemyError:
        logger.exception(
            "update_document_status failed: kb=%s uri=%s", knowledge_id, source_uri
        )
        raise


def soft_delete_document_record(
    knowledge_id: int, source_uri: str, user_id: Optional[str] = None
) -> bool:
    """
    Soft-delete a document record by knowledge_id + source_uri.

    Returns True if a row was deleted, False if not found.
    """
    try:
        with get_db_session() as session:
            record = session.query(KnowledgeDocumentRecord).filter(
                KnowledgeDocumentRecord.knowledge_id == knowledge_id,
                KnowledgeDocumentRecord.source_uri == source_uri,
                KnowledgeDocumentRecord.delete_flag != "Y",
            ).first()
            if not record:
                return False
            record.delete_flag = "Y"
            if user_id:
                record.updated_by = user_id
            session.commit()
            return True
    except SQLAlchemyError:
        logger.exception(
            "soft_delete_document_record failed: kb=%s uri=%s", knowledge_id, source_uri
        )
        raise


def soft_delete_all_documents_by_knowledge_id(
    knowledge_id: int, user_id: Optional[str] = None
) -> int:
    """
    Soft-delete ALL document records belonging to a knowledge base.

    Used when the entire knowledge base is deleted.
    Returns number of rows affected.
    """
    try:
        with get_db_session() as session:
            rows = (
                session.query(KnowledgeDocumentRecord)
                .filter(
                    KnowledgeDocumentRecord.knowledge_id == knowledge_id,
                    KnowledgeDocumentRecord.delete_flag != "Y",
                )
                .all()
            )
            for r in rows:
                r.delete_flag = "Y"
                if user_id:
                    r.updated_by = user_id
            session.commit()
            return len(rows)
    except SQLAlchemyError:
        logger.exception(
            "soft_delete_all_documents_by_knowledge_id failed for kb %s", knowledge_id
        )
        raise
