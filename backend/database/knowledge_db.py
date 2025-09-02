from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from database.client import as_dict, get_db_session
from database.db_models import KnowledgeRecord


def create_knowledge_record(query: Dict[str, Any]) -> int:
    """
    Create a knowledge base record

    Args:
        query: Dictionary containing all knowledge base data, must include:
            - index_name: Knowledge base name
            - knowledge_describe: Knowledge base description
            - knowledge_status: Knowledge base status
            - user_id: Optional user ID for created_by and updated_by fields
            - tenant_id: Optional tenant ID for created_by and updated_by fields

    Returns:
        int: Newly created knowledge base ID
    """
    try:
        with get_db_session() as session:
            # Prepare data dictionary
            data = {
                "index_name": query["index_name"],
                "knowledge_describe": query.get("knowledge_describe", ""),
                "created_by": query.get("user_id"),
                "updated_by": query.get("user_id"),
                "knowledge_sources": query.get("knowledge_sources", "elasticsearch"),
                "tenant_id": query.get("tenant_id")
            }

            # Create new record
            new_record = KnowledgeRecord(**data)
            session.add(new_record)
            session.flush()
            session.commit()
            return new_record.knowledge_id
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
                    "knowledge_sources": item.knowledge_sources
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
