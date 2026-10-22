# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Internal message provenance and opaque activity pagination cursors."""

import base64
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel, Field


class MessageSource(str, Enum):
    CHAT = "CHAT"
    AUTOMATION = "AUTOMATION"


def conversation_time_as_utc(value: datetime) -> datetime:
    """Interpret naive storage values as UTC and normalize aware instants."""
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def encode_activity_cursor(activity: datetime, conversation_id: int) -> str:
    value = [conversation_time_as_utc(activity).isoformat(), conversation_id]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_activity_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        if not cursor or len(cursor) > 512:
            raise ValueError
        value = json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
            )
        )
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        activity = datetime.fromisoformat(value[0])
        identity = value[1]
        if activity.tzinfo is None or type(identity) is not int or identity <= 0:
            raise ValueError
        return activity.astimezone(timezone.utc), identity
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError("Invalid conversation activity cursor") from exc


# Request models
class HistoryItem(BaseModel):
    role: str
    content: str
    minio_files: Optional[List[Dict[str, Any]]] = None


class MessageUnit(BaseModel):
    type: str
    content: str
    tool_call_id: Optional[str] = None


class MessageRequest(BaseModel):
    conversation_id: int  # Modified to integer type to match database auto-increment ID
    message_idx: int  # Modified to integer type
    role: str
    message: List[MessageUnit]
    # Complete list of attachment information
    minio_files: Optional[List[Dict[str, Any]]] = None


class ConversationRequest(BaseModel):
    title: str = "新对话"


class ConversationResponse(BaseModel):
    code: int = 0  # Modified default value to 0
    message: str = "success"
    data: Any


class RenameRequest(BaseModel):
    conversation_id: int
    name: str
    only_if_default_title: bool = False


class BatchDeleteConversationRequest(BaseModel):
    conversation_ids: List[int]


class OpinionRequest(BaseModel):
    message_id: int
    opinion: Optional[str] = None


class GenerateTitleRequest(BaseModel):
    conversation_id: int
    question: str
    model_id: Optional[int] = Field(default=None, gt=0)


class MessageIdRequest(BaseModel):
    conversation_id: int
    message_index: int


class CreateConversationShareRequest(BaseModel):
    mode: str = "selected"
    selected_user_message_ids: Optional[List[int]] = None
    expire_time: Optional[datetime] = None
    render_version: str = "legacy"


class MessageRecord(TypedDict):
    message_id: int
    message_index: int
    role: str
    create_time: Optional[int]
    type: Optional[str]
    content: Optional[str]
    opinion_flag: Optional[str]


class SearchRecord(TypedDict):
    message_id: int
    source_type: str
    source_title: str
    source_location: str
    source_content: str
    score_overall: Optional[float]
    score_accuracy: Optional[float]
    score_semantic: Optional[float]
    retrieval_highlight_terms: Optional[List[str]]
    aidp_metadata: Optional[Dict[str, Any]]
    aidp_source_reference: Optional[Dict[str, Any]]
    published_date: Optional[datetime]
    cite_index: Optional[int]
    search_type: Optional[str]
    tool_sign: Optional[str]


class ImageRecord(TypedDict):
    message_id: int
    image_url: str


class ConversationHistory(TypedDict):
    conversation_id: int
    conversation_title: str
    agent_id: Optional[int]
    knowledge_scope: Optional[Dict[str, Any]]
    runtime_metadata: Dict[str, Any]
    runtime_metadata_version: int
    workbench_config: Optional[Dict[str, Any]]
    workbench_config_version: int
    create_time: int
    message_records: List[MessageRecord]
    search_records: List[SearchRecord]
    image_records: List[ImageRecord]
