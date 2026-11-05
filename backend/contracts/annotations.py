# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Structured reply annotations attached to an outgoing user message.

The "add to chat" flow lets a user quote excerpts of an assistant reply
(optionally with a comment) and attach them to the next outgoing message.
Annotations travel as a structured field on ``AgentRequest``, are persisted
on the user message as a ``message_annotations`` unit, and are merged into
the model-facing text at request time so the stored message text stays
clean (mirroring how ``clarification_response`` is handled).
"""

import json
from typing import Any, List, Optional

from pydantic import BaseModel

# Unit type used for the per-message annotation payload persisted on user
# messages through conversation_message_unit_t.
MESSAGE_ANNOTATIONS_UNIT_TYPE = "message_annotations"

# Defensive caps mirroring the client-side limits; the backend truncates
# rather than rejects so oversized payloads never break a send.
ANNOTATION_QUOTED_TEXT_MAX_CHARS = 1500
ANNOTATION_COMMENT_MAX_CHARS = 500
ANNOTATION_SOURCE_EXCERPT_MAX_CHARS = 120
ANNOTATION_MAX_COUNT = 10
ANNOTATION_CONTEXT_MAX_CHARS = 200


class MessageAnnotationItem(BaseModel):
    """One quoted excerpt attached to an outgoing user message.

    Length caps are enforced by ``normalize_message_annotations`` (truncating
    rather than rejecting) so oversized client payloads degrade gracefully
    instead of failing the whole send.
    """

    quoted_text: str
    comment: Optional[str] = None
    source_excerpt: Optional[str] = None
    context_before: Optional[str] = None
    context_after: Optional[str] = None


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
        before = (annotation.context_before or "").strip() or None
        after = (annotation.context_after or "").strip() or None
        annotations.append(
            MessageAnnotationItem(
                quoted_text=quoted[:ANNOTATION_QUOTED_TEXT_MAX_CHARS],
                comment=comment[:ANNOTATION_COMMENT_MAX_CHARS] if comment else None,
                source_excerpt=(
                    excerpt[:ANNOTATION_SOURCE_EXCERPT_MAX_CHARS]
                    if excerpt
                    else None
                ),
                context_before=before[-ANNOTATION_CONTEXT_MAX_CHARS:] if before else None,
                context_after=after[:ANNOTATION_CONTEXT_MAX_CHARS] if after else None,
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
    if annotation.context_before:
        lines.append("Context before (not selected):")
        lines.extend(f"> {line}" for line in annotation.context_before.split("\n"))
    if annotation.context_before or annotation.context_after:
        lines.append("Selected text:")
    for line in annotation.quoted_text.split("\n"):
        lines.append(f"> {line}" if line else ">")
    if annotation.context_after:
        lines.append("Context after (not selected):")
        lines.extend(f"> {line}" for line in annotation.context_after.split("\n"))
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
