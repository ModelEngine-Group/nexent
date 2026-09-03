import logging
from http import HTTPStatus
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from consts.model import (
    BatchDeleteConversationRequest,
    ConversationKnowledgeScopeUpdateRequest,
    ConversationRequest,
    ConversationResponse,
    GenerateTitleRequest,
    MessageIdRequest,
    OpinionRequest,
    RenameRequest,
)
from consts.exceptions import ConversationNotFoundError, ValidationError, TokenExpiredError
from database.conversation_db import get_conversation_list_page
from services.conversation_management_service import (
    create_new_conversation,
    delete_conversation_service,
    delete_conversations_batch_service,
    generate_conversation_title_service,
    get_conversation_history_service,
    get_sources_service,
    rename_conversation_service,
    update_conversation_knowledge_scope_service,
    update_message_opinion_service, get_message_id_by_index_impl,
)
from utils.auth_utils import get_current_user_id, get_current_user_info

router = APIRouter(prefix="/conversation")


@router.put("/create", response_model=ConversationResponse)
async def create_new_conversation_endpoint(request: ConversationRequest, authorization: Optional[str] = Header(None)):
    """
    Create a new conversation

    Args:
        request: ConversationRequest object containing:
            - title: Conversation title, default is "New Conversation"
        authorization: Authorization header

    Returns:
        ConversationResponse object containing:
            - conversation_id: Conversation ID
            - conversation_title: Conversation title
            - create_time: Creation timestamp (milliseconds)
            - update_time: Update timestamp (milliseconds)
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        conversation_data = create_new_conversation(request.title, user_id)
        return ConversationResponse(code=0, message="success", data=conversation_data)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to create conversation: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/list", response_model=ConversationResponse)
async def list_conversations_endpoint(
    today_start_ms: Annotated[int, Query(ge=0)],
    week_start_ms: Annotated[int, Query(ge=0)],
    authorization: Optional[str] = Header(None),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[Optional[int], Query(ge=1, le=100)] = None,
):
    """
    Get all conversation list

    Args:
        authorization: Authorization header

    Returns:
        ConversationResponse object containing conversation list
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        if not user_id:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Unauthorized access, Please login first")
        conversations = get_conversation_list_page(
            user_id=user_id,
            today_start_ms=today_start_ms,
            week_start_ms=week_start_ms,
            limit=limit,
            offset=offset,
        )
        return ConversationResponse(code=0, message="success", data=conversations)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to get conversation list: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/rename", response_model=ConversationResponse)
async def rename_conversation_endpoint(request: RenameRequest, authorization: Optional[str] = Header(None)):
    """
    Rename a conversation

    Args:
        request: RenameRequest object containing:
            - conversation_id: Conversation ID
            - name: New conversation title
        authorization: Authorization header

    Returns:
        ConversationResponse object
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        rename_conversation_service(
            request.conversation_id, request.name, user_id)
        return ConversationResponse(code=0, message="success", data=True)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to rename conversation: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{conversation_id}", response_model=ConversationResponse)
async def delete_conversation_endpoint(conversation_id: int, authorization: Optional[str] = Header(None)):
    """
    Delete specified conversation

    Args:
        conversation_id: Conversation ID to delete
        authorization: Authorization header

    Returns:
        ConversationResponse object
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        delete_conversation_service(conversation_id, user_id)
        return ConversationResponse(code=0, message="success", data=True)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to delete conversation: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/batch-delete", response_model=ConversationResponse)
async def delete_conversations_batch_endpoint(request: BatchDeleteConversationRequest, authorization: Annotated[Optional[str], Header()] = None):
    """
    Batch-delete conversations owned by the current user

    Args:
        request: BatchDeleteConversationRequest containing conversation_ids
        authorization: Authorization header

    Returns:
        ConversationResponse with deleted_count and failed_ids
    """
    try:
        user_id, _ = get_current_user_id(authorization)
        result = delete_conversations_batch_service(request.conversation_ids, user_id)
        return ConversationResponse(code=0, message="success", data=result)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.exception("Failed to batch delete conversations")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_history_endpoint(conversation_id: int, authorization: Optional[str] = Header(None)):
    """
    Get complete history of specified conversation

    Args:
        conversation_id: Conversation ID
        authorization: Authorization header

    Returns:
        ConversationResponse object containing conversation history
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        history_data = get_conversation_history_service(
            conversation_id, user_id)
        return ConversationResponse(code=0, message="success", data=history_data)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to get conversation history: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/{conversation_id}/knowledge-scope", response_model=ConversationResponse)
async def update_conversation_knowledge_scope_endpoint(
    conversation_id: int,
    request: ConversationKnowledgeScopeUpdateRequest,
    authorization: Optional[str] = Header(None),
):
    """Replace the desired knowledge scope for an existing conversation."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        scope = request.scope.model_dump(mode="json") if request.scope is not None else None
        result = update_conversation_knowledge_scope_service(
            conversation_id=conversation_id,
            knowledge_scope=scope,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return ConversationResponse(
            code=0,
            message="success",
            data=result,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logging.error("Failed to update conversation knowledge scope: %s", exc)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/sources", response_model=Dict[str, Any])
async def get_sources_endpoint(request: Dict[str, Any], authorization: Optional[str] = Header(None)):
    """
    Get message source information (images and search results)

    Args:
        request: Request body containing optional fields:
            - conversation_id: Conversation ID
            - message_id: Message ID
            - type: Source type, default is "all", options are "image", "search", or "all"
        authorization: Authorization header

    Returns:
        Dict containing source information
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        conversation_id = request.get("conversation_id")
        message_id = request.get("message_id")
        source_type = request.get("type", "all")
        return get_sources_service(conversation_id, message_id, source_type, user_id)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to get message sources: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/generate_title", response_model=ConversationResponse)
async def generate_conversation_title_endpoint(
        request: GenerateTitleRequest,
        http_request: Request,
        authorization: Optional[str] = Header(None)
):
    """
    Generate conversation title from user question

    This endpoint generates title immediately after user sends a message,
    using only the question content instead of waiting for full conversation.

    Args:
        request: GenerateTitleRequest object containing:
            - conversation_id: Conversation ID
            - question: User's question content
        http_request: http request containing language info
        authorization: Authorization header

    Returns:
        ConversationResponse object containing generated title
    """
    try:
        user_id, tenant_id, language = get_current_user_info(
            authorization=authorization, request=http_request)
        title = await generate_conversation_title_service(
            request.conversation_id, request.question, user_id, tenant_id=tenant_id, language=language)
        return ConversationResponse(code=0, message="success", data=title)
    except TokenExpiredError as e:
        logging.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logging.error(f"Failed to generate conversation title: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/message/update_opinion", response_model=ConversationResponse)
async def update_opinion_endpoint(request: OpinionRequest, authorization: Optional[str] = Header(None)):
    """
    Update message like/dislike status

    Args:
        request: OpinionRequest object containing message_id and opinion
        authorization: Authorization header

    Returns:
        ConversationResponse object
    """
    try:
        update_message_opinion_service(request.message_id, request.opinion)
        return ConversationResponse(code=0, message="success", data=True)
    except Exception as e:
        logging.error(f"Failed to update message like/dislike: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/message/id", response_model=ConversationResponse)
async def get_message_id_endpoint(request: MessageIdRequest):
    """
    Get message ID by conversation ID and message index

    Args:
        request: MessageIdRequest object containing:
            - conversation_id: Conversation ID
            - message_index: Message index

    Returns:
        ConversationResponse object containing message_id
    """
    try:
        message_id = await get_message_id_by_index_impl(request.conversation_id, request.message_index)
        return ConversationResponse(code=0, message="success", data=message_id)
    except Exception as e:
        logging.error(f"Failed to get message ID: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))
