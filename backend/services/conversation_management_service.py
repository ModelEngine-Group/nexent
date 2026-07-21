import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import StrictUndefined, Template

from consts.const import LANGUAGE, MODEL_CONFIG_MAPPING, MESSAGE_ROLE, DEFAULT_EN_TITLE, DEFAULT_ZH_TITLE
from consts.model import AgentRequest, MessageRequest, MessageUnit
from consts.exceptions import ConversationNotFoundError
from database.conversation_db import (
    create_conversation,
    create_conversation_message,
    create_message_unit,
    create_source_image,
    create_source_search,
    delete_conversation,
    get_conversation,
    get_conversation_history,
    get_historical_context,
    get_conversation_list,
    get_latest_assistant_message,  # noqa: F401 - service boundary re-export
    get_latest_assistant_message_id,
    get_latest_user_message_id,
    get_last_unit_for_message,  # noqa: F401 - service boundary re-export
    get_message_id_by_index,
    get_source_images_by_conversation,
    get_source_images_by_message,
    get_source_searches_by_conversation,
    get_source_searches_by_message,
    rename_conversation,
    save_history_summary,
    update_conversation_agent_id,
    update_conversation_message_content,
    update_conversation_message_status,
    update_message_minio_files,
    update_message_opinion,
    update_message_unit_content,
    update_message_unit_status,
)
from nexent.monitor import set_monitoring_context, set_monitoring_operation
from nexent.core.models import OpenAIModel
from agents.agent_run_manager import agent_run_manager
from utils.config_utils import get_model_name_from_config, tenant_config_manager
from utils.prompt_template_utils import get_generate_title_prompt_template
from utils.str_utils import remove_think_blocks

logger = logging.getLogger("conversation_management_service")


def save_message(request: MessageRequest, user_id: str, tenant_id: str,
                  status: str = 'completed') -> int:
    """
    Insert only the ConversationMessage row for a new message.

    Args:
        request: MessageRequest object containing:
            - conversation_id: Required, conversation ID
            - message_idx: Message index (integer type)
            - role: Message role
            - message: List of message units (the string/final_answer unit, if any,
              is used to populate message_content; all units are then persisted
              via separate ``save_message_unit`` calls)
            - minio_files: List of object_names for files stored in minio
        user_id: Identifier of the user creating the message
        tenant_id: Identifier of the tenant
        status: Lifecycle status of the message
            (pending / streaming / completed / failed / stopped)

    Returns:
        int: Newly created message_id

    Raises:
        Exception: If conversation_id is missing or the insert fails
    """
    if tenant_id is None or user_id is None:
        logging.warning("Missing tenant_id or user_id to save message")

    message_data = request.model_dump()

    conversation_id = message_data.get('conversation_id')
    if not conversation_id:
        raise Exception(
            "conversation_id is required, please call /conversation/create to create a conversation first")

    message_units = message_data.get('message') or []
    string_content = None
    for unit in message_units:
        if unit.get('type') in ('string', 'final_answer'):
            string_content = unit.get('content')
            break

    if string_content is None and message_units:
        string_content = ""

    message_data_copy = {
        'conversation_id': conversation_id,
        'message_idx': message_data['message_idx'],
        'role': message_data['role'],
        'content': string_content or "",
        'minio_files': message_data.get('minio_files'),
    }
    return create_conversation_message(message_data_copy, user_id, status=status)


def save_message_unit(message_id: int, conversation_id: int, unit_index: int,
                      unit_type: str, unit_content: str,
                      user_id: Optional[str] = None,
                      unit_status: str = 'completed') -> int:
    """
    Insert exactly one ConversationMessageUnit row.

    Args:
        message_id: Parent message ID
        conversation_id: Conversation ID
        unit_index: Sequence number for frontend display sorting
        unit_type: Type of the unit (e.g. "model_output_code", "final_answer")
        unit_content: Complete content of the unit
        user_id: Identifier of the user creating the unit
        unit_status: Lifecycle status (streaming / completed)

    Returns:
        int: Newly created unit_id
    """
    return create_message_unit(
        message_id=message_id,
        conversation_id=conversation_id,
        unit_index=unit_index,
        unit_type=unit_type,
        unit_content=unit_content,
        user_id=user_id,
        unit_status=unit_status,
    )


def persist_history_summary_candidate(
    conversation_id: int, candidate: Any, user_id: str, tenant_id: str,
) -> int:
    """Backend persistence boundary injected into the SDK context runtime."""
    def field(name: str, default: Any = None) -> Any:
        return candidate.get(name, default) if isinstance(candidate, dict) \
            else getattr(candidate, name, default)

    return save_history_summary(
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        summary=field("summary"),
        covered_through_message_id=field("covered_through_message_id"),
        previous_summary_unit_id=field("previous_summary_unit_id"),
        trigger=field("trigger"),
    )


def load_historical_context(
    conversation_id: int, current_user_message_id: int,
    user_id: str, tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Load only the authorized checkpoint and completed turns needed by SDK."""
    return get_historical_context(
        conversation_id=conversation_id,
        current_user_message_id=current_user_message_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )


def get_current_run_user_message_id(conversation_id: int, user_id: str) -> Optional[int]:
    """Resolve the persisted boundary for the run that was just saved."""
    return get_latest_user_message_id(conversation_id, user_id)


def update_message_status(message_id: int, status: str, user_id: str) -> None:
    """Update the lifecycle status of a conversation message."""
    update_conversation_message_status(message_id, status, user_id=user_id)


def update_unit_status(unit_id: int, status: str, user_id: str) -> None:
    """Update the unit_status field of a message unit."""
    update_message_unit_status(unit_id, status, user_id=user_id)


def update_unit_content(unit_id: int, content: str, user_id: str) -> None:
    """Update the unit_content field of a message unit."""
    update_message_unit_content(unit_id, content, user_id=user_id)


def update_message_content(message_id: int, content: str, user_id: str) -> None:
    """Update the message_content field of a conversation message."""
    update_conversation_message_content(message_id, content, user_id=user_id)


def save_source_image(image_data: Dict[str, Any]) -> int:
    """
    Persist a single image source reference for a message.

    Args:
        image_data: Dictionary with message_id, conversation_id, image_url

    Returns:
        int: Newly created image_id, or -1 if duplicate
    """
    return create_source_image(image_data)


def save_source_search(search_data: Dict[str, Any], user_id: Optional[str] = None) -> int:
    """
    Persist a single search source reference for a message.

    Args:
        search_data: Dictionary of search result fields
        user_id: Identifier of the user creating the search record

    Returns:
        int: Newly created search_id
    """
    return create_source_search(search_data, user_id=user_id)


def save_conversation_user(request: AgentRequest, user_id: str, tenant_id: str) -> None:
    """Persist the user-side message (one message row only).

    Note: conversation_message_unit_t only stores assistant message content.
    User messages do not need unit records.
    """
    user_role_count = sum(1 for item in getattr(
        request, "history", []) if item.role == MESSAGE_ROLE["USER"])

    conversation_req = MessageRequest(
        conversation_id=request.conversation_id,
        message_idx=user_role_count * 2,
        role=MESSAGE_ROLE["USER"],
        message=[MessageUnit(type="string", content=request.query)],
        minio_files=request.minio_files,
    )
    save_message(
        conversation_req, user_id=user_id, tenant_id=tenant_id)


def save_conversation_assistant(request: AgentRequest, messages: List[str], user_id: str, tenant_id: str):
    """
    Batch-persist the assistant-side message and all of its units.

    Kept for backwards compatibility and debug flows. The streaming agent run
    persists units incrementally via ``save_message_unit`` instead of going
    through this function. New callers should use ``save_message`` +
    ``save_message_unit`` directly.

    Raises ``NotImplementedError`` because the incremental streaming flow
    replaces this path; calling it would double-write the assistant message.
    """
    raise NotImplementedError(
        "save_conversation_assistant has been replaced by the incremental "
        "save_message / save_message_unit flow used by _stream_agent_chunks."
    )


def call_llm_for_title(question: str, tenant_id: str, language: str = LANGUAGE["ZH"]) -> str:
    """
    Call LLM to generate a title from a user question

    Args:
        question: User's question content
        tenant_id: Tenant ID
        language: Language code ('zh' for Chinese, 'en' for English)

    Returns:
        str: Generated title
    """
    prompt_template = get_generate_title_prompt_template(language=language)
    set_monitoring_context(tenant_id=tenant_id, user_id=None)

    model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
    display_name = model_config.get("display_name", "") if model_config else ""
    set_monitoring_operation("title_generation", display_name=display_name or None)

    timeout_seconds = model_config.get("timeout_seconds") if model_config else None

    # Create OpenAIModel instance
    llm = OpenAIModel(
        model_id=get_model_name_from_config(model_config) if model_config.get("model_name") else "",
        api_base=model_config.get("base_url", ""),
        api_key=model_config.get("api_key", ""),
        temperature=0.7,
        top_p=0.95,
        model_factory=model_config.get("model_factory", None),
        ssl_verify=model_config.get("ssl_verify", True),
        timeout_seconds=timeout_seconds,
        stream=False,
    )

    # Build messages - use new template variable 'question' instead of 'content'
    user_prompt = Template(prompt_template["USER_PROMPT"], undefined=StrictUndefined).render({
        "question": question
    })
    messages = [{"role": MESSAGE_ROLE["SYSTEM"],
                 "content": prompt_template["SYSTEM_PROMPT"]},
                {"role": MESSAGE_ROLE["USER"],
                 "content": user_prompt}]

    # ModelEngine accepts role/content in a simple structure, ensure flattening before passing
    if model_config.get("model_factory", "").lower() == "modelengine":
        messages = [{"role": msg["role"], "content": str(msg.get("content", ""))} for msg in messages]

    # Call the model
    response = llm.generate(messages)
    if not response or not response.content or not response.content.strip():
        return DEFAULT_EN_TITLE if language == LANGUAGE["EN"] else DEFAULT_ZH_TITLE
    return remove_think_blocks(response.content.strip())


def update_conversation_title(conversation_id: int, title: str, user_id: str = None) -> bool:
    """
    Update conversation title

    Args:
        conversation_id: Conversation ID
        title: New title
        user_id: Reserved parameter, user ID
    Returns:
        bool: Whether the update was successful
    """
    success = rename_conversation(conversation_id, title, user_id)
    if not success:
        raise ConversationNotFoundError(
            f"Conversation {conversation_id} does not exist or has been deleted"
        )
    return success


def create_new_conversation(title: str, user_id: str, agent_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Create a new conversation

    Args:
        title: Conversation title
        user_id: User ID
        agent_id: Agent used by the latest run in this conversation

    Returns:
        Dict containing conversation data
    """
    try:
        conversation_data = create_conversation(title, user_id, agent_id=agent_id)
        return conversation_data
    except Exception as e:
        logging.error(f"Failed to create conversation: {str(e)}")
        raise Exception(str(e))


def get_conversation_list_service(user_id: str) -> List[Dict[str, Any]]:
    """
    Get all conversation list

    Returns:
        List of conversation data
    """
    try:
        conversations = get_conversation_list(user_id)
        return conversations
    except Exception as e:
        logging.error(f"Failed to get conversation list: {str(e)}")
        raise Exception(str(e))


def get_conversation_service(
    conversation_id: int,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return a conversation only within the requesting user and tenant scope."""
    return get_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )


def update_conversation_agent_id_service(conversation_id: int, agent_id: int, user_id: str) -> bool:
    """
    Update the latest agent associated with a conversation.
    """
    try:
        success = update_conversation_agent_id(conversation_id, agent_id, user_id)
        if not success:
            raise Exception(f"Conversation {conversation_id} does not exist or has been deleted")
        return True
    except Exception as e:
        logging.error(f"Failed to update conversation agent: {str(e)}")
        raise Exception(str(e))


def rename_conversation_service(conversation_id: int, name: str, user_id: str) -> bool:
    """
    Rename a conversation

    Args:
        conversation_id: Conversation ID
        name: New conversation title
        user_id: User ID

    Returns:
        bool: Whether the rename was successful
    """
    try:
        success = rename_conversation(conversation_id, name, user_id)
        if not success:
            raise Exception(f"Conversation {conversation_id} does not exist or has been deleted")
        return True
    except Exception as e:
        logging.error(f"Failed to rename conversation: {str(e)}")
        raise Exception(str(e))


def delete_conversation_service(conversation_id: int, user_id: str) -> bool:
    """
    Delete specified conversation

    Args:
        conversation_id: Conversation ID to delete
        user_id: User ID

    Returns:
        bool: Whether the deletion was successful
    """
    try:
        try:
            from services.agent_automation.facade import agent_automation_facade
            agent_automation_facade.on_conversation_deleted(conversation_id, user_id)
        except Exception as automation_error:
            logging.warning(
                "Failed to cleanup automation task for conversation %s: %s",
                conversation_id,
                automation_error,
            )

        success = delete_conversation(conversation_id, user_id)
        if not success:
            raise Exception(f"Conversation {conversation_id} does not exist or has been deleted")

        # Defensive cleanup: release the ContextManager associated with this conversation
        # to avoid memory leaks in edge cases
        agent_run_manager.clear_conversation_context_manager(conversation_id)

        return True
    except Exception as e:
        logging.error(f"Failed to delete conversation: {str(e)}")
        raise Exception(str(e))


def _build_streaming_message(message_records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Build streaming state from the latest assistant message with status='streaming'.
    This is used by the frontend to recover streaming state when the user returns to
    a conversation tab after switching away.

    Args:
        message_records: Raw message records from get_conversation_history

    Returns:
        Optional[Dict]: Contains streaming message info for recovery, or None if no streaming message
    """
    for msg in reversed(message_records):
        if msg.get('status') == 'streaming' and msg.get('role') == MESSAGE_ROLE["ASSISTANT"]:
            units = msg.get('units') or []
            last_unit = units[-1] if units else None
            return {
                'message_id': msg['message_id'],
                'message_index': msg['message_index'],
                'status': msg['status'],
                'message_content': msg.get('message_content', ''),
                'last_unit': last_unit,
                'units': units,
            }
    return None


def get_conversation_history_service(conversation_id: int, user_id: str) -> List[Dict[str, Any]]:
    """
    Get complete history of specified conversation

    Args:
        conversation_id: Conversation ID
        user_id: User ID

    Returns:
        Dict containing conversation history data
    """
    try:
        # Get original conversation history data
        history_data = get_conversation_history(conversation_id, user_id)

        if not history_data:
            logging.debug(
                f"No history data found for conversation_id: {conversation_id}")
            return []

        # Collect search content, grouped by unit_id
        search_by_unit_id = {}
        # Collect data for message-level search field
        search_by_message = {}
        for record in history_data['search_records']:
            unit_id = record['unit_id']
            message_id = record['message_id']

            # Process published_date, ensure it's a datetime object
            published_date = None
            if record['published_date'] is not None:
                if isinstance(record['published_date'], datetime):
                    published_date = record['published_date'].strftime(
                        "%Y-%m-%d")
                elif isinstance(record['published_date'], str):
                    published_date = record['published_date']

            # Build search content
            search_item = {"title": record["source_title"], "text": record["source_content"],
                           "source_type": record["source_type"], "url": record["source_location"],
                           "filename": record["source_title"] if record["source_type"] == "file" else None,
                           "published_date": published_date, "score": record["score_overall"],
                           "cite_index": record["cite_index"], "search_type": record["search_type"],
                           "tool_sign": record["tool_sign"], "score_details": {}}

            if record["score_accuracy"] is not None:
                search_item["score_details"]["accuracy"] = record["score_accuracy"]
            if record["score_semantic"] is not None:
                search_item["score_details"]["semantic"] = record["score_semantic"]

            # Group by unit_id (for frontend matching by unit_id)
            if unit_id is not None:
                if unit_id not in search_by_unit_id:
                    search_by_unit_id[unit_id] = []
                search_by_unit_id[unit_id].append(search_item)

            # Group by message_id (for message-level search field)
            if message_id not in search_by_message:
                search_by_message[message_id] = []
            search_by_message[message_id].append(search_item)

        # Collect image content - grouped by message_id, with URL deduplication
        image_by_message = {}
        for record in history_data['image_records']:
            message_id = record['message_id']
            if message_id not in image_by_message:
                image_by_message[message_id] = []
            # Only add if not already present (by URL)
            if record['image_url'] not in image_by_message[message_id]:
                image_by_message[message_id].append(record['image_url'])

        # Sort by message index and build final message list, including images and search content
        messages = []

        for msg in history_data['message_records']:
            message_id = msg['message_id']
            role = msg['role']
            message_content = msg['message_content']
            # Initialize for all message types
            message_units = msg['units'] or []

            if role == MESSAGE_ROLE["USER"]:
                # User message: directly use message_content as message field value
                message_item = {
                    'role': role,
                    'message': message_content,
                    'message_id': message_id,
                    'opinion_flag': None
                }

                # Add minio_files field (if any)
                if 'minio_files' in msg and msg['minio_files']:
                    message_item['minio_files'] = msg['minio_files']
            else:
                # Assistant message: message is an array, need to process search_content_placeholder
                processed_units = []
                for unit in message_units:
                    unit_id = unit.get('unit_id')
                    unit_type = unit.get('unit_type')
                    unit_content = unit.get('unit_content')

                    if unit_type == 'history_summary':
                        try:
                            summary_payload = json.loads(unit_content)
                            covered_message_id = int(
                                summary_payload['covered_through_message_id'])
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                            logger.warning(
                                "Skipping invalid history summary unit_id=%s",
                                unit_id,
                            )
                            continue
                        if covered_message_id != int(message_id):
                            logger.warning(
                                "Skipping misplaced history summary unit_id=%s "
                                "message_id=%s coverage=%s",
                                unit_id,
                                message_id,
                                covered_message_id,
                            )
                            continue

                    if unit_type == 'search_content_placeholder' and unit_id:
                        placeholder_content = {
                            "placeholder": True,
                            "unit_id": unit_id
                        }
                        processed_units.append({
                            'type': 'search_content_placeholder',
                            'content': json.dumps(placeholder_content, ensure_ascii=False)
                        })
                    else:
                        processed_units.append({
                            'type': unit_type,
                            'content': unit_content
                        })

                # Add final_answer type message unit only if not already present
                has_final_answer = any(u.get('type') == 'final_answer' for u in processed_units)
                if not has_final_answer:
                    processed_units.append({
                        'type': 'final_answer',
                        'content': message_content
                    })

                message_item = {
                    'role': role,
                    'message': processed_units,
                    'message_id': message_id,
                    'opinion_flag': msg['opinion_flag']
                }

                # Add minio_files field (if any, e.g., skill-generated attachments)
                if 'minio_files' in msg and msg['minio_files']:
                    message_item['minio_files'] = msg['minio_files']

            # Add image content (if any)
            if message_id in image_by_message:
                message_item['picture'] = image_by_message[message_id]

            # Add search content (for frontend right panel display)
            if message_id in search_by_message:
                message_item['search'] = search_by_message[message_id]

            # Add searchByUnitId for precise matching in frontend
            message_unit_search = {}
            for unit_id, search_results in search_by_unit_id.items():
                # Only include unit_id belonging to the current message
                for unit in message_units:
                    if unit.get('unit_id') == unit_id:
                        message_unit_search[str(unit_id)] = search_results
                        break

            if message_unit_search:
                message_item['searchByUnitId'] = message_unit_search

            messages.append(message_item)

        # Build final result
        formatted_history = {
            # Convert to string
            'conversation_id': str(history_data['conversation_id']),
            'agent_id': history_data.get('agent_id'),
            'create_time': history_data['create_time'],
            'message': messages
        }

        # Add streaming_message if there's an in-progress assistant message
        streaming_message = _build_streaming_message(history_data['message_records'])
        if streaming_message:
            formatted_history['streaming_message'] = streaming_message

        return [formatted_history]

    except Exception as e:
        logging.error(f"Failed to get conversation history: {str(e)}")
        raise Exception(str(e))


def get_sources_service(conversation_id: Optional[int], message_id: Optional[int], source_type: str = "all", user_id: str = "") -> Dict[str, Any]:
    """
    Get message source information (images and search results)

    Args:
        conversation_id: Optional conversation ID
        message_id: Optional message ID
        source_type: Source type, default is "all", options are "image", "search", or "all"
        user_id: User ID

    Returns:
        Dict containing source information
    """
    try:
        if not conversation_id and not message_id:
            return {
                "code": 400,
                "message": "Must provide conversation_id or message_id parameter",
                "data": None
            }

        # If conversation ID is provided
        if conversation_id:
            conversation = get_conversation(conversation_id, user_id)
            if not conversation:
                return {
                    "code": 404,
                    "message": f"Conversation {conversation_id} does not exist",
                    "data": None
                }

        result = {"searches": [], "images": []}

        # Get image sources
        if source_type in ["image", "all"]:
            images = []
            if message_id:
                image_records = get_source_images_by_message(
                    message_id, user_id)
            elif conversation_id:
                image_records = get_source_images_by_conversation(
                    conversation_id, user_id)

            for image in image_records:
                images.append(image["image_url"])

            result["images"] = images

        # Get search sources
        if source_type in ["search", "all"]:
            searches = []
            search_records = []
            if message_id:
                search_records = get_source_searches_by_message(
                    message_id, user_id)
            elif conversation_id:
                search_records = get_source_searches_by_conversation(
                    conversation_id, user_id)

            for record in search_records:
                search_item = {
                    "title": record["source_title"],
                    "text": record["source_content"],
                    "source_type": record["source_type"],
                    "url": record["source_location"],
                    "filename": record["source_title"] if record["source_type"] == "file" else None,
                    "published_date": record["published_date"].strftime("%Y-%m-%d") if record[
                        "published_date"] else None,
                    "score": record["score_overall"]
                }

                search_item["score_details"] = {}
                if record["score_accuracy"] is not None:
                    search_item["score_details"]["accuracy"] = record["score_accuracy"]
                if record["score_semantic"] is not None:
                    search_item["score_details"]["semantic"] = record["score_semantic"]

                if conversation_id and not message_id:
                    search_item["message_id"] = record["message_id"]

                searches.append(search_item)

            result["searches"] = searches

        return {
            "code": 0,
            "message": "success",
            "data": result
        }

    except Exception as e:
        logging.error(f"Failed to get message sources: {str(e)}")
        return {
            "code": 500,
            "message": str(e),
            "data": None
        }


async def generate_conversation_title_service(conversation_id: int, question: str, user_id: str, tenant_id: str, language: str = LANGUAGE["ZH"]) -> str:
    """
    Generate conversation title from user question

    This function is called immediately after user sends a message,
    generating title from the question instead of waiting for full conversation.

    Args:
        conversation_id: Conversation ID
        question: User's question content
        user_id: User ID
        tenant_id: Tenant ID
        language: Language code ('zh' for Chinese, 'en' for English)

    Returns:
        str: Generated title
    """
    try:
        # Call LLM to generate title from question in a separate thread to avoid blocking
        title = await asyncio.to_thread(call_llm_for_title, question, tenant_id, language)

        # Update conversation title
        update_conversation_title(conversation_id, title, user_id)

        return title

    except Exception as e:
        logging.error(f"Failed to generate conversation title: {str(e)}")
        raise Exception(str(e))


def update_message_opinion_service(message_id: int, opinion: Optional[str]) -> bool:
    """
    Update message like/dislike status

    Args:
        message_id: Message ID
        opinion: Opinion value ('Y' or 'N' or None)

    Returns:
        bool: Whether the update was successful
    """
    try:
        success = update_message_opinion(message_id, opinion)
        if not success:
            raise Exception("Message does not exist or has been deleted")
        return True
    except Exception as e:
        logging.error(f"Failed to update message like/dislike: {str(e)}")
        raise Exception(str(e))


async def get_message_id_by_index_impl(conversation_id: int, message_index: int) -> Optional[int]:
    message_id = get_message_id_by_index(conversation_id, message_index)
    if message_id is None:
        raise Exception("Message not found.")
    return message_id


def save_skill_files_to_conversation(
    conversation_id: int,
    skill_file_uploads: List[Dict[str, Any]],
    user_id: str,
) -> bool:
    """
    Append skill file upload records to the latest assistant message in a conversation.

    This persists generated documents (e.g., DOCX, XLSX created by skills) to the
    conversation history so they appear in subsequent GET /conversation/{id} calls.

    Args:
        conversation_id: Target conversation ID
        skill_file_uploads: List of upload metadata dicts (e.g., from upload_fileobj)
        user_id: User ID for ownership validation

    Returns:
        bool: True if files were saved, False if no assistant message was found
    """
    if not skill_file_uploads:
        return False

    try:
        message_id = get_latest_assistant_message_id(conversation_id, user_id)
        if message_id is None:
            logging.warning(
                "[skill-file] no assistant message found for conversation=%s, "
                "cannot persist skill file uploads",
                conversation_id,
            )
            return False

        success = update_message_minio_files(message_id, skill_file_uploads)
        if success:
            logging.info(
                "[skill-file] persisted %d file(s) to message_id=%s conversation=%s",
                len(skill_file_uploads),
                message_id,
                conversation_id,
            )
        return success
    except Exception:
        logging.exception(
            "[skill-file] failed to persist skill file uploads for conversation=%s",
            conversation_id,
        )
        return False
