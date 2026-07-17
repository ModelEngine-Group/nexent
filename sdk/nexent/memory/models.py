"""Data models for the Nexent Memory system.

This module defines the core data structures used across the memory system,
including internal memory records and external provider interfaces.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemoryLayer(str, Enum):
    """Memory layer enumeration.

    Memory is organized into three layers:
    - tenant: Tenant-level long-term memory (PostgreSQL only)
    - user: User-level long-term memory (PostgreSQL only)
    - agent: Agent-level short-term memory (PostgreSQL + Elasticsearch)
    """
    TENANT = "tenant"
    USER = "user"
    AGENT = "agent"


class MemoryType(str, Enum):
    """Memory type within each layer."""
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class MemoryStatus(str, Enum):
    """Memory record status."""
    ACTIVE = "active"
    ARCHIVED = "archived"


class MemoryRecord(BaseModel):
    """Internal memory record stored in PostgreSQL and/or Elasticsearch.

    This is the core data model for all memory operations within Nexent.
    """
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    user_id: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None

    layer: MemoryLayer
    memory_type: MemoryType

    content: str
    concept_tags: List[str] = Field(default_factory=list)

    # Retrieval statistics
    recall_count: int = 0
    daily_count: int = 0
    grounded_count: int = 0
    last_recalled_at: Optional[datetime] = None
    query_hashes: List[str] = Field(default_factory=list)
    recall_days: List[str] = Field(default_factory=list)

    # Dreaming statistics
    light_hits: int = 0
    rem_hits: int = 0
    last_light_at: Optional[datetime] = None
    last_rem_at: Optional[datetime] = None

    # Metadata
    idempotency_key: str
    status: MemoryStatus = MemoryStatus.ACTIVE
    deleted_flag: str = "N"

    # Audit fields
    create_time: datetime = Field(default_factory=datetime.utcnow)
    update_time: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        use_enum_values = True


class ExternalMemoryItem(BaseModel):
    """Memory item returned from external providers.

    This model is used for search results from external memory providers.
    External items are not persisted internally and are used for
    temporary augmentation of memory context.
    """
    id: str
    content: str
    score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    provider: str
    created_at: Optional[datetime] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class MemorySearchRequest(BaseModel):
    """Request model for memory search operations."""
    query: str
    tenant_id: str
    user_id: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    layers: List[MemoryLayer] = Field(default_factory=list)
    top_k: int = 5
    limit: int = 5
    threshold: Optional[float] = 0.65
    embedding: Optional[List[float]] = None
    # When True, the index service is asked to run a hybrid (BM25 + kNN)
    # query against Elasticsearch instead of pure kNN. Falls back to kNN
    # silently if the backend cannot honour the request. Defaults to False
    # to keep existing callers bit-for-bit identical.
    hybrid: bool = False
    weight_accurate: float = 0.3


class MemorySearchResult(BaseModel):
    """Result model for memory search operations."""
    memory_id: Optional[int] = None
    external_id: Optional[str] = None
    content: str
    score: float
    layer: Optional[MemoryLayer] = None
    source: str = "internal"  # "internal" or external provider name
    is_external: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UnitIngestStatus(str, Enum):
    """Status of an individual unit within an ingest request."""
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEGRADED = "degraded"


class UnitIngestResult(BaseModel):
    """Result for a single unit in an ingest operation."""
    unit_id: str
    status: UnitIngestStatus
    message: Optional[str] = None


class MemoryIngestUnit(BaseModel):
    """Single unit of content for ingestion to external providers."""
    event_id: str
    event_type: str
    unit_type: str
    unit_content: str
    unit_index: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryIngestRequest(BaseModel):
    """Request model for ingesting context units to external providers."""
    tenant_id: str
    user_id: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    units: List[MemoryIngestUnit]
    idempotency_key: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryIngestResult(BaseModel):
    """Result model for memory ingest operations."""
    provider: str
    status: str  # "ok", "degraded", "error"
    accepted_count: int = 0
    rejected_count: int = 0
    unit_results: List[UnitIngestResult] = Field(default_factory=list)
    message: Optional[str] = None


class ProviderErrorCode(str, Enum):
    """Error codes for external provider operations."""
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UNSUPPORTED_UNIT_TYPE = "unsupported_unit_type"
    PARTIAL_ACCEPTANCE = "partial_acceptance"
    INVALID_PAYLOAD = "invalid_payload"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNKNOWN = "unknown"


class ProviderErrorSeverity(str, Enum):
    """Severity levels for provider errors."""
    RETRYABLE = "retryable"
    DEGRADABLE = "degradable"
    NON_RETRYABLE = "non_retryable"


class ProviderError(BaseModel):
    """Error from external memory provider."""
    code: ProviderErrorCode
    message: str
    severity: ProviderErrorSeverity
    retry_after_seconds: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class MemoryConfig(BaseModel):
    """Configuration model for memory operations.

    This model defines the configuration structure for memory services,
    including embedding model settings and Elasticsearch connection details.
    The index name follows the pattern: mem_{model_repo}_{model_name}_{dimension}
    """
    # Embedding model configuration
    embed_model_name: str
    embed_model_repo: Optional[str] = None
    embed_model_base_url: str
    embed_model_api_key: str
    embed_model_dimension: int

    # Elasticsearch configuration
    es_host: str
    es_port: int
    es_api_key: Optional[str] = None
    es_username: Optional[str] = None
    es_password: Optional[str] = None

    # LLM configuration (for inference)
    llm_model_name: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None

    def get_index_name(self) -> str:
        """Generate Elasticsearch index name based on embedding model configuration.

        The index name follows the pattern:
        - With repo: mem_{repo}_{name}_{dimension}
        - Without repo: mem_{name}_{dimension}

        This naming convention allows for model-specific indexes while
        preserving the ability to clear all memories for a given model.
        """
        safe_repo = self.embed_model_repo.replace("/", "_").replace("-", "_") if self.embed_model_repo else ""
        safe_name = self.embed_model_name.replace("/", "_").replace("-", "_")

        if safe_repo:
            return f"mem_{safe_repo}_{safe_name}_{self.embed_model_dimension}"
        return f"mem_{safe_name}_{self.embed_model_dimension}"



class MemorySearchContext(BaseModel):
    """Context object containing retrieved memories for agent injection."""
    tenant_long_term: List[MemorySearchResult] = Field(default_factory=list)
    user_long_term: List[MemorySearchResult] = Field(default_factory=list)
    agent_short_term: List[MemorySearchResult] = Field(default_factory=list)
    external: List[MemorySearchResult] = Field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Convert context to prompt-friendly text format."""
        sections = []

        if self.tenant_long_term:
            sections.append("#### Tenant Long-term Memory")
            for mem in self.tenant_long_term:
                sections.append(f"- {mem.content}")

        if self.user_long_term:
            sections.append("#### User Long-term Memory")
            for mem in self.user_long_term:
                sections.append(f"- {mem.content}")

        if self.agent_short_term:
            sections.append("#### Agent Short-term Memory")
            for mem in self.agent_short_term:
                sections.append(f"- {mem.content}")

        if self.external:
            sections.append("#### External Memory")
            for mem in self.external:
                sections.append(f"- {mem.content}")

        if not sections:
            return ""

        return "### Memory Context\n\n" + "\n\n".join(sections)


class StoreMemoryResult(BaseModel):
    """Result from storing a memory."""
    memory_id: str
    event: str = "ADD"  # ADD, UPDATE, NONE
    content: str
    layer: MemoryLayer
    memory_type: MemoryType
