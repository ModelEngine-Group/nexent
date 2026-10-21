# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict


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


HISTORY_SUMMARY_UNIT_TYPE = "history_summary"


class HistorySummaryPersistenceError(ValueError):
    """Raised when a history-summary candidate violates persistence rules."""


CHAT_MODE_VALUES = {"planning", "execution"}
