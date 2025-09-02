import asyncio
import json
import logging
from datetime import datetime
from http import HTTPStatus
from typing import List, Optional, Dict, Any

from fastapi import Header
from jinja2 import StrictUndefined, Template
from smolagents import OpenAIServerModel

from consts.model import MessageRequest, ConversationResponse, AgentRequest, MessageUnit
from database.conversation_db import create_conversation_message, create_source_search, create_message_units, \
    create_source_image, rename_conversation, get_conversation_list, get_conversation_history, \
    get_source_images_by_message, \
    get_source_images_by_conversation, get_source_searches_by_message, get_source_searches_by_conversation, \
    delete_conversation, get_conversation, create_conversation, update_message_opinion
from nexent.core.utils.observer import ProcessType
from utils.auth_utils import get_current_user_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.prompt_template_utils import get_generate_title_prompt_template
from utils.str_utils import remove_think_tags, add_no_think_token

logger = logging.getLogger("conversation_management_service")


def save_message(request: MessageRequest, authorization: Optional[str] = Header(None)):
    """
    Save a new message record

    Args:
        request: MessageRequest object containing:
            - conversation_id: Required, conversation ID
            - message_idx: Message index (integer type)
            - role: Message role
            - message: List of message units
            - minio_files: List of object_names for files stored in minio
        authorization: Authorization header

    Returns:
        ConversationResponse object:
            - code: 0 indicates success
            - data: true indicates successful save
            - message: "success" success message
    """
    try:
        # Authorization may be a FastAPI Header object or None when called outside a request
        user_id = None
        if isinstance(authorization, str) and authorization:
            try:
                user_id = get_current_user_id(authorization)
            except Exception as auth_error:
                logging.warning(
                    f"Ignoring authorization during save_message: {auth_error}")
        message_data = request.model_dump()

        # Validate conversation_id
        conversation_id = message_data.get('conversation_id')
        if not conversation_id:
            raise Exception("conversation_id is required, please call /conversation/create to create a conversation first")

        # Process different types of message units
        message_units = message_data['message']

        # Filter specific message units
        string_content = None
        other_units = []

        # First pass: Separate string/final_answer and other types
        for unit in message_units:
            unit_type = unit['type']
            unit_content = unit['content']

            if unit_type in ['string', 'final_answer']:
                string_content = unit_content
            else:
                other_units.append(unit)

        # Initialize message record data
        message_id = None
        minio_files = message_data.get('minio_files')

        # Process string/final_answer type, create message record
        if string_content is not None:
            message_data_copy = {'conversation_id': conversation_id, 'message_idx': message_data['message_idx'],
                                 'role': message_data['role'], 'content': string_content, 'minio_files': minio_files}
            message_id = create_conversation_message(
                message_data_copy, user_id)

        # If there are other types of units but no string type, create an empty content message for them
        if other_units and message_id is None:
            message_data_copy = {'conversation_id': conversation_id, 'message_idx': message_data['message_idx'],
                                 # Empty content
                                 'role': message_data['role'], 'content': "",
                                 'minio_files': minio_files}
            message_id = create_conversation_message(
                message_data_copy, user_id)

        # Process other types of units
        filtered_message_units = []
        search_content_units = []

        for unit in other_units:
            unit_type = unit['type']
            unit_content = unit['content']

            if unit_type == 'search_content':
                # Create a placeholder for the search content and process it later
                search_content_units.append(unit_content)
                filtered_message_units.append({
                    'type': 'search_content_placeholder',
                    'content': '{"placeholder": true}'
                })
            elif unit_type == 'picture_web':
                # Process image content, save as source_image, do not add to filtered_message_units
                try:
                    # Parse image URL list
                    import json
                    content_json = json.loads(unit_content)
                    if isinstance(content_json, dict) and 'images_url' in content_json:
                        for image_url in content_json['images_url']:
                            image_data = {'message_id': message_id, 'conversation_id': conversation_id,
                                          'image_url': image_url}
                            create_source_image(image_data)
                except Exception as e:
                    logging.error(f"Failed to save image content: {str(e)}")
            else:
                # Keep other types of message units
                filtered_message_units.append(unit)

        # Create message unit records and get unit_ids
        unit_ids = []
        if filtered_message_units and message_id is not None:
            unit_ids = create_message_units(
                filtered_message_units, message_id, conversation_id)

        # Process search content using corresponding unit_ids
        search_placeholder_index = 0
        for search_content in search_content_units:
            try:
                # Find the unit_id for this search content placeholder
                placeholder_unit_id = None
                current_index = 0
                for i, unit in enumerate(filtered_message_units):
                    if unit['type'] == 'search_content_placeholder':
                        if current_index == search_placeholder_index:
                            placeholder_unit_id = unit_ids[i]
                            break
                        current_index += 1

                if placeholder_unit_id is None:
                    logging.error(
                        "Could not find unit_id for search content placeholder")
                    continue

                # Parse search content
                import json
                search_results = json.loads(search_content)

                # Ensure search_results is a list
                if not isinstance(search_results, list):
                    search_results = [search_results]

                # Iterate through each search result and save separately
                for result in search_results:
                    search_data = {'message_id': message_id, 'conversation_id': conversation_id,
                                   'unit_id': placeholder_unit_id,  # Use the placeholder's unit_id
                                   'source_type': result.get('source_type', ''), 'source_title': result.get('title', ''),
                                   'source_location': result.get('url', ''), 'source_content': result.get('text', ''),
                                   'score_overall': float(result.get('score')) if result.get('score') and result.get(
                                       'score') != '' else None,
                                   'score_accuracy': float(result.get('score_details', {}).get('accuracy')) if result.get(
                                       'score_details', {}).get('accuracy') and result.get('score_details', {}).get(
                                       'accuracy') != '' else None,
                                   'score_semantic': float(result.get('score_details', {}).get('semantic')) if result.get(
                                       'score_details', {}).get('semantic') and result.get('score_details', {}).get(
                                       'semantic') != '' else None,
                                   'published_date': result.get('published_date') if result.get(
                                       'published_date') and result.get('published_date') != '' else None,
                                   'cite_index': result.get('cite_index', None) if result.get('cite_index') != '' else None,
                                   'search_type': result.get('search_type') if result.get('search_type') and result.get(
                                       'search_type') != '' else None, 'tool_sign': result.get('tool_sign', '')}
                    create_source_search(search_data, user_id)

                search_placeholder_index += 1

            except Exception as e:
                logging.error(f"Failed to save search content: {str(e)}")
                search_placeholder_index += 1

        return ConversationResponse(code=0, message="success", data=True)

    except Exception as e:
        logging.error(f"Failed to save message: {str(e)}")
        raise Exception(str(e))


def save_conversation_user(request: AgentRequest, authorization: Optional[str] = None):
    user_role_count = sum(1 for item in getattr(
        request, "history", []) if item.get("role") == "user")

    conversation_req = MessageRequest(conversation_id=request.conversation_id, message_idx=user_role_count * 2,
                                      role="user", message=[MessageUnit(type="string", content=request.query)], minio_files=request.minio_files)
    save_message(conversation_req, authorization=authorization)


def save_conversation_assistant(request: AgentRequest, messages: List[str], authorization: Optional[str] = None):
    user_role_count = sum(1 for item in getattr(
        request, "history", []) if item.get("role") == "user")

    message_list = []
    for item in messages:
        message = json.loads(item)
        if (len(message_list) and
            message.get("type") in [ProcessType.MODEL_OUTPUT_CODE.value, ProcessType.MODEL_OUTPUT_THINKING.value] and
                message.get("type") == message_list[-1].get("type")):
            message_list[-1]["content"] += message["content"]
        else:
            message_list.append(message)

    conversation_req = MessageRequest(conversation_id=request.conversation_id, message_idx=user_role_count * 2 + 1,
                                      role="assistant", message=message_list, minio_files=request.minio_files)
    save_message(conversation_req, authorization=authorization)


def extract_user_messages(history: List[Dict[str, str]]) -> str:
    """
    Extract user message content from conversation history

    Args:
        history: List of conversation history records

    Returns:
        str: Concatenated user message content
    """
    content = ""
    for message in history:
        if message.get("role") == "user" and message.get("content"):
            content += f"\n### User Question：\n{message['content']}\n"
        if message.get("role") == "assistant" and message.get("content"):
            content += f"\n### Response Content：\n{message['content']}\n"
    return content


def call_llm_for_title(content: str, tenant_id: str, language: str = 'zh') -> str:
    """
    Call LLM to generate a title

    Args:
        content: Conversation content
        tenant_id: Tenant ID
        language: Language code ('zh' for Chinese, 'en' for English)

    Returns:
        str: Generated title
    """
    prompt_template = get_generate_title_prompt_template(language=language)

    model_config = tenant_config_manager.get_model_config(
        key="LLM_ID", tenant_id=tenant_id)

    # Create OpenAIServerModel instance
    llm = OpenAIServerModel(model_id=get_model_name_from_config(model_config) if model_config.get("model_name") else "", api_base=model_config.get("base_url", ""),
                            api_key=model_config.get("api_key", ""), temperature=0.7, top_p=0.95)

    # Build messages
    user_prompt = Template(prompt_template["USER_PROMPT"], undefined=StrictUndefined).render({
        "content": content
    })
    messages = [{"role": "system",
                 "content": prompt_template["SYSTEM_PROMPT"]},
                {"role": "user",
                 "content": user_prompt}]
    add_no_think_token(messages)

    # Call the model
    response = llm(messages, max_tokens=10)

    return remove_think_tags(response.content.strip())


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
        raise Exception(f"Conversation {conversation_id} does not exist or has been deleted")
    return success


def create_new_conversation(title: str, user_id: str) -> Dict[str, Any]:
    """
    Create a new conversation

    Args:
        title: Conversation title
        user_id: User ID

    Returns:
        Dict containing conversation data
    """
    try:
        conversation_data = create_conversation(title, user_id)
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
        success = delete_conversation(conversation_id, user_id)
        if not success:
            raise Exception(f"Conversation {conversation_id} does not exist or has been deleted")
        return True
    except Exception as e:
        logging.error(f"Failed to delete conversation: {str(e)}")
        raise Exception(str(e))


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

        # Collect image content - grouped by message_id
        image_by_message = {}
        for record in history_data['image_records']:
            message_id = record['message_id']
            if message_id not in image_by_message:
                image_by_message[message_id] = []
            image_by_message[message_id].append(record['image_url'])

        # Sort by message index and build final message list, including images and search content
        messages = []

        for msg in history_data['message_records']:
            message_id = msg['message_id']
            role = msg['role']
            message_content = msg['message_content']
            # Initialize for all message types
            message_units = msg['units'] or []

            if role == 'user':
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

                # Add final_answer type message unit
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
            'create_time': history_data['create_time'],
            'message': messages
        }
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


async def generate_conversation_title_service(conversation_id: int, history: List[Dict[str, str]], user_id: str, tenant_id: str, language: str = 'zh') -> str:
    """
    Generate conversation title

    Args:
        conversation_id: Conversation ID
        history: Conversation history list
        user_id: User ID
        tenant_id: Tenant ID
        language: Language code ('zh' for Chinese, 'en' for English)

    Returns:
        str: Generated title
    """
    try:
        # Extract user messages
        content = extract_user_messages(history)

        # Call LLM to generate title in a separate thread to avoid blocking
        title = await asyncio.to_thread(call_llm_for_title, content, tenant_id, language)

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
