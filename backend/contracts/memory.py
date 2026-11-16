# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from nexent.scheduler import is_valid_cron_expression
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Memory Feature Data Models (Missing previously)
# ---------------------------------------------------------------------------
class MemoryAgentShareMode(str, Enum):
    """Memory sharing mode for agent-level memory.

    always: Agent memories are always shared with others.
    ask:    Ask user every time whether to share.
    never:  Never share agent memories.
    """

    ALWAYS = "always"
    ASK = "ask"
    NEVER = "never"

    @classmethod
    def default(cls) -> "MemoryAgentShareMode":
        return cls.NEVER


class DreamingRunRequest(BaseModel):
    target_user_id: Optional[str] = None


class DreamingScheduleRequest(BaseModel):
    enabled: bool
    rule_type: Literal["CRON", "INTERVAL"] = "CRON"
    timezone: str = "Asia/Shanghai"
    start_at: Optional[datetime] = None
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, ge=3600)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_recall_count: Optional[int] = Field(default=None, ge=0)
    min_unique_queries: Optional[int] = Field(default=None, ge=0)
    source_limit: Optional[int] = Field(default=None, ge=1, le=100)
    long_term_max_chars: Optional[int] = Field(default=None, ge=100, le=1000000)
    summarization_max_attempts: Optional[int] = Field(default=None, ge=0, le=10)
    target_user_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"Invalid timezone: {self.timezone}") from exc
        if self.rule_type == "CRON":
            if not is_valid_cron_expression(self.cron_expr or ""):
                raise ValueError("A valid five-field cron_expr is required")
            if self.interval_seconds is not None:
                raise ValueError("CRON schedule cannot include interval_seconds")
        else:
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required")
            if self.cron_expr is not None:
                raise ValueError("INTERVAL schedule cannot include cron_expr")
        return self


class CreateVersionRequest(BaseModel):
    content: str
    expected_active_version_id: Optional[int] = None


class ActivateVersionRequest(BaseModel):
    expected_active_version_id: Optional[int] = None


class ProviderConfigCreate(BaseModel):
    provider_name: str
    connection_type: Literal["plugin"] = "plugin"
    enabled: bool = False
    timeout_seconds: int = 30
    params: Dict[str, str] = Field(
        ...,
        description="EAV params, e.g. {'plugin.name': 'mem0', 'plugin.api_key': '...'}",
    )


class ProviderConfigUpdate(BaseModel):
    provider_name: Optional[str] = None
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    params: Optional[Dict[str, str]] = None


class TestSearchRequest(BaseModel):
    query: str
    top_k: int = 5


class TestIngestRequest(BaseModel):
    units: List[Dict[str, Any]] = Field(
        ..., description="List of MemoryIngestUnit dicts"
    )


class CreateMemoryRequest(BaseModel):
    layer: str = Field(..., description="tenant | user | agent")
    content: str = Field(..., min_length=1)
    memory_type: Optional[str] = Field(
        default=None,
        description="long_term | short_term; defaults by layer",
    )
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    concept_tags: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None
    concept_tags: Optional[List[str]] = None


class SearchMemoryRequest(BaseModel):
    query: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    layers: Optional[List[str]] = None
    top_k: int = 5
    threshold: float = 0.65
    hybrid: bool = Field(
        default=False,
        description=(
            "When true, agent short-term memory is retrieved via a hybrid "
            "(BM25 + kNN) query against Elasticsearch instead of pure "
            "kNN. Defaults to false to preserve prior behavior."
        ),
    )
    weight_accurate: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Weight of the fuzzy (BM25) branch when hybrid=true. The "
            "complementary 1 - weight is given to the semantic kNN branch."
        ),
    )
