from typing import Any, Dict, List, Optional

import uuid
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from database.client import as_dict, get_db_session
from database.db_models import KnowledgeRecord


def _generate_index_name(knowledge_id: int) -> str:
    """
    Generate a new internal index_name based on knowledge_id and a UUID suffix.
    The suffix contains only digits and lowercase letters.
    """
    suffix = uuid.uuid4().hex
    return f"{knowledge_id}-{suffix}"


def create_knowledge_record(query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a knowledge base record

    Args:
        query: Dictionary containing all knowledge base data, must include:
            - index_name: Knowledge base name
            - knowledge_describe: Knowledge base description
            - knowledge_status: Knowledge base status
            - user_id: Optional user ID for created_by and updated_by fields
            - tenant_id: Optional tenant ID for created_by and updated_by fields
            - embedding_model_name: embedding model name for the knowledge base

    Returns:
        Dict[str, Any]: Dictionary with at least 'knowledge_id' and 'index_name'
    """
    try:
        with get_db_session() as session:
            # Determine user-facing knowledge base name
            knowledge_name = query.get(
                "knowledge_name") or query.get("index_name")

            # Prepare data dictionary
            data: Dict[str, Any] = {
                "knowledge_describe": query.get("knowledge_describe", ""),
                "created_by": query.get("user_id"),
                "updated_by": query.get("user_id"),
                "knowledge_sources": query.get("knowledge_sources", "elasticsearch"),
                "tenant_id": query.get("tenant_id"),
                "embedding_model_name": query.get("embedding_model_name"),
                "knowledge_name": knowledge_name,
            }

            # For backward compatibility: if caller explicitly provides index_name,
            # respect it and do not regenerate; otherwise generate after flush.
            explicit_index_name = query.get("index_name")
            if explicit_index_name:
                data["index_name"] = explicit_index_name

            # Create new record
            new_record = KnowledgeRecord(**data)
            session.add(new_record)
            session.flush()

            # Generate internal index_name for new records when not explicitly provided
            if not explicit_index_name:
                generated_index_name = _generate_index_name(
                    new_record.knowledge_id)
                new_record.index_name = generated_index_name
                session.flush()

            session.commit()
            return {
                "knowledge_id": new_record.knowledge_id,
                "index_name": new_record.index_name,
                "knowledge_name": new_record.knowledge_name,
            }
    except SQLAlchemyError as e:
        session.rollback()
        raise e


def update_knowledge_record(query: Dict[str, Any]) -> bool:
    """
    Update a knowledge base record

    Args:
        query: Dictionary containing update data, must include:
            - knowledge_id: Knowledge base ID
            - update_data: Dictionary containing fields to update
            - user_id: Optional user ID for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    try:
        with get_db_session() as session:
            record = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.index_name == query['index_name'],
                KnowledgeRecord.delete_flag != 'Y'
            ).first()

            if not record:
                return False

            record.knowledge_describe = query["knowledge_describe"]
            record.update_time = func.current_timestamp()
            if query.get("user_id"):
                record.updated_by = query["user_id"]

            session.flush()
            session.commit()
            return True
    except SQLAlchemyError as e:
        session.rollback()
        raise e


def delete_knowledge_record(query: Dict[str, Any]) -> bool:
    """
    Delete a knowledge base record (soft delete)

    Args:
        query: Dictionary containing delete data, must include:
            - index_name: Knowledge base name
            - user_id: Optional user ID for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    try:
        with get_db_session() as session:
            # Find the record to update
            record = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.index_name == query['index_name'],
                KnowledgeRecord.delete_flag != 'Y'
            ).first()

            if not record:
                return False

            # Update record for soft delete
            record.delete_flag = 'Y'
            record.update_time = func.current_timestamp()
            if query.get('user_id'):
                record.updated_by = query['user_id']

            session.flush()
            session.commit()
            return True
    except SQLAlchemyError as e:
        session.rollback()
        raise e


def get_knowledge_record(query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get a knowledge base record

    Args:
        query: Dictionary containing filter conditions, optional parameter.
               If 'tenant_id' is provided, it will filter by tenant.
               If 'tenant_id' is not provided, it will search across all tenants.

    Returns:
        Dict[str, Any]: Knowledge base record
    """
    try:
        with get_db_session() as session:
            db_query = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.delete_flag != 'Y',
                KnowledgeRecord.index_name == query['index_name'],
            )

            # Add tenant_id filter only if it is provided in the query
            if 'tenant_id' in query and query['tenant_id'] is not None:
                db_query = db_query.filter(
                    KnowledgeRecord.tenant_id == query['tenant_id'])

            result = db_query.first()

            if result:
                return as_dict(result)
            return {}
    except SQLAlchemyError as e:
        raise e


def get_knowledge_info_by_knowledge_ids(knowledge_ids: List[str]) -> List[Dict[str, Any]]:
    try:
        with get_db_session() as session:
            result = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.knowledge_id.in_(knowledge_ids),
                KnowledgeRecord.delete_flag != 'Y'
            ).all()
            knowledge_info = []
            for item in result:
                knowledge_info.append({
                    "knowledge_id": item.knowledge_id,
                    "index_name": item.index_name,
                    "knowledge_sources": item.knowledge_sources,
                    "embedding_model_name": item.embedding_model_name
                })
            return knowledge_info
    except SQLAlchemyError as e:
        raise e


def get_knowledge_ids_by_index_names(index_names: List[str]) -> List[str]:
    try:
        with get_db_session() as session:
            result = session.query(KnowledgeRecord.knowledge_id).filter(
                KnowledgeRecord.index_name.in_(index_names),
                KnowledgeRecord.delete_flag != 'Y'
            ).all()
            return [item.knowledge_id for item in result]
    except SQLAlchemyError as e:
        raise e


def get_knowledge_info_by_tenant_id(tenant_id: str) -> List[Dict[str, Any]]:
    try:
        with get_db_session() as session:
            result = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.tenant_id == tenant_id,
                KnowledgeRecord.delete_flag != 'Y'
            ).all()
            return [as_dict(item) for item in result]
    except SQLAlchemyError as e:
        raise e


def update_model_name_by_index_name(index_name: str, embedding_model_name: str, tenant_id: str, user_id: str) -> bool:
    try:
        with get_db_session() as session:
            session.query(KnowledgeRecord).filter(
                KnowledgeRecord.index_name == index_name,
                KnowledgeRecord.delete_flag != 'Y',
                KnowledgeRecord.tenant_id == tenant_id
            ).update({"embedding_model_name": embedding_model_name, "updated_by": user_id})
            session.commit()
            return True
    except SQLAlchemyError as e:
        raise e


def get_index_name_by_knowledge_name(knowledge_name: str, tenant_id: str) -> str:
    """
    Get the internal index_name from user-facing knowledge_name.

    Args:
        knowledge_name: User-facing knowledge base name
        tenant_id: Tenant ID to filter by

    Returns:
        str: The internal index_name if found

    Raises:
        ValueError: If knowledge base with the given name is not found for the tenant
    """
    try:
        with get_db_session() as session:
            result = session.query(KnowledgeRecord).filter(
                KnowledgeRecord.knowledge_name == knowledge_name,
                KnowledgeRecord.tenant_id == tenant_id,
                KnowledgeRecord.delete_flag != 'Y'
            ).first()

            if result:
                return result.index_name
            raise ValueError(
                f"Knowledge base '{knowledge_name}' not found for the current tenant"
            )
    except SQLAlchemyError as e:
        raise e
