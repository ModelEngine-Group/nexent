"""Data models for the Nexent Memory system."""
from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
class MemoryLayer(str, Enum):
    TENANT = "tenant"; USER = "user"; AGENT = "agent"
class MemoryType(str, Enum):
    SHORT_TERM = "short_term"; LONG_TERM = "long_term"
class MemoryStatus(str, Enum):
    ACTIVE = "active"; ARCHIVED = "archived"
class MemoryRecord(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str; user_id: str
    agent_id: Optional[str] = None; conversation_id: Optional[str] = None
    layer: MemoryLayer; memory_type: MemoryType
    content: str; concept_tags: List[str] = Field(default_factory=list)
    recall_count: int = 0; daily_count: int = 0; grounded_count: int = 0
    last_recalled_at: Optional[datetime] = None
    query_hashes: List[str] = Field(default_factory=list)
    recall_days: List[str] = Field(default_factory=list)
    light_hits: int = 0; rem_hits: int = 0
    last_light_at: Optional[datetime] = None; last_rem_at: Optional[datetime] = None
    idempotency_key: str; status: MemoryStatus = MemoryStatus.ACTIVE; deleted_flag: str = "N"
    create_time: datetime = Field(default_factory=datetime.utcnow)
    update_time: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None; updated_by: Optional[str] = None
    class Config: use_enum_values = True
class ExternalMemoryItem(BaseModel):
    id: str; content: str; score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)
    provider: str; created_at: Optional[datetime] = None
    class Config: json_encoders = {datetime: lambda v: v.isoformat() if v else None}
class MemorySearchRequest(BaseModel):
    query: str; tenant_id: str; user_id: str
    agent_id: Optional[str] = None; conversation_id: Optional[str] = None
    layers: List[MemoryLayer] = Field(default_factory=list)
    top_k: int = 5; limit: int = 5; threshold: Optional[float] = 0.65
    embedding: Optional[List[float]] = None; hybrid: bool = False; weight_accurate: float = 0.3
class MemorySearchResult(BaseModel):
    memory_id: Optional[int] = None; external_id: Optional[str] = None
    content: str; score: float; layer: Optional[MemoryLayer] = None
    source: str = "internal"; is_external: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
class UnitIngestStatus(str, Enum):
    ACCEPTED = "accepted"; REJECTED = "rejected"; DEGRADED = "degraded"
class UnitIngestResult(BaseModel):
    unit_id: str; status: UnitIngestStatus; message: Optional[str] = None
class MemoryIngestUnit(BaseModel):
    event_id: str; event_type: str; unit_type: str; unit_content: str
    unit_index: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
class MemoryIngestRequest(BaseModel):
    tenant_id: str; user_id: str; agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    units: List[MemoryIngestUnit]; idempotency_key: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
class MemoryIngestResult(BaseModel):
    provider: str; status: str; accepted_count: int = 0; rejected_count: int = 0
    unit_results: List[UnitIngestResult] = Field(default_factory=list)
    message: Optional[str] = None
class ProviderErrorCode(str, Enum):
    TIMEOUT = "timeout"; RATE_LIMITED = "rate_limited"; PROVIDER_ERROR = "provider_error"
    UNAUTHORIZED = "unauthorized"; FORBIDDEN = "forbidden"
    UNSUPPORTED_UNIT_TYPE = "unsupported_unit_type"; PARTIAL_ACCEPTANCE = "partial_acceptance"
    INVALID_PAYLOAD = "invalid_payload"; SCHEMA_MISMATCH = "schema_mismatch"; UNKNOWN = "unknown"
class ProviderErrorSeverity(str, Enum):
    RETRYABLE = "retryable"; DEGRADABLE = "degradable"; NON_RETRYABLE = "non_retryable"
class ProviderError(BaseModel):
    code: ProviderErrorCode; message: str; severity: ProviderErrorSeverity
    retry_after_seconds: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)
class MemoryConfig(BaseModel):
    embed_model_name: str; embed_model_repo: Optional[str] = None
    embed_model_base_url: str; embed_model_api_key: str; embed_model_dimension: int
    es_host: str; es_port: int; es_api_key: Optional[str] = None
    es_username: Optional[str] = None; es_password: Optional[str] = None
    llm_model_name: Optional[str] = None; llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    def get_index_name(self) -> str:
        safe_repo = self.embed_model_repo.replace("/", "_").replace("-", "_") if self.embed_model_repo else ""
        safe_name = self.embed_model_name.replace("/", "_").replace("-", "_")
        if safe_repo: return f"mem_{safe_repo}_{safe_name}_{self.embed_model_dimension}"
        return f"mem_{safe_name}_{self.embed_model_dimension}"
class MemorySearchContext(BaseModel):
    tenant_long_term: List[MemorySearchResult] = Field(default_factory=list)
    user_long_term: List[MemorySearchResult] = Field(default_factory=list)
    agent_short_term: List[MemorySearchResult] = Field(default_factory=list)
    external: List[MemorySearchResult] = Field(default_factory=list)
    def to_prompt_text(self) -> str:
        sections = []
        if self.tenant_long_term:
            sections.append("#### Tenant Long-term Memory")
            for mem in self.tenant_long_term: sections.append(f"- {mem.content}")
        if self.user_long_term:
            sections.append("#### User Long-term Memory")
            for mem in self.user_long_term: sections.append(f"- {mem.content}")
        if self.agent_short_term:
            sections.append("#### Agent Short-term Memory")
            for mem in self.agent_short_term: sections.append(f"- {mem.content}")
        if self.external:
            sections.append("#### External Memory")
            for mem in self.external: sections.append(f"- {mem.content}")
        if not sections: return ""
        sep = chr(10) + chr(10)
        header = "### Memory Context" + sep + sep
        return header + sep.join(sections)
class StoreMemoryResult(BaseModel):
    memory_id: str; event: str = "ADD"; content: str
    layer: MemoryLayer; memory_type: MemoryType

# Phase 4: Retrieval Pipeline models
class RetrievalSource(str, Enum):
    AGENT_SHORT_TERM = "agent_short_term"; EXTERNAL = "external"
class PipelineMemoryRecord(BaseModel):
    record_id: str; content: str; score: float
    source: RetrievalSource; is_external: bool
    tenant_id: str
    user_id: Optional[str] = None; agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    layer: MemoryLayer
    memory_type: Optional[MemoryType] = None
    source_weight: float = 1.0
    fused_score: Optional[float] = None
    token_count: int = 0
    age_days: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
class PipelineConfig(BaseModel):
    mmr_lambda: float = 0.7; mmr_candidate_top_k: int = 10
    mmr_final_top_k: int = 5; mmr_duplicate_threshold: float = 0.92
    half_life_days: int = 14
    w_agent_short_term: float = 1.0; w_external: float = 0.8
    token_budget: int = 2000
    class Config: use_enum_values = True
