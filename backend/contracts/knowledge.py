# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum

if TYPE_CHECKING:
    from contracts.tool import ToolParamsRequest


@dataclass
class ResolvedKnowledgeScope:
    """Runtime projection of a persisted conversation knowledge policy."""

    desired_scope: Dict[str, Any]
    tool_params: ToolParamsRequest
    local_knowledge_ids: List[str] = field(default_factory=list)
    local_index_names: List[str] = field(default_factory=list)
    local_display_names: List[str] = field(default_factory=list)
    aidp_kds_ids: List[str] = field(default_factory=list)
    aidp_display_names: List[str] = field(default_factory=list)
    local_disabled: bool = False
    aidp_disabled: bool = False
    local_capable: bool = True
    aidp_capable: bool = True
    warnings: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeStorageContext:
    """Validated ownership and object-bucket context for one KB upload."""

    tenant_id: str
    knowledge_id: int
    index_name: str
    bucket_name: str
    ingroup_permission: Optional[str] = None


@dataclass(frozen=True)
class StorageObjectReference:
    """Canonical MinIO object identity for an existing KB source path."""

    bucket_name: str
    object_name: str


@dataclass(frozen=True)
class ClassifiedIngestionException:
    """A durable error representation plus retry guidance for the active task."""

    error_code: Optional[str]
    error_message: Optional[str]
    retryable: bool


KnowledgeScopeMode = Literal["inherit", "override", "disabled"]


class LocalKnowledgeScopeRequest(BaseModel):
    """Conversation-scoped selection for local knowledge bases."""

    mode: KnowledgeScopeMode = "inherit"
    knowledge_ids: List[str] = Field(default_factory=list, max_length=50)

    @field_validator("knowledge_ids")
    @classmethod
    def normalize_knowledge_ids(cls, values: List[str]) -> List[str]:
        normalized = []
        for value in values:
            item = str(value).strip()
            if not item or len(item) > 32:
                raise ValueError(
                    "knowledge_ids must contain non-empty identifiers of at most 32 characters"
                )
            if item not in normalized:
                normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def validate_mode_and_ids(self):
        if self.mode == "override" and not self.knowledge_ids:
            raise ValueError("local override mode requires at least one knowledge_id")
        if self.mode != "override" and self.knowledge_ids:
            raise ValueError(f"local {self.mode} mode does not accept knowledge_ids")
        return self


class AidpKnowledgeScopeRequest(BaseModel):
    """Conversation-scoped selection for AIDP knowledge bases."""

    mode: KnowledgeScopeMode = "inherit"
    kds_ids: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("kds_ids")
    @classmethod
    def normalize_kds_ids(cls, values: List[str]) -> List[str]:
        normalized = []
        for value in values:
            item = str(value).strip()
            if not item or len(item) > 256:
                raise ValueError(
                    "kds_ids must contain non-empty identifiers of at most 256 characters"
                )
            if item not in normalized:
                normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def validate_mode_and_ids(self):
        if self.mode == "override" and not self.kds_ids:
            raise ValueError("AIDP override mode requires at least one kds_id")
        if self.mode != "override" and self.kds_ids:
            raise ValueError(f"AIDP {self.mode} mode does not accept kds_ids")
        return self


class ConversationKnowledgeScopeRequest(BaseModel):
    """Persisted business policy for conversation-scoped knowledge retrieval."""

    schema_version: Literal[1] = 1
    retrieval_config: Optional[Dict[str, Any]] = None

    @field_validator("retrieval_config")
    @classmethod
    def validate_retrieval_config(cls, values):
        if values is None:
            return None
        reserved = {
            "index_names",
            "kds_list",
            "display_names",
            "server_url",
            "api_key",
            "tenant_id",
            "observer",
            "kds_name_to_id_map",
            "allowed_kds_set",
            "allowed_index_names",
        }
        if len(values) > 30 or reserved.intersection(values):
            raise ValueError(
                "Retrieval parameters cannot contain connection settings or resource ranges"
            )
        return values

    local: LocalKnowledgeScopeRequest = Field(
        default_factory=LocalKnowledgeScopeRequest
    )
    aidp: AidpKnowledgeScopeRequest = Field(default_factory=AidpKnowledgeScopeRequest)


class ConversationKnowledgeScopeUpdateRequest(BaseModel):
    """Replace a conversation scope, or clear it with null to restore defaults."""

    scope: Optional[ConversationKnowledgeScopeRequest] = None
    expected_workbench_config_version: Optional[int] = Field(default=None, ge=0)


WorkbenchMode = Literal[
    "generic_chat",
    "single_agent_chat",
    "multi_agent_chat",
    "skill_create",
    "agent_create",
]


# Pydantic models for API
class TaskRequest(BaseModel):
    source: str
    source_type: str
    chunking_strategy: Optional[str] = None
    index_name: Optional[str] = None
    original_filename: Optional[str] = None
    embedding_model_id: Optional[int] = None
    tenant_id: Optional[str] = None
    file_id: Optional[str] = None
    telemetry_context: Dict[str, str] = Field(default_factory=dict)
    additional_params: Dict[str, Any] = Field(default_factory=dict)


class BatchTaskRequest(BaseModel):
    sources: List[Dict[str, Any]] = Field(
        ..., description="List of source objects to process"
    )


class IndexingResponse(BaseModel):
    success: bool
    message: str
    total_indexed: int
    total_submitted: int


class ChunkCreateRequest(BaseModel):
    """Request payload for manual chunk creation."""

    content: str = Field(..., min_length=1, description="Chunk content")
    title: Optional[str] = Field(None, description="Optional chunk title")
    filename: Optional[str] = Field(None, description="Associated file name")
    path_or_url: Optional[str] = Field(None, description="Source path or URL")
    chunk_id: Optional[str] = Field(None, description="Explicit chunk identifier")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional chunk metadata"
    )


class ChunkUpdateRequest(BaseModel):
    """Request payload for chunk updates."""

    content: Optional[str] = Field(None, description="Updated chunk content")
    title: Optional[str] = Field(None, description="Updated chunk title")
    filename: Optional[str] = Field(None, description="Updated file name")
    path_or_url: Optional[str] = Field(None, description="Updated source path or URL")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata updates"
    )


class HybridSearchRequest(BaseModel):
    """Request payload for hybrid knowledge-base searches."""

    query: str = Field(..., min_length=1, description="Search query text")
    index_names: List[str] = Field(
        ..., min_items=1, description="List of index names to search"
    )
    top_k: int = Field(10, ge=1, le=100, description="Number of results to return")
    weight_accurate: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional caller-specified weight applied to accurate search scores",
    )
    tag_predicates: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Document tag predicates: list of {definition_id, value_ids} "
        "groups combined with OR-within / AND-across semantics. Results are "
        "restricted to projection-confirmed documents when provided.",
    )


# Request models
class ProcessParams(BaseModel):
    chunking_strategy: Optional[str] = "basic"
    source_type: str
    index_name: str
    authorization: Optional[str] = None


# used in Knowledge Summary request
class ChangeSummaryRequest(BaseModel):
    summary_result: str


class KnowledgeBaseResolution(BaseModel):
    """User-selected resolution for an existing official knowledge base."""

    knowledge_name: str
    action: Literal["reuse", "create_new"]


class UpdateKnowledgeListRequest(BaseModel):
    """Request model for updating user's selected knowledge base list grouped by source"""

    nexent: Optional[List[str]] = Field(
        None, description="List of knowledge base index names from nexent source"
    )
    datamate: Optional[List[str]] = Field(
        None, description="List of knowledge base index names from datamate source"
    )


class SyncDatamateRequest(BaseModel):
    """Request body for syncing DataMate knowledge bases."""

    datamate_url: Optional[str] = None


class HaotianListRequest(BaseModel):
    list_url: str = Field(..., description="Haotian knowledge sets list URL")
    authorization: str = Field(
        ..., description="Authorization header value, e.g. 'Bearer xxx'"
    )


class HaotianTestConnectionRequest(BaseModel):
    list_url: str = Field(..., description="Haotian knowledge sets list URL")
    authorization: str = Field(
        ..., description="Authorization header value, e.g. 'Bearer xxx'"
    )


class IndependentAidpKnowledgeBaseListRequest(BaseModel):
    server_url: str = Field(..., description="Independent AIDP API base URL")
    api_key: str = Field(..., description="Independent AIDP API key")
    tenant_id: str = Field(default="aidp", description="AIDP tenant identifier")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)


# Vector database providers
class VectorDatabaseType(str, Enum):
    ELASTICSEARCH = "elasticsearch"
    DATAMATE = "datamate"
