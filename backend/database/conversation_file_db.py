import logging
from enum import Enum
from typing import List, Optional

from sqlalchemy import select, update

from .client import get_db_session
from .db_models import ConversationFile


class ConversationFileStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"

logger = logging.getLogger(__name__)


def create_conversation_file(
    conversation_id: str,
    tenant_id: str,
    object_name: str,
    filename: str,
    content_hash: str,
    embedding_model: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    with get_db_session() as session:
        record = ConversationFile(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            object_name=object_name,
            filename=filename,
            content_hash=content_hash,
            embedding_model=embedding_model,
            status=ConversationFileStatus.PENDING,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(record)
        session.flush()
        return {
            "id": record.id,
            "conversation_id": conversation_id,
            "object_name": object_name,
            "filename": filename,
            "status": ConversationFileStatus.PENDING,
        }


def get_conversation_files(conversation_id: str) -> List[dict]:
    with get_db_session() as session:
        stmt = (
            select(ConversationFile)
            .where(
                ConversationFile.conversation_id == str(conversation_id),
                ConversationFile.delete_flag == "N",
            )
            .order_by(ConversationFile.update_time.desc())
        )
        results = session.execute(stmt).scalars().all()
        return [
            {
                "id": r.id,
                "conversation_id": r.conversation_id,
                "tenant_id": r.tenant_id,
                "object_name": r.object_name,
                "filename": r.filename,
                "content_hash": r.content_hash,
                "status": r.status,
                "chunk_count": r.chunk_count,
                "fulltext_key": r.fulltext_key,
                "embedding_model": r.embedding_model,
                "error_message": r.error_message,
            }
            for r in results
        ]


def update_conversation_file_status(
    record_id: int,
    status: str,
    chunk_count: int = 0,
    fulltext_key: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    with get_db_session() as session:
        values = {"status": status, "chunk_count": chunk_count}
        if fulltext_key is not None:
            values["fulltext_key"] = fulltext_key
        if error_message is not None:
            values["error_message"] = error_message
        stmt = update(ConversationFile).where(ConversationFile.id == record_id).values(**values)
        session.execute(stmt)


def delete_conversation_files(conversation_id: str) -> int:
    with get_db_session() as session:
        stmt = (
            update(ConversationFile)
            .where(
                ConversationFile.conversation_id == str(conversation_id),
                ConversationFile.delete_flag == "N",
            )
            .values(delete_flag="Y")
        )
        result = session.execute(stmt)
        return result.rowcount
