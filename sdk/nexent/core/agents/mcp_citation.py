# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Citation annotation wrapper for MCP retrieval tools.

MCP tools (e.g. data-platform RAG search) return plain JSON text without the
citation metadata Nexent uses for reference marks. This module detects
retrieval-shaped JSON results returned by an MCP tool, assigns citation
indexes, reports them through the observer search-content channel and
rewrites the model-facing payload with reference marks, so citation
rendering works exactly like built-in search tools without any backend or
frontend change.
"""

import functools
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolSign

logger = logging.getLogger(__name__)

# Field candidates commonly used by retrieval/RAG MCP tools.
_TEXT_FIELDS = ("text", "content", "chunk_content", "chunk_text", "chunk", "snippet", "segment", "passage", "page_content")
_TITLE_FIELDS = ("title", "name", "doc_title", "document_name", "document_title")
# file_url is the attachment file address used by data-platform RAG chunks.
_URL_FIELDS = ("url", "link", "source_url", "uri", "web_url", "file_url")
# knowledge_doc_id is the last filename fallback so data-platform documents
# without a real file name stay traceable in the citation UI title chain.
_FILENAME_FIELDS = ("filename", "file_name", "doc_name", "knowledge_doc_id")
_DATE_FIELDS = ("published_date", "publish_date", "date", "created_at", "create_time")
_SCORE_FIELDS = ("score", "similarity", "relevance", "similarity_score")
# Keys under which a retrieval list is typically nested in a JSON object.
_LIST_KEYS = ("results", "data", "items", "chunks", "documents", "records", "list")
# Identity fields proving an entry is a document rather than arbitrary text.
_IDENTITY_FIELDS = _TITLE_FIELDS + _URL_FIELDS + _FILENAME_FIELDS + ("source", "source_name")
# Chunk identity fields of data-platform RAG MCP tools, normalized into the
# unified score_details shape produced by built-in AIDP search tools.
_CHUNK_ID_FIELDS = ("chunk_id", "id", "text_id")
_KNOWLEDGE_DOC_ID_FIELDS = ("knowledge_doc_id",)
_RETRIEVAL_SOURCE_FIELDS = ("retrieval_source", "source")
_CHUNK_TYPE_FIELDS = ("chunk_type",)
_PAGES_FIELDS = ("pages",)
_FILE_URL_FIELDS = ("file_url",)
# Inline <img> tags embedded in data-platform RAG chunk text are stripped the
# same way built-in AIDP search tools do before reporting citation content.
_HTML_IMAGE_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
# Minimum characters a text-like field must contain to count as a chunk.
_MIN_TEXT_LENGTH = 10
# Minimum share of items that must carry an identity field.
_IDENTITY_RATIO = 0.5


def _first_str(source: Dict[str, Any], fields: Sequence[str]) -> Optional[str]:
    """Return the first non-empty string value among the candidate fields."""
    for field in fields:
        value = source.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _has_value(source: Dict[str, Any], field: str) -> bool:
    """Check whether a field carries a meaningful (non-empty) value."""
    value = source.get(field)
    if value is None:
        return False
    return not isinstance(value, str) or bool(value.strip())


def _extract_result_items(payload: Any) -> Optional[List[Any]]:
    """Extract the candidate result list from a parsed JSON payload."""
    if isinstance(payload, list):
        return payload if payload else None
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list) and value:
                return value
        if _first_str(payload, _TEXT_FIELDS) is not None:
            return [payload]
    return None


def _looks_like_retrieval_result(items: List[Any]) -> bool:
    """Heuristically decide whether the items represent retrieval results.

    Every item must be a mapping with a text-like field long enough to be a
    chunk, and at least half of the items must carry an identity field
    (title/url/filename/source-like) so that unrelated JSON tool outputs
    (e.g. installed-tool listings) are not misdetected.
    """
    if not items:
        return False
    identity_count = 0
    for item in items:
        if not isinstance(item, dict):
            return False
        text = _first_str(item, _TEXT_FIELDS)
        if text is None or len(text.strip()) < _MIN_TEXT_LENGTH:
            return False
        if any(_has_value(item, field) for field in _IDENTITY_FIELDS):
            identity_count += 1
    return identity_count >= len(items) * _IDENTITY_RATIO


def _pick_str(item: Dict[str, Any], metadata: Dict[str, Any], fields: Sequence[str]) -> str:
    """Pick the first non-empty string field from the item, then metadata."""
    for source in (item, metadata):
        value = _first_str(source, fields)
        if value is not None:
            return value
    return ""


def _pick_value(item: Dict[str, Any], metadata: Dict[str, Any], fields: Sequence[str]) -> Any:
    """Pick the first meaningful field value (any type) from item, then metadata."""
    for source in (item, metadata):
        for field in fields:
            if _has_value(source, field):
                return source.get(field)
    return None


def _pick_score(item: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    """Pick a numeric or textual score from the item, then metadata."""
    for source in (item, metadata):
        for field in _SCORE_FIELDS:
            value = source.get(field)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _build_score_details(item: Dict[str, Any], metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize chunk identity fields into the unified score_details shape.

    Mirrors the mapping of built-in AIDP search tools so data-platform RAG
    chunks (knowledge_doc_id/chunk_id/source/chunk_type/pages/file_url) keep
    their retrieval identity in the citation UI. Payloads without any of
    these fields fall back to the raw metadata mapping.
    """
    details: Dict[str, Any] = {}
    chunk_id = _pick_value(item, metadata, _CHUNK_ID_FIELDS)
    if chunk_id is not None:
        details["chunk_id"] = chunk_id
    knowledge_doc_id = _pick_value(item, metadata, _KNOWLEDGE_DOC_ID_FIELDS)
    if knowledge_doc_id is not None:
        details["knowledge_doc_id"] = knowledge_doc_id
    retrieval_source = _pick_value(item, metadata, _RETRIEVAL_SOURCE_FIELDS)
    if retrieval_source is not None:
        details["retrieval_source"] = retrieval_source
    chunk_type = _pick_value(item, metadata, _CHUNK_TYPE_FIELDS)
    if chunk_type is not None:
        details["chunk_type"] = str(chunk_type)
    pages = _pick_value(item, metadata, _PAGES_FIELDS)
    if pages is not None:
        details["pages"] = pages
    file_url = _pick_value(item, metadata, _FILE_URL_FIELDS)
    if file_url is not None:
        details["file_url"] = file_url
    if details:
        details["metadata"] = metadata
        return details
    return metadata if metadata else None


def _build_search_result_message(
    item: Dict[str, Any],
    cite_index: int,
    search_type: str,
    tool_sign: str,
) -> SearchResultTextMessage:
    """Map a raw retrieval item onto the unified search result message."""
    raw_metadata = item.get("metadata")
    if not isinstance(raw_metadata, dict):
        raw_metadata = item.get("meta")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

    # Strip inline <img> tags once here: the shared text field feeds both the
    # observer (UI) channel and the model-facing payload.
    text = _HTML_IMAGE_TAG_PATTERN.sub("", _pick_str(item, metadata, _TEXT_FIELDS))
    title = _pick_str(item, metadata, _TITLE_FIELDS)
    url = _pick_str(item, metadata, _URL_FIELDS)
    filename = _pick_str(item, metadata, _FILENAME_FIELDS)
    published_date = _pick_str(item, metadata, _DATE_FIELDS)
    score = _pick_score(item, metadata)

    return SearchResultTextMessage(
        title=title,
        url=url,
        text=text,
        published_date=published_date or None,
        source_type="url" if url else "file",
        filename=filename or None,
        score=score or None,
        score_details=_build_score_details(item, metadata),
        cite_index=cite_index,
        search_type=search_type,
        tool_sign=tool_sign,
    )


def annotate_mcp_search_results(
    result_text: Any,
    observer: Optional[MessageObserver],
    tool_name: str = "",
) -> Optional[str]:
    """Annotate a retrieval-shaped JSON result with citation metadata.

    Returns the rewritten model-facing JSON string, or ``None`` when the
    result does not look like a retrieval result (callers keep the original
    output unchanged in that case).
    """
    if observer is None or not isinstance(result_text, str) or not result_text.strip():
        return None
    try:
        payload = json.loads(result_text)
    except (TypeError, ValueError):
        return None

    items = _extract_result_items(payload)
    if items is None or not _looks_like_retrieval_result(items):
        return None

    tool_sign = ToolSign.MCP_SEARCH.value
    start_index = observer.reserve_citations(tool_sign, len(items))
    messages = [
        _build_search_result_message(item, start_index + offset, tool_name, tool_sign)
        for offset, item in enumerate(items)
    ]
    observer.add_message(
        "",
        ProcessType.SEARCH_CONTENT,
        json.dumps([message.to_dict() for message in messages], ensure_ascii=False),
    )
    return json.dumps([message.to_model_dict() for message in messages], ensure_ascii=False)


def wrap_mcp_tool_with_citation(tool: Any, observer: Optional[MessageObserver]) -> Any:
    """Wrap an MCP tool forward so retrieval results carry citation marks.

    Non-retrieval outputs pass through unchanged; annotation failures never
    break the underlying tool call.
    """
    if observer is None or getattr(tool, "_nexent_mcp_citation_wrapped", False):
        return tool

    original_forward = tool.forward
    tool_name = getattr(tool, "name", "") or ""

    def _annotate(result: Any) -> Any:
        try:
            annotated = annotate_mcp_search_results(result, observer, tool_name)
        except Exception:
            logger.exception("Failed to annotate MCP search results for tool %s", tool_name)
            return result
        return annotated if annotated is not None else result

    if inspect.iscoroutinefunction(original_forward):
        @functools.wraps(original_forward)
        async def forward(*args, **kwargs):
            return _annotate(await original_forward(*args, **kwargs))
    else:
        @functools.wraps(original_forward)
        def forward(*args, **kwargs):
            return _annotate(original_forward(*args, **kwargs))

    tool.forward = forward
    try:
        setattr(tool, "_nexent_mcp_citation_wrapped", True)
    except (AttributeError, TypeError):
        pass
    return tool
