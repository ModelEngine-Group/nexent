import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from sqlalchemy import asc, desc, func, insert, select, update

from .client import as_dict, db_client, get_db_session
from .db_models import (
    ConversationMessage,
    ConversationMessageUnit,
    ConversationRecord,
    ConversationSourceImage,
    ConversationSourceSearch,
)
from .utils import add_creation_tracking, add_update_tracking


class MessageRecord(TypedDict):
    message_id: int
    message_index: int
    role: str
    type: Optional[str]
    content: Optional[str]
    opinion_flag: Optional[str]


def _serialize_unit_content(content: Any) -> str:
    """Serialize structured unit content for the text database column."""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


class SearchRecord(TypedDict):
    message_id: int
    source_type: str
    source_title: str
    source_location: str
    source_content: str
    score_overall: Optional[float]
    score_accuracy: Optional[float]
    score_semantic: Optional[float]
    published_date: Optional[datetime]
    cite_index: Optional[int]
    search_type: Optional[str]
    tool_sign: Optional[str]


class ImageRecord(TypedDict):
    message_id: int
    image_url: str


class ConversationHistory(TypedDict):
    conversation_id: int
    agent_id: Optional[int]
    create_time: int
    message_records: List[MessageRecord]
    search_records: List[SearchRecord]
    image_records: List[ImageRecord]


HISTORY_SUMMARY_UNIT_TYPE = "history_summary"


class HistorySummaryPersistenceError(ValueError):
    """Raised when a history-summary candidate violates persistence rules."""


def _parse_history_summary_content(content: Any) -> Optional[Dict[str, Any]]:
    """Return a valid summary payload, or ``None`` for malformed/stale units."""
    try:
        payload = json.loads(content) if isinstance(content, str) else content
        if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
            return None
        boundary = payload.get("covered_through_message_id")
        if isinstance(boundary, bool) or int(boundary) <= 0:
            return None
        payload["covered_through_message_id"] = int(boundary)
        return payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _get_user_tenant(user_id: str) -> Optional[Dict[str, Any]]:
    """Resolve tenant ownership lazily to keep database modules decoupled."""
    from .user_tenant_db import get_user_tenant_by_user_id

    return get_user_tenant_by_user_id(user_id)


def _get_effective_tenant_id(user_tenant: Dict[str, Any]) -> str:
    """Resolve legacy empty tenant fields consistently with authentication."""
    from consts.const import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID

    tenant_id = user_tenant.get("tenant_id")
    if tenant_id:
        return tenant_id
    if (user_tenant.get("user_role") or "").upper() == ASSET_OWNER_ROLE:
        return ASSET_OWNER_TENANT_ID
    return DEFAULT_TENANT_ID


def create_conversation(
    conversation_title: str,
    user_id: Optional[str] = None,
    agent_id: Optional[int] = None,
    db_session=None,
) -> Dict[str, Any]:
    """
    Create a new conversation record

    Args:
        conversation_title: Conversation title
        user_id: Reserved parameter for created_by and updated_by fields
        agent_id: Agent used by the latest run in this conversation

    Returns:
        Dict[str, Any]: Dictionary containing complete information of the newly created conversation
    """
    session_context = get_db_session(db_session) if db_session is not None else get_db_session()
    with session_context as session:
        # Prepare data dictionary
        data = {"conversation_title": conversation_title, "delete_flag": 'N'}
        if agent_id is not None:
            data["agent_id"] = agent_id
        if user_id:
            data = add_creation_tracking(data, user_id)

        stmt = insert(ConversationRecord).values(**data).returning(
            ConversationRecord.conversation_id,
            ConversationRecord.conversation_title,
            ConversationRecord.agent_id,
            (func.extract('epoch', ConversationRecord.create_time)
             * 1000).label('create_time'),
            (func.extract('epoch', ConversationRecord.update_time)
             * 1000).label('update_time')
        )

        record = session.execute(stmt).fetchone()

        # Convert to dictionary and ensure timestamps are integers
        result_dict = {
            "conversation_id": record.conversation_id,
            "conversation_title": record.conversation_title,
            "agent_id": record.agent_id,
            "create_time": int(record.create_time),
            "update_time": int(record.update_time)
        }
        return result_dict


def create_conversation_message(message_data: Dict[str, Any], user_id: Optional[str] = None,
                                 status: str = 'completed') -> int:
    """
    Create a conversation message record

    Args:
        message_data: Dictionary containing message data, must include the following fields:
            - conversation_id: Conversation ID (integer)
            - message_idx: Message index (integer)
            - role: Message role
            - content: Message content
            - minio_files: JSON string of attachment information
        user_id: Reserved parameter for created_by and updated_by fields
        status: Lifecycle status (pending / streaming / completed / failed / stopped)

    Returns:
        int: Newly created message ID (auto-increment ID)
    """
    with get_db_session() as session:
        # Ensure conversation_id is integer type
        conversation_id = int(message_data['conversation_id'])
        message_idx = int(message_data['message_idx'])

        minio_files = message_data.get('minio_files')
        # Convert minio_files to JSON string for storage
        if minio_files is not None:
            # If minio_files is already a string, use it directly; otherwise convert to JSON string
            if not isinstance(minio_files, str):
                minio_files = json.dumps(minio_files)

        # Prepare data dictionary
        data = {"conversation_id": conversation_id, "message_index": message_idx, "message_role": message_data['role'],
                "message_content": message_data['content'], "minio_files": minio_files, "opinion_flag": None,
                "delete_flag": 'N', "status": status}
        if user_id:
            data = add_creation_tracking(data, user_id)

        # insert into conversation_message_t
        stmt = insert(ConversationMessage).values(
            **data).returning(ConversationMessage.message_id)
        result = session.execute(stmt)
        message_id = result.scalar()
        return message_id


def create_message_units(message_units: List[Dict[str, Any]], message_id: int, conversation_id: int,
                         user_id: Optional[str] = None) -> List[int]:
    """
    Batch create message unit records

    Args:
        message_units: List of message units, each containing:
            - type: Unit type
            - content: Unit content
        message_id: Message ID (integer)
        conversation_id: Conversation ID (integer)
        user_id: Reserved parameter for created_by and updated_by fields

    Returns:
        List[int]: List of newly created unit IDs
    """
    if not message_units:
        return []  # No message units, return empty list

    with get_db_session() as session:
        # Ensure IDs are integer type
        message_id = int(message_id)
        conversation_id = int(conversation_id)

        # Create units one by one to get unit_ids
        unit_ids = []
        for idx, unit in enumerate(message_units):
            # Basic data
            row_data = {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "unit_index": idx,
                "unit_type": unit['type'],
                "unit_content": _serialize_unit_content(unit['content']),
                "delete_flag": 'N'
            }

            if user_id:
                row_data["created_by"] = user_id
                row_data["updated_by"] = user_id

            # Insert and get unit_id
            stmt = insert(ConversationMessageUnit).values(
                **row_data).returning(ConversationMessageUnit.unit_id)
            result = session.execute(stmt)
            unit_id = result.scalar_one()
            unit_ids.append(unit_id)

        return unit_ids


def create_message_unit(message_id: int, conversation_id: int, unit_index: int,
                        unit_type: str, unit_content: Any,
                        user_id: Optional[str] = None,
                        unit_status: str = 'completed') -> int:
    """
    Insert a single ConversationMessageUnit row.

    Args:
        message_id: Message ID (integer)
        conversation_id: Conversation ID (integer)
        unit_index: Sequence number for frontend display sorting
        unit_type: Type of the unit (e.g. "model_output_code", "final_answer")
        unit_content: Complete content of the unit
        user_id: Reserved parameter for created_by and updated_by fields
        unit_status: Lifecycle status (streaming / completed)

    Returns:
        int: Newly created unit ID (auto-increment ID)
    """
    with get_db_session() as session:
        message_id = int(message_id)
        conversation_id = int(conversation_id)
        unit_index = int(unit_index)

        row_data = {
            "message_id": message_id,
            "conversation_id": conversation_id,
            "unit_index": unit_index,
            "unit_type": unit_type,
            "unit_content": _serialize_unit_content(unit_content),
            "unit_status": unit_status,
            "delete_flag": 'N',
        }
        if user_id:
            row_data["created_by"] = user_id
            row_data["updated_by"] = user_id

        stmt = insert(ConversationMessageUnit).values(
            **row_data).returning(ConversationMessageUnit.unit_id)
        result = session.execute(stmt)
        return result.scalar_one()


def update_conversation_message_status(message_id: int, status: str,
                                        user_id: Optional[str] = None) -> None:
    """
    Update the lifecycle status of a conversation message.

    Args:
        message_id: Message ID (integer)
        status: New status (pending / streaming / completed / failed / stopped)
        user_id: Reserved parameter for updated_by field
    """
    with get_db_session() as session:
        message_id = int(message_id)
        update_data = {
            "status": status,
            "update_time": func.current_timestamp(),
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)
        session.execute(
            update(ConversationMessage)
            .where(ConversationMessage.message_id == message_id,
                   ConversationMessage.delete_flag == 'N')
            .values(update_data)
        )


def update_conversation_message_content(message_id: int, content: str,
                                         user_id: Optional[str] = None) -> None:
    """
    Update the message_content field of a conversation message.

    Args:
        message_id: Message ID (integer)
        content: New content text
        user_id: Reserved parameter for updated_by field
    """
    with get_db_session() as session:
        message_id = int(message_id)
        update_data = {
            "message_content": content,
            "update_time": func.current_timestamp(),
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)
        session.execute(
            update(ConversationMessage)
            .where(ConversationMessage.message_id == message_id,
                   ConversationMessage.delete_flag == 'N')
            .values(update_data)
        )


def update_message_unit_status(unit_id: int, status: str,
                                user_id: Optional[str] = None) -> None:
    """
    Update the unit_status field of a message unit.

    Args:
        unit_id: Unit ID (integer)
        status: New status (streaming / completed)
        user_id: Reserved parameter for updated_by field
    """
    with get_db_session() as session:
        unit_id = int(unit_id)
        update_data = {
            "unit_status": status,
            "update_time": func.current_timestamp(),
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)
        session.execute(
            update(ConversationMessageUnit)
            .where(ConversationMessageUnit.unit_id == unit_id,
                   ConversationMessageUnit.delete_flag == 'N')
            .values(update_data)
        )


def update_message_unit_content(unit_id: int, content: Any,
                                user_id: Optional[str] = None) -> None:
    """
    Update the unit_content field of a message unit.

    Args:
        unit_id: Unit ID (integer)
        content: New content text
        user_id: Reserved parameter for updated_by field
    """
    with get_db_session() as session:
        unit_id = int(unit_id)
        update_data = {
            "unit_content": _serialize_unit_content(content),
            "update_time": func.current_timestamp(),
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)
        session.execute(
            update(ConversationMessageUnit)
            .where(ConversationMessageUnit.unit_id == unit_id,
                   ConversationMessageUnit.delete_flag == 'N')
            .values(update_data)
        )


def get_conversation(
    conversation_id: int,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get conversation details

    Args:
        conversation_id: Conversation ID (integer)
        user_id: User that must own the conversation
        tenant_id: Tenant that the owning user must currently belong to

    Returns:
        Optional[Dict[str, Any]]: Conversation details, or None if it doesn't exist
    """
    if tenant_id and not user_id:
        raise ValueError("user_id is required when tenant_id is provided")
    if tenant_id:
        user_tenant = _get_user_tenant(user_id)
        if not user_tenant or _get_effective_tenant_id(user_tenant) != tenant_id:
            return None

    with get_db_session() as session:
        # Ensure conversation_id is integer type
        conversation_id = int(conversation_id)

        # Build the query statement
        stmt = select(ConversationRecord).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.delete_flag == 'N'
        )

        if user_id:
            stmt = stmt.where(
                ConversationRecord.created_by == user_id
            )
        # Execute the query
        record = session.scalars(stmt).first()
        return None if record is None else as_dict(record)


def get_conversation_messages(conversation_id: int) -> List[Dict[str, Any]]:
    """
    Get all messages in a conversation

    Args:
        conversation_id: Conversation ID (integer)

    Returns:
        List[Dict[str, Any]]: List of messages, sorted by message_index
    """
    with get_db_session() as session:
        # Ensure conversation_id is of integer type
        conversation_id = int(conversation_id)

        # Build the query statement
        stmt = select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.delete_flag == 'N'
        ).order_by(asc(ConversationMessage.message_index))

        # Execute the query
        records = session.scalars(stmt).all()

        # Convert SQLAlchemy model instances to dictionaries
        return list(map(as_dict, records))


def get_message_units(message_id: int) -> List[Dict[str, Any]]:
    """
    Get all units of a message

    Args:
        message_id: Message ID (integer)

    Returns:
        List[Dict[str, Any]]: List of message units, sorted by unit_index
    """
    with get_db_session() as session:
        # Ensure message_id is integer type
        message_id = int(message_id)

        # Build the query statement
        stmt = select(ConversationMessageUnit).where(
            ConversationMessageUnit.message_id == message_id,
            ConversationMessageUnit.delete_flag == 'N'
        ).order_by(asc(ConversationMessageUnit.unit_index))

        # Execute the query
        records = session.scalars(stmt).all()

        # Convert SQLAlchemy model instances to dictionaries
        return list(map(as_dict, records))


def get_conversation_list(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get list of all undeleted conversations, sorted by creation time in descending order

    Args:
        user_id: Reserved parameter for filtering conversations created by this user

    Returns:
        List[Dict[str, Any]]: List of conversations, each containing id, title and timestamp information
    """
    with get_db_session() as session:
        # Build the query statement
        stmt = select(
            ConversationRecord.conversation_id,
            ConversationRecord.conversation_title,
            ConversationRecord.agent_id,
            (func.extract('epoch', ConversationRecord.create_time)
             * 1000).label('create_time'),
            (func.extract('epoch', ConversationRecord.update_time)
             * 1000).label('update_time')
        ).where(ConversationRecord.delete_flag == 'N')

        # Keep NL2AGENT runner conversations out of the global chat history.
        # The lazy import preserves compatibility with isolated DB-model stubs.
        try:
            from .db_models import AgentInfo
        except ImportError:
            AgentInfo = None
        if AgentInfo is not None:
            stmt = stmt.where(~select(AgentInfo.agent_id).where(
                AgentInfo.agent_id == ConversationRecord.agent_id,
                AgentInfo.version_no == 0,
                AgentInfo.name == "nl2agent",
            ).exists())

        stmt = stmt.order_by(desc(ConversationRecord.create_time))

        # If user_id is provided, additional filter conditions can be added here
        if user_id:
            stmt = stmt.where(ConversationRecord.created_by == user_id)

        # Execute the query
        records = session.execute(stmt)

        # Convert query results to a list of dictionaries and ensure timestamps are integers
        result = []
        for record in records:
            conversation = as_dict(record)
            conversation['create_time'] = int(conversation['create_time'])
            conversation['update_time'] = int(conversation['update_time'])
            result.append(conversation)

        return result


def update_conversation_agent_id(conversation_id: int, agent_id: int, user_id: Optional[str] = None) -> bool:
    """
    Update the agent associated with a conversation.

    Args:
        conversation_id: Conversation ID (integer)
        agent_id: Latest agent ID used by this conversation
        user_id: Reserved parameter for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    with get_db_session() as session:
        conversation_id = int(conversation_id)
        update_data = {
            "agent_id": int(agent_id),
            "update_time": func.current_timestamp()
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)

        stmt = update(ConversationRecord).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.delete_flag == 'N'
        ).values(update_data)

        result = session.execute(stmt)
        return result.rowcount > 0


def rename_conversation(conversation_id: int, new_title: str, user_id: Optional[str] = None) -> bool:
    """
    Rename a conversation

    Args:
        conversation_id: Conversation ID (integer)
        new_title: New conversation title
        user_id: Reserved parameter for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    with get_db_session() as session:
        # Ensure conversation_id is of integer type
        conversation_id = int(conversation_id)

        # Prepare update data with UTF-8 encoding for title
        update_data = {
            "conversation_title": new_title,
            "update_time": func.current_timestamp()
        }
        update_data = db_client.clean_string_values(update_data)
        if user_id:
            update_data = add_update_tracking(update_data, user_id)

        # Build the update statement
        stmt = update(ConversationRecord).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.delete_flag == 'N'
        ).values(update_data)

        # Execute the update statement
        result = session.execute(stmt)

        # Check if any rows were affected
        return result.rowcount > 0


def delete_conversation(conversation_id: int, user_id: Optional[str] = None) -> bool:
    """
    Delete a conversation (soft delete)

    Args:
        conversation_id: Conversation ID (integer)
        user_id: Reserved parameter for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    with get_db_session() as session:
        # Ensure conversation_id is of integer type
        conversation_id = int(conversation_id)

        # Prepare update data
        update_data = {
            "delete_flag": 'Y',
            "update_time": func.current_timestamp()
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)

        # 1. Mark conversation as deleted
        conversation_stmt = update(ConversationRecord).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.delete_flag == 'N'
        ).values(update_data)
        conversation_result = session.execute(conversation_stmt)

        # 2. Mark related messages as deleted
        message_stmt = update(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.delete_flag == 'N'
        ).values(update_data)
        session.execute(message_stmt)

        # 3. Mark message units as deleted
        unit_stmt = update(ConversationMessageUnit).where(
            ConversationMessageUnit.conversation_id == conversation_id,
            ConversationMessageUnit.delete_flag == 'N'
        ).values(update_data)
        session.execute(unit_stmt)

        # 4. Mark search sources as deleted
        search_stmt = update(ConversationSourceSearch).where(
            ConversationSourceSearch.conversation_id == conversation_id,
            ConversationSourceSearch.delete_flag == 'N'
        ).values(update_data)
        session.execute(search_stmt)

        # 5. Mark image sources as deleted
        image_stmt = update(ConversationSourceImage).where(
            ConversationSourceImage.conversation_id == conversation_id,
            ConversationSourceImage.delete_flag == 'N'
        ).values(update_data)
        session.execute(image_stmt)

        # Check if the conversation record was affected
        return conversation_result.rowcount > 0


def soft_delete_all_conversations_by_user(user_id: str) -> int:
    """
    Soft-delete all conversations and related records created by a user.

    Returns the number of conversations marked as deleted.
    """
    with get_db_session() as session:
        update_data = {
            "delete_flag": 'Y',
            "update_time": func.current_timestamp()
        }

        # 1) Find all conversation ids created by the user
        conv_ids = session.scalars(
            select(ConversationRecord.conversation_id).where(
                ConversationRecord.delete_flag == 'N',
                ConversationRecord.created_by == user_id,
            )
        ).all()

        if not conv_ids:
            return 0

        # 2) Mark conversations as deleted
        session.execute(
            update(ConversationRecord)
            .where(ConversationRecord.conversation_id.in_(conv_ids), ConversationRecord.delete_flag == 'N')
            .values(update_data)
        )

        # 3) Mark messages as deleted
        session.execute(
            update(ConversationMessage)
            .where(ConversationMessage.conversation_id.in_(conv_ids), ConversationMessage.delete_flag == 'N')
            .values(update_data)
        )

        # 4) Mark message units as deleted
        session.execute(
            update(ConversationMessageUnit)
            .where(ConversationMessageUnit.conversation_id.in_(conv_ids), ConversationMessageUnit.delete_flag == 'N')
            .values(update_data)
        )

        # 5) Mark search sources as deleted
        session.execute(
            update(ConversationSourceSearch)
            .where(ConversationSourceSearch.conversation_id.in_(conv_ids), ConversationSourceSearch.delete_flag == 'N')
            .values(update_data)
        )

        # 6) Mark image sources as deleted
        session.execute(
            update(ConversationSourceImage)
            .where(ConversationSourceImage.conversation_id.in_(conv_ids), ConversationSourceImage.delete_flag == 'N')
            .values(update_data)
        )

        return len(conv_ids)


def update_message_opinion(message_id: int, opinion: str, user_id: Optional[str] = None) -> bool:
    """
    Update message like/dislike status

    Args:
        message_id: Message ID (integer)
        opinion: Opinion flag, 'Y' for like, 'N' for dislike, None for no opinion
        user_id: Reserved parameter for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    with get_db_session() as session:
        # Ensure message_id is of integer type
        message_id = int(message_id)

        # Prepare update data
        update_data = {
            "opinion_flag": opinion,
            # Use the database's CURRENT_TIMESTAMP function
            "update_time": func.current_timestamp()
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)

        # Build the update statement
        stmt = update(ConversationMessage).where(
            ConversationMessage.message_id == message_id,
            ConversationMessage.delete_flag == 'N'
        ).values(update_data)

        # Execute the update statement
        result = session.execute(stmt)

        # Check if any rows were affected
        return result.rowcount > 0


def get_conversation_history(conversation_id: int, user_id: Optional[str] = None) -> Optional[ConversationHistory]:
    """
    Get complete conversation history, including all messages and message units' raw data

    Args:
        conversation_id: Conversation ID (integer)
        user_id: Reserved parameter for created_by and updated_by fields

    Returns:
        Optional[ConversationHistory]: Contains basic conversation information and raw data of all messages and message units
    """
    with get_db_session() as session:
        # Ensure conversation_id is of integer type
        conversation_id = int(conversation_id)

        # First check if conversation exists
        check_stmt = select(
            ConversationRecord.conversation_id,
            ConversationRecord.agent_id,
            (func.extract('epoch', ConversationRecord.create_time)
             * 1000).label('create_time')
        ).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.delete_flag == 'N'
        )
        if user_id:
            check_stmt = check_stmt.where(
                ConversationRecord.created_by == user_id)

        conversation = session.execute(check_stmt).first()

        if not conversation:
            return None

        conversation = as_dict(conversation)

        subquery = select(
            func.json_agg(
                func.json_build_object(
                    'unit_id', ConversationMessageUnit.unit_id,
                    'unit_type', ConversationMessageUnit.unit_type,
                    'unit_content', ConversationMessageUnit.unit_content,
                    'unit_status', ConversationMessageUnit.unit_status,
                    'unit_index', ConversationMessageUnit.unit_index
                )
            )
        ).select_from(
            ConversationMessageUnit
        ).where(
            ConversationMessageUnit.message_id == ConversationMessage.message_id,
            ConversationMessageUnit.delete_flag == 'N',
            ConversationMessageUnit.unit_type is not None
        ).scalar_subquery()

        query = select(
            ConversationMessage.message_id,
            ConversationMessage.message_index,
            ConversationMessage.message_role.label('role'),
            ConversationMessage.message_content,
            ConversationMessage.status,
            ConversationMessage.minio_files,
            ConversationMessage.opinion_flag,
            subquery.label('units')
        ).where(
            ConversationMessage.conversation_id == conversation_id,

            ConversationMessage.delete_flag == 'N'
        ).order_by(
            asc(ConversationMessage.message_index),
            asc(ConversationMessage.message_id),
        )

        message_records = session.execute(query).all()

        # Get search data
        search_stmt = select(ConversationSourceSearch).where(
            ConversationSourceSearch.conversation_id == conversation_id,
            ConversationSourceSearch.delete_flag == 'N'
        ).order_by(ConversationSourceSearch.search_id)
        search_records = session.scalars(search_stmt).all()

        # Get image data
        image_stmt = select(ConversationSourceImage).where(
            ConversationSourceImage.conversation_id == conversation_id,
            ConversationSourceImage.delete_flag == 'N'
        )
        image_records = session.scalars(image_stmt).all()

        # Integrate message and unit data
        message_list = []
        for record in message_records:
            message_data = as_dict(record)

            # Ensure units field is empty list instead of None, then sort by unit_index
            if message_data['units'] is None:
                message_data['units'] = []
            else:
                message_data['units'] = sorted(message_data['units'], key=lambda u: u['unit_index'])

            # Process minio_files field - if it's a JSON string, parse it into Python object
            if message_data.get('minio_files'):
                try:
                    if isinstance(message_data['minio_files'], str):
                        message_data['minio_files'] = json.loads(
                            message_data['minio_files'])
                except (json.JSONDecodeError, TypeError):
                    # If parsing fails, keep original value
                    pass

            message_list.append(message_data)

        return {
            'conversation_id': conversation['conversation_id'],
            'agent_id': conversation.get('agent_id'),
            'create_time': int(conversation['create_time']),
            'message_records': message_list,
            'search_records': [as_dict(record) for record in search_records],
            'image_records': [as_dict(record) for record in image_records]
        }


def _image_exists(session, message_id: int, image_url: str) -> bool:
    stmt = select(ConversationSourceImage).where(
        ConversationSourceImage.message_id == message_id,
        ConversationSourceImage.image_url == image_url,
        ConversationSourceImage.delete_flag == 'N'
    ).limit(1)
    return session.execute(stmt).scalar_one_or_none() is not None


def create_source_image(image_data: Dict[str, Any], user_id: Optional[str] = None) -> int:
    """
    Create image source reference (skips if the same message_id + image_url already exists).

    Args:
        image_data: Dictionary containing image data, must include the following fields:
            - message_id: Message ID (integer)
            - image_url: Image URL
        user_id: Reserved parameter for created_by and updated_by fields

    Returns:
        int: Newly created image ID (auto-increment ID), or -1 if skipped due to duplicate
    """
    with get_db_session() as session:
        # Ensure message_id is of integer type
        message_id = int(image_data['message_id'])
        image_url = image_data['image_url']

        # Skip duplicate: same message_id + image_url already in DB
        if _image_exists(session, message_id, image_url):
            return -1

        # Prepare data dictionary
        data = {
            "message_id": message_id,
            "conversation_id": image_data.get('conversation_id'),
            "image_url": image_url,
            "delete_flag": 'N',
            # Use the database's CURRENT_TIMESTAMP function
            "create_time": func.current_timestamp()
        }

        if user_id:
            data = add_creation_tracking(data, user_id)

        # Build the insert statement and return the newly created image ID
        stmt = insert(ConversationSourceImage).values(
            **data).returning(ConversationSourceImage.image_id)

        # Execute the insert statement
        result = session.execute(stmt)
        image_id = result.scalar_one()

        return image_id


def delete_source_image(image_id: int, user_id: Optional[str] = None) -> bool:
    """
    Delete image source reference (soft delete)

    Args:
        image_id: Image ID (integer)
        user_id: Reserved parameter for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    with get_db_session() as session:
        # Ensure image_id is an integer
        image_id = int(image_id)

        # Prepare update data
        update_data = {
            "delete_flag": 'Y',
            # Use database's CURRENT_TIMESTAMP function
            "update_time": func.current_timestamp()
        }

        if user_id:
            update_data = add_update_tracking(update_data, user_id)

        # Build the update statement
        stmt = update(ConversationSourceImage).where(
            ConversationSourceImage.image_id == image_id,
            ConversationSourceImage.delete_flag == 'N'
        ).values(update_data)

        # Execute the update statement
        result = session.execute(stmt)

        # Check if any rows were affected
        return result.rowcount > 0


def get_source_images_by_message(message_id: int, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all associated image source information by message ID

    Args:
        message_id: Message ID
        user_id: Reserved parameter for filtering images created by this user

    Returns:
        List[Dict[str, Any]]: List of image source information
    """
    with get_db_session() as session:
        # Ensure message_id is an integer
        message_id = int(message_id)

        # Build the query using SQLAlchemy's ORM
        stmt = select(ConversationSourceImage).join(
            ConversationMessage, ConversationSourceImage.message_id == ConversationMessage.message_id
        ).join(
            ConversationRecord, ConversationMessage.conversation_id == ConversationRecord.conversation_id
        ).where(
            ConversationSourceImage.message_id == message_id,
            ConversationSourceImage.delete_flag == 'N'
        ).order_by(
            ConversationSourceImage.image_id
        )

        if user_id:
            stmt = stmt.where(ConversationRecord.created_by == user_id)

        # Execute the query
        image_records = session.scalars(stmt).all()

        # Convert SQLAlchemy model instances to dictionaries
        return [as_dict(record) for record in image_records]


def get_source_images_by_conversation(conversation_id: int, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all associated image source information by conversation ID

    Args:
        conversation_id: Conversation ID
        user_id: Current user ID, for filtering images created by this user

    Returns:
        List[Dict[str, Any]]: List of image source information
    """
    with get_db_session() as session:
        # Ensure conversation_id is an integer
        conversation_id = int(conversation_id)

        # Build the query
        stmt = select(ConversationSourceImage).join(
            ConversationRecord, ConversationSourceImage.conversation_id == ConversationRecord.conversation_id
        ).where(
            ConversationSourceImage.conversation_id == conversation_id,
            ConversationSourceImage.delete_flag == 'N'
        ).order_by(
            ConversationSourceImage.image_id
        )

        if user_id:
            stmt = stmt.where(ConversationRecord.created_by == user_id)

        # Execute the query
        image_records = session.scalars(stmt).all()

        # Convert SQLAlchemy model instances to dictionaries
        return [as_dict(record) for record in image_records]


def create_source_search(search_data: Dict[str, Any], user_id: Optional[str] = None) -> int:
    """
    Create search source reference

    Args:
        search_data: Dictionary containing search data, must include the following fields:
            - message_id: Message ID (integer)
            - source_type: Source type
            - source_title: Source title
            - source_location: Source location/URL
            - source_content: Source content
            - cite_index: Index number
            - search_type: Source tool
            - tool_sign: Source tool simple identifier, used for summary differentiation
            Optional fields:
            - unit_id: Message unit ID (integer)
            - score_overall: Overall relevance score
            - score_accuracy: Accuracy score
            - score_semantic: Semantic relevance score
            - published_date: Publication date
        user_id: Reserved parameter for created_by and updated_by fields

    Returns:
        int: Newly created search ID (auto-increment ID)
    """
    with get_db_session() as session:
        # Ensure message_id is an integer
        message_id = int(search_data['message_id'])

        # Prepare basic data dictionary
        data = {
            "message_id": message_id,
            "conversation_id": search_data.get('conversation_id'),
            "source_type": search_data['source_type'],
            "source_title": search_data['source_title'],
            "source_location": search_data['source_location'],
            "source_content": search_data['source_content'],
            "cite_index": search_data['cite_index'],
            "search_type": search_data['search_type'],
            "tool_sign": search_data['tool_sign'],
            "delete_flag": 'N',
            # Use the database's CURRENT_TIMESTAMP function
            "create_time": func.current_timestamp()
        }

        # Add unit_id if provided
        if 'unit_id' in search_data and search_data['unit_id'] is not None:
            data["unit_id"] = int(search_data['unit_id'])

        # Add optional fields
        if 'score_overall' in search_data:
            data["score_overall"] = search_data['score_overall']
        if 'score_accuracy' in search_data:
            data["score_accuracy"] = search_data['score_accuracy']
        if 'score_semantic' in search_data:
            data["score_semantic"] = search_data['score_semantic']
        if 'published_date' in search_data:
            data["published_date"] = search_data['published_date']
        if user_id:
            data = add_creation_tracking(data, user_id)

        # Build the insert statement and return the newly created search ID
        stmt = insert(ConversationSourceSearch).values(
            **data).returning(ConversationSourceSearch.search_id)

        # Execute the insert statement
        result = session.execute(stmt)
        search_id = result.scalar_one()

        return search_id


def delete_source_search(search_id: int, user_id: Optional[str] = None) -> bool:
    """
    Delete search source reference (soft delete)

    Args:
        search_id: Search ID (integer)
        user_id: Reserved parameter for updated_by field

    Returns:
        bool: Whether the operation was successful
    """
    with get_db_session() as session:
        # Ensure search_id is an integer
        search_id = int(search_id)

        # Prepare update data
        update_data = {
            "delete_flag": 'Y',
            # Use the database's CURRENT_TIMESTAMP function
            "update_time": func.current_timestamp()
        }
        if user_id:
            update_data = add_update_tracking(update_data, user_id)

        # Build the update statement
        stmt = update(ConversationSourceSearch).where(
            ConversationSourceSearch.search_id == search_id,
            ConversationSourceSearch.delete_flag == 'N'
        ).values(update_data)

        # Execute the update statement
        result = session.execute(stmt)

        # Check if any rows were affected
        return result.rowcount > 0


def get_source_searches_by_message(message_id: int, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all associated search source information by message ID

    Args:
        message_id: Message ID
        user_id: Reserved parameter for created_by and updated_by fields

    Returns:
        List[Dict[str, Any]]: List of search source information
    """
    with get_db_session() as session:
        # Ensure message_id is an integer
        message_id = int(message_id)

        # Build the query
        stmt = select(ConversationSourceSearch).join(
            ConversationMessage, ConversationSourceSearch.message_id == ConversationMessage.message_id
        ).join(
            ConversationRecord, ConversationMessage.conversation_id == ConversationRecord.conversation_id
        ).where(
            ConversationSourceSearch.message_id == message_id,
            ConversationSourceSearch.delete_flag == 'N'
        ).order_by(
            ConversationSourceSearch.search_id
        )

        if user_id:
            stmt = stmt.where(ConversationRecord.created_by == user_id)

        # Execute the query
        search_records = session.scalars(stmt).all()

        # Convert SQLAlchemy model instances to dictionaries
        return [as_dict(record) for record in search_records]


def get_source_searches_by_conversation(conversation_id: int, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all associated search source information by conversation ID

    Args:
        conversation_id: Conversation ID
        user_id: Reserved parameter for filtering search content created by this user

    Returns:
        List[Dict[str, Any]]: List of search source information
    """
    with get_db_session() as session:
        # Convert conversation_id to integer
        conversation_id = int(conversation_id)

        # Build the SQL query
        stmt = select(ConversationSourceSearch).join(
            ConversationRecord,
            ConversationSourceSearch.conversation_id == ConversationRecord.conversation_id
        ).where(
            ConversationSourceSearch.conversation_id == conversation_id,
            ConversationSourceSearch.delete_flag == 'N'
        ).order_by(
            ConversationSourceSearch.search_id
        )

        if user_id:
            stmt = stmt.where(ConversationRecord.created_by == user_id)

        # Execute the query and get all results
        search_records = session.scalars(stmt).all()

        # Convert SQLAlchemy objects to dictionaries
        return [as_dict(record) for record in search_records]


def get_message(message_id: int, user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get message details by message ID

    Args:
        message_id: Message ID
        user_id: Reserved parameter for created_by and updated_by fields

    Returns:
        Dict[str, Any]: Message details
    """
    with get_db_session() as session:
        # Ensure message_id is an integer
        message_id = int(message_id)

        # Build the query
        stmt = select(ConversationMessage).join(
            ConversationRecord, ConversationMessage.conversation_id == ConversationRecord.conversation_id
        ).where(
            ConversationMessage.message_id == message_id,
            ConversationMessage.delete_flag == 'N'
        )

        if user_id:
            stmt = stmt.where(ConversationRecord.created_by == user_id)

        # Execute the query and get the first result
        record = session.scalars(stmt).first()

        # Convert the SQLAlchemy object to a dictionary if it exists
        return as_dict(record) if record else None


def get_message_id_by_index(conversation_id: int, message_index: int) -> Optional[int]:
    """
    Get message ID by conversation ID and message index

    Args:
        conversation_id: Conversation ID (integer)
        message_index: Message index (integer)

    Returns:
        Optional[int]: Message ID if found, None otherwise
    """
    with get_db_session() as session:
        # Ensure input parameters are integers
        conversation_id = int(conversation_id)
        message_index = int(message_index)

        # Build the query
        stmt = select(ConversationMessage.message_id).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.message_index == message_index,
            ConversationMessage.delete_flag == 'N'
        )

        # Execute the query and get the first result
        result = session.execute(stmt).scalar()

        return result


def get_latest_assistant_message_id(conversation_id: int, user_id: Optional[str] = None) -> Optional[int]:
    """
    Get the most recent assistant message ID for a conversation.

    Args:
        conversation_id: Conversation ID (integer)
        user_id: Optional user ID for ownership check

    Returns:
        Optional[int]: The latest assistant message ID, or None if not found
    """
    with get_db_session() as session:
        conversation_id = int(conversation_id)

        stmt = select(ConversationMessage.message_id).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.delete_flag == 'N',
            ConversationMessage.message_role == 'assistant'
        ).order_by(desc(ConversationMessage.message_index)).limit(1)

        if user_id:
            stmt = stmt.join(
                ConversationRecord,
                ConversationMessage.conversation_id == ConversationRecord.conversation_id
            ).where(ConversationRecord.created_by == user_id)

        result = session.execute(stmt).scalar()
        return result


def get_latest_user_message_id(conversation_id: int, user_id: str) -> Optional[int]:
    """Return the latest user message in a non-deleted conversation owned by user."""
    with get_db_session() as session:
        stmt = select(ConversationMessage.message_id).join(
            ConversationRecord,
            ConversationMessage.conversation_id == ConversationRecord.conversation_id,
        ).where(
            ConversationMessage.conversation_id == int(conversation_id),
            ConversationMessage.message_role == 'user',
            ConversationMessage.delete_flag == 'N',
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == 'N',
        ).order_by(desc(ConversationMessage.message_index)).limit(1)
        return session.execute(stmt).scalar()


def get_latest_assistant_message(conversation_id: int, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get the latest assistant message for a conversation, including its status field.
    Used for streaming recovery to check if a stream is still in progress.

    Args:
        conversation_id: Conversation ID
        user_id: Optional user ID for ownership check

    Returns:
        Optional[Dict]: Contains message_id, status, message_content, or None if not found
    """
    with get_db_session() as session:
        conversation_id = int(conversation_id)

        stmt = select(
            ConversationMessage.message_id,
            ConversationMessage.status,
            ConversationMessage.message_content,
        ).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.delete_flag == 'N',
            ConversationMessage.message_role == 'assistant'
        ).order_by(desc(ConversationMessage.message_index)).limit(1)

        if user_id:
            stmt = stmt.join(
                ConversationRecord,
                ConversationMessage.conversation_id == ConversationRecord.conversation_id
            ).where(ConversationRecord.created_by == user_id)

        result = session.execute(stmt).first()
        if result:
            return {
                'message_id': result.message_id,
                'status': result.status,
                'message_content': result.message_content,
            }
        return None


def get_last_unit_for_message(message_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the last unit (highest unit_index) for a message.
    Used for streaming recovery to determine the resume position.

    Args:
        message_id: Message ID

    Returns:
        Optional[Dict]: Contains unit_id, unit_index, unit_type, unit_content, unit_status,
                        or None if no units exist
    """
    with get_db_session() as session:
        message_id = int(message_id)

        stmt = select(
            ConversationMessageUnit.unit_id,
            ConversationMessageUnit.unit_index,
            ConversationMessageUnit.unit_type,
            ConversationMessageUnit.unit_content,
            ConversationMessageUnit.unit_status,
        ).where(
            ConversationMessageUnit.message_id == message_id,
            ConversationMessageUnit.delete_flag == 'N'
        ).order_by(desc(ConversationMessageUnit.unit_index)).limit(1)

        result = session.execute(stmt).first()
        if result:
            return {
                'unit_id': result.unit_id,
                'unit_index': result.unit_index,
                'unit_type': result.unit_type,
                'unit_content': result.unit_content,
                'unit_status': result.unit_status,
            }
        return None


def update_message_minio_files(message_id: int, skill_file_uploads: List[Dict[str, Any]]) -> bool:
    """
    Merge skill file uploads into an existing message's minio_files field.

    Args:
        message_id: Message ID to update
        skill_file_uploads: List of skill file upload metadata dicts to append

    Returns:
        bool: True if the message was updated, False if the message was not found
    """
    with get_db_session() as session:
        message_id = int(message_id)

        stmt = select(ConversationMessage).where(
            ConversationMessage.message_id == message_id,
            ConversationMessage.delete_flag == 'N'
        )
        record = session.scalars(stmt).first()
        if not record:
            return False

        existing = record.minio_files
        if existing:
            try:
                if isinstance(existing, str):
                    existing = json.loads(existing)
            except (json.JSONDecodeError, TypeError):
                existing = []
        else:
            existing = []

        existing.extend(skill_file_uploads)
        record.minio_files = json.dumps(existing, ensure_ascii=False)

        return True


def save_history_summary(
    conversation_id: int, user_id: str, tenant_id: str,
    summary: Dict[str, Any], covered_through_message_id: int,
    previous_summary_unit_id: Optional[int] = None,
    trigger: Optional[str] = None,
) -> int:
    """Persist a validated checkpoint on its last covered assistant message."""
    if not user_id or not tenant_id or not isinstance(summary, dict):
        raise HistorySummaryPersistenceError(
            "user_id, tenant_id and an object summary are required")
    conversation_id = int(conversation_id)
    covered_through_message_id = int(covered_through_message_id)
    user_tenant = _get_user_tenant(user_id)
    if not user_tenant or _get_effective_tenant_id(user_tenant) != tenant_id:
        raise HistorySummaryPersistenceError("conversation is not accessible")

    with get_db_session() as session:
        owner = session.execute(select(ConversationRecord.conversation_id).where(
            ConversationRecord.conversation_id == conversation_id,
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == 'N')).first()
        if not owner:
            raise HistorySummaryPersistenceError("conversation is not accessible")

        covered = session.execute(select(
            ConversationMessage.message_id, ConversationMessage.message_index,
            ConversationMessage.message_role, ConversationMessage.status,
        ).where(
            ConversationMessage.message_id == covered_through_message_id,
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.delete_flag == 'N')).first()
        if (not covered or covered.message_role != 'assistant'
                or covered.status != 'completed'):
            raise HistorySummaryPersistenceError(
                "coverage must end at a completed assistant message")

        previous_boundary_index = -1
        if previous_summary_unit_id is not None:
            previous = session.execute(select(
                ConversationMessageUnit.unit_content,
                ConversationMessage.message_index,
            ).join(ConversationMessage,
                   ConversationMessage.message_id == ConversationMessageUnit.message_id).where(
                ConversationMessageUnit.unit_id == int(previous_summary_unit_id),
                ConversationMessageUnit.conversation_id == conversation_id,
                ConversationMessageUnit.unit_type == HISTORY_SUMMARY_UNIT_TYPE,
                ConversationMessageUnit.unit_status == 'completed',
                ConversationMessageUnit.delete_flag == 'N',
                ConversationMessage.delete_flag == 'N')).first()
            if not previous or not _parse_history_summary_content(previous.unit_content):
                raise HistorySummaryPersistenceError("previous summary is invalid")
            previous_boundary_index = previous.message_index
            if previous_boundary_index >= covered.message_index:
                raise HistorySummaryPersistenceError("summary coverage must advance")

        incomplete_count = session.scalar(select(func.count()).select_from(
            ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.message_index > previous_boundary_index,
                ConversationMessage.message_index <= covered.message_index,
                ConversationMessage.status != 'completed',
                ConversationMessage.delete_flag == 'N'))
        if incomplete_count:
            raise HistorySummaryPersistenceError(
                "history summaries may cover completed messages only")

        max_index = session.scalar(select(func.max(
            ConversationMessageUnit.unit_index)).where(
                ConversationMessageUnit.message_id == covered_through_message_id,
                ConversationMessageUnit.delete_flag == 'N'))
        payload: Dict[str, Any] = {
            "summary": summary,
            "covered_through_message_id": covered_through_message_id,
        }
        if previous_summary_unit_id is not None:
            payload["previous_summary_unit_id"] = int(previous_summary_unit_id)
        if trigger:
            payload["trigger"] = trigger
        row = add_creation_tracking({
            "message_id": covered_through_message_id,
            "conversation_id": conversation_id,
            "unit_index": (max_index if max_index is not None else -1) + 1,
            "unit_type": HISTORY_SUMMARY_UNIT_TYPE,
            "unit_content": json.dumps(payload, ensure_ascii=False),
            "unit_status": 'completed', "delete_flag": 'N',
        }, user_id)
        return session.execute(insert(ConversationMessageUnit).values(**row).returning(
            ConversationMessageUnit.unit_id)).scalar_one()


def get_historical_context(
    conversation_id: int, current_user_message_id: int,
    user_id: str, tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Load the authorized latest checkpoint and completed turns before a run."""
    if not user_id or not tenant_id:
        return None
    user_tenant = _get_user_tenant(user_id)
    if not user_tenant or _get_effective_tenant_id(user_tenant) != tenant_id:
        return None
    conversation_id = int(conversation_id)
    current_user_message_id = int(current_user_message_id)
    with get_db_session() as session:
        current = session.execute(select(
            ConversationMessage.message_id, ConversationMessage.message_index,
        ).join(ConversationRecord,
               ConversationRecord.conversation_id == ConversationMessage.conversation_id).where(
            ConversationMessage.message_id == current_user_message_id,
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.message_role == 'user',
            ConversationMessage.delete_flag == 'N',
            ConversationRecord.created_by == user_id,
            ConversationRecord.delete_flag == 'N')).first()
        if not current:
            return None

        candidates = session.execute(select(
            ConversationMessageUnit.unit_id,
            ConversationMessageUnit.unit_content,
            ConversationMessageUnit.unit_index,
            ConversationMessage.message_index,
        ).join(ConversationMessage,
               ConversationMessage.message_id == ConversationMessageUnit.message_id).where(
            ConversationMessageUnit.conversation_id == conversation_id,
            ConversationMessageUnit.unit_type == HISTORY_SUMMARY_UNIT_TYPE,
            ConversationMessageUnit.unit_status == 'completed',
            ConversationMessageUnit.delete_flag == 'N',
            ConversationMessage.status == 'completed',
            ConversationMessage.delete_flag == 'N',
            ConversationMessage.message_index < current.message_index,
        ).order_by(desc(ConversationMessage.message_index),
                   desc(ConversationMessageUnit.unit_index))).all()

        summary_record = None
        summary_payload = None
        boundary_index = -1
        for candidate in candidates:
            payload = _parse_history_summary_content(candidate.unit_content)
            if not payload:
                continue
            boundary = session.execute(select(
                ConversationMessage.message_index,
                ConversationMessage.message_role,
                ConversationMessage.status,
            ).where(
                ConversationMessage.message_id == payload["covered_through_message_id"],
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.delete_flag == 'N')).first()
            if (boundary and boundary.message_role == 'assistant'
                    and boundary.status == 'completed'
                    and boundary.message_index == candidate.message_index
                    and boundary.message_index < current.message_index):
                summary_record, summary_payload = candidate, payload
                boundary_index = boundary.message_index
                break

        messages = session.execute(select(
            ConversationMessage.message_id,
            ConversationMessage.message_index,
            ConversationMessage.message_role,
            ConversationMessage.message_content,
            ConversationMessage.minio_files,
        ).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.message_index > boundary_index,
            ConversationMessage.message_index < current.message_index,
            ConversationMessage.status == 'completed',
            ConversationMessage.delete_flag == 'N',
            ConversationMessage.message_role.in_(['user', 'assistant']),
        ).order_by(asc(ConversationMessage.message_index))).all()

        turns: List[Dict[str, Any]] = []
        pending_user = None
        for message in messages:
            if message.message_role == 'user':
                pending_user = message
            elif pending_user is not None:
                turns.append({
                    "user_message": pending_user.message_content or "",
                    "assistant_final_answer": message.message_content or "",
                    "attachments": pending_user.minio_files,
                    "user_message_id": pending_user.message_id,
                    "assistant_message_id": message.message_id,
                })
                pending_user = None

        summary_result = None
        if summary_record and summary_payload:
            summary_result = {
                "unit_id": summary_record.unit_id,
                **summary_payload,
            }
        return {"history_summary": summary_result, "conversation_turns": turns}
