# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Conversation messages, reply annotations and opaque activity pagination cursors."""

import base64
import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from contracts.clarification import ClarificationResponse


# Unit type used for the per-message annotation payload persisted on user
# messages through conversation_message_unit_t.
MESSAGE_ANNOTATIONS_UNIT_TYPE = "message_annotations"

# Defensive caps mirroring the client-side limits; the backend truncates
# rather than rejects so oversized payloads never break a send.
ANNOTATION_QUOTED_TEXT_MAX_CHARS = 1500
ANNOTATION_COMMENT_MAX_CHARS = 500
ANNOTATION_SOURCE_EXCERPT_MAX_CHARS = 120
ANNOTATION_MAX_COUNT = 10


class MessageAnnotationItem(BaseModel):
    """One quoted excerpt attached to an outgoing user message.

    Length caps are enforced by ``normalize_message_annotations`` (truncating
    rather than rejecting) so oversized client payloads degrade gracefully
    instead of failing the whole send. Legacy neighboring-context fields are
    ignored when reading requests and persisted units.
    """

    quoted_text: str
    comment: Optional[str] = None
    source_excerpt: Optional[str] = None


def normalize_message_annotations(
    raw: Any,
) -> Optional[List[MessageAnnotationItem]]:
    """Validate raw annotation payloads, applying defensive caps.

    Accepts a list of annotation dicts (or models) as delivered by the
    request body or read back from a persisted unit. Entries without usable
    quoted text are dropped, over-length fields are truncated, and the list
    is capped to ``ANNOTATION_MAX_COUNT``. Returns ``None`` when nothing
    usable remains so callers can skip persistence and merging entirely.
    """
    if not isinstance(raw, list):
        return None

    annotations: List[MessageAnnotationItem] = []
    for item in raw:
        try:
            annotation = (
                item
                if isinstance(item, MessageAnnotationItem)
                else MessageAnnotationItem.model_validate(item)
            )
        except (ValueError, TypeError):
            continue
        quoted = annotation.quoted_text.strip()
        if not quoted:
            continue
        comment = (annotation.comment or "").strip() or None
        excerpt = (annotation.source_excerpt or "").strip() or None
        annotations.append(
            MessageAnnotationItem(
                quoted_text=quoted[:ANNOTATION_QUOTED_TEXT_MAX_CHARS],
                comment=comment[:ANNOTATION_COMMENT_MAX_CHARS] if comment else None,
                source_excerpt=(
                    excerpt[:ANNOTATION_SOURCE_EXCERPT_MAX_CHARS]
                    if excerpt
                    else None
                ),
            )
        )
        if len(annotations) >= ANNOTATION_MAX_COUNT:
            break

    return annotations or None


def parse_message_annotation_unit(unit_content: Optional[str]) -> Optional[List[MessageAnnotationItem]]:
    """Parse a persisted ``message_annotations`` unit payload.

    Returns the normalized annotations, or ``None`` for missing/invalid
    payloads so history readers can skip the field entirely.
    """
    if not unit_content:
        return None
    try:
        payload = json.loads(unit_content)
    except (ValueError, TypeError):
        return None
    return normalize_message_annotations(payload)


def _annotation_block(index: int, annotation: MessageAnnotationItem) -> str:
    # The reply intro is a UI label, not reliable model-facing context.
    lines = [f"{index}. Quote:"]
    for line in annotation.quoted_text.split("\n"):
        lines.append(f"> {line}" if line else ">")
    if annotation.comment:
        lines.append(f"Comment: {annotation.comment}")
    return "\n".join(lines)


def format_annotations_for_llm(
    text: str, annotations: Optional[List[MessageAnnotationItem]]
) -> str:
    """Merge annotation blocks into the model-facing user text.

    Each annotation becomes a numbered quote block (blockquote excerpt plus
    an optional comment line); the blocks are joined with blank lines and
    separated from the user's own text by a horizontal rule so the model
    receives both the quoted reply excerpts and the follow-up question in
    one message. With no annotations the text is returned unchanged.
    """
    if not annotations:
        return text

    blocks = [
        _annotation_block(index, annotation)
        for index, annotation in enumerate(annotations, start=1)
    ]
    quote_block = "\n\n".join(blocks)
    body = text or ""
    return f"{quote_block}\n\n---\n\n{body}" if body else quote_block


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
    clarification_response: Optional[ClarificationResponse] = None
    # Reply annotations ("add to chat" quotes) attached to this user message
    annotations: Optional[List[MessageAnnotationItem]] = None
    # Complete list of attachment information
    minio_files: Optional[List[Dict[str, Any]]] = None


class ConversationTarget(BaseModel):
    """Resource edited by a creator conversation, distinct from its executor."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["agent", "skill"]
    id: StrictInt = Field(gt=0)


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


class BranchConversationRequest(BaseModel):
    conversation_id: int
    # 1-based Q&A turn (inclusive) that marks the branch point
    turn_index: int
    # Persisted answer ID, or the runtime's 1-based answer version before reload.
    source_message_id: Optional[StrictInt] = Field(default=None, gt=0)
    answer_index: Optional[StrictInt] = Field(default=None, gt=0)


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
    target: Optional[Dict[str, Any]]
    agent_system_key: Optional[str]
    knowledge_scope: Optional[Dict[str, Any]]
    runtime_metadata: Dict[str, Any]
    runtime_metadata_version: int
    workbench_config: Optional[Dict[str, Any]]
    workbench_config_version: int
    create_time: int
    message_records: List[MessageRecord]
    search_records: List[SearchRecord]
    image_records: List[ImageRecord]


class ConversationModelPreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    delete_parameters: List[str] = Field(default_factory=list, max_length=128)


class ConversationModelSelectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_model_id: int = Field(gt=0, lt=2**31, strict=True)


def _search_fingerprint(search: str) -> str:
    return hashlib.sha256(search.strip().casefold().encode("utf-8")).hexdigest()


def encode_agent_group_cursor(activity: datetime, group_id: int, search: str) -> str:
    """Encode an opaque group cursor bound to the current search query."""
    value = [
        conversation_time_as_utc(activity).isoformat(),
        group_id,
        _search_fingerprint(search),
    ]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_agent_group_cursor(cursor: str, search: str) -> tuple[datetime, int]:
    """Decode an agent-group cursor and reject cursors from another query."""
    try:
        if not cursor or len(cursor) > 512:
            raise ValueError
        value = json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4),
                altchars=b"-_",
                validate=True,
            )
        )
        if (
            not isinstance(value, list)
            or len(value) != 3
            or not isinstance(value[0], str)
            or type(value[1]) is not int
            or value[1] < -1
            or value[1] == 0
            or value[2] != _search_fingerprint(search)
        ):
            raise ValueError
        activity = datetime.fromisoformat(value[0])
        if activity.tzinfo is None:
            raise ValueError
        return activity.astimezone(timezone.utc), value[1]
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError("Invalid agent group cursor") from exc


def encode_agent_conversation_cursor(
    activity: datetime, conversation_id: int, group_key: str, search: str
) -> str:
    """Encode a group conversation cursor bound to its group and search."""
    value = [
        conversation_time_as_utc(activity).isoformat(),
        conversation_id,
        group_key,
        _search_fingerprint(search),
    ]
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_agent_conversation_cursor(
    cursor: str, group_key: str, search: str
) -> tuple[datetime, int]:
    """Decode a per-group conversation cursor and validate its query scope."""
    try:
        if not cursor or len(cursor) > 512:
            raise ValueError
        value = json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4),
                altchars=b"-_",
                validate=True,
            )
        )
        if (
            not isinstance(value, list)
            or len(value) != 4
            or not isinstance(value[0], str)
            or type(value[1]) is not int
            or value[1] <= 0
            or value[2] != group_key
            or value[3] != _search_fingerprint(search)
        ):
            raise ValueError
        activity = datetime.fromisoformat(value[0])
        if activity.tzinfo is None:
            raise ValueError
        return activity.astimezone(timezone.utc), value[1]
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError("Invalid agent conversation cursor") from exc

