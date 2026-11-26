# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Request models for the AIDP management mock server."""

from typing import Any, Dict, List, Literal, Optional
import uuid

from pydantic import BaseModel, Field, model_validator


_RETRIEVAL_CHANNELS = ("vector_search", "full_text_search", "graph_search")


# Request Models
# =============================================================================
class CreateKbBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    embedding_model: Optional[str] = None
    is_multimodal: Optional[bool] = None
    vision_model: Optional[str] = None
    chunk_token_num: int = 512
    chunk_overlap_num: int = 51
    chunk_mode: int = 0
    is_personal: int = 0
    topk: int = 10
    similarity: float = 0.0
    caption_enable: int = 0
    vlm_model: str = ""
    is_exist_graph: bool = False
    graph_config: Optional[str] = None
    summary_enable: bool = False
    summary_model: Optional[str] = None
    summary_preview: Optional[bool] = None
    sensitive_intercept_enable: int = 0


class UpdateKbBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    summary_enable: Optional[bool] = None
    summary_model: Optional[str] = None
    summary_preview: Optional[bool] = None
    chunk_mode: Optional[int] = None
    chunk_token_num: Optional[int] = None
    chunk_overlap_num: Optional[int] = None
    topk: Optional[int] = None
    caption_enable: Optional[int] = None
    vlm_model: Optional[str] = None
    is_exist_graph: Optional[bool] = None
    graph_config: Optional[str] = None
    sensitive_intercept_enable: Optional[int] = None


class DocHistoryBody(BaseModel):
    """Body of POST .../KnowledgeFiles/History (channel + directory scoped)."""

    fs_id: Optional[str] = None
    dir_path: Optional[str] = None
    page: int = 1
    page_size: Optional[int] = Field(default=None, ge=1, le=100)
    status: Optional[int] = Field(default=None, ge=0, le=5)
    keyword: Optional[str] = Field(default=None, max_length=200)


class RetryDocumentsBody(BaseModel):
    retry_file_info: List[Dict[str, str]] = Field(..., min_length=1)


class DocStatusBody(BaseModel):
    """Body of POST /_mock/doc-status (test control over one document)."""

    kds_id: str
    file_ino_no: str
    status: Literal[
        "UPLOADING", "PROCESSING", "EXTRACTING", "COMPLETED", "FAILED"
    ] = "FAILED"


class MetadataCondition(BaseModel):
    logical_operator: Literal["and", "or"] = "and"
    conditions: List[Dict[str, Any]] = Field(default_factory=list)


class HybridSearchConfig(BaseModel):
    """Per-channel knobs for the vector/full-text part of a FusionSearch call."""

    vector_candidates: int = Field(default=10, ge=1, le=500)
    full_text_candidates: int = Field(default=10, ge=1, le=500)
    # Present values mirror the real AIDP contract (1-100); omission means
    # "no separate cap", which the mock evaluates as falling back to topk.
    hybrid_top_k: Optional[int] = Field(None, ge=1, le=100)
    vector_score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    full_text_score_threshold: float = Field(0.0, ge=0.0, le=1.0)


class GraphSearchConfig(BaseModel):
    """Per-channel knobs for the graph part of a FusionSearch call."""

    graph_top_k: Optional[int] = Field(None, ge=1, le=100)
    graph_score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    graph_reranking_enable: bool = True


class FusionSearchRequest(BaseModel):
    """FusionSearch request mirroring the current AIDP wire contract.

    ``topk``/``multi_modal_enable`` are the outbound names; the retired
    ``top_k``/``multi_modal`` aliases are accepted only so historical clients
    keep working in tests, and are never mixed with the new names in a single
    payload.
    """

    query: str = Field(min_length=1)
    kds_list: List[str] = Field(min_length=1, max_length=10)
    search_method: str = "vector_search|full_text_search|graph_search"
    reranking_enable: bool = False
    reranking_mode: Optional[Literal["performance", "high_accuracy", "jargon_coverage"]] = None
    rewrite_enable: bool = False
    query_expansion_enable: bool = False
    related_search_enable: bool = False
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    topk: int = Field(10, ge=1, le=100)
    multi_modal_enable: bool = False
    hybrid_search_config: Optional[HybridSearchConfig] = None
    graph_search_config: Optional[GraphSearchConfig] = None
    metadata_condition: Optional[MetadataCondition] = None
    ontology_enhance_enable: bool = False
    rule_enable: bool = False

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_aliases(cls, data: Any) -> Any:
        """Translate the pre-upgrade names once, rejecting mixed payloads."""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        for legacy, current in (("top_k", "topk"), ("multi_modal", "multi_modal_enable")):
            if legacy in payload:
                if current in payload and payload[current] != payload[legacy]:
                    raise ValueError(f"{current} and legacy {legacy} disagree")
                payload.setdefault(current, payload.pop(legacy))
        return payload

    @model_validator(mode="after")
    def _validate_method_and_quota(self) -> "FusionSearchRequest":
        """Validate the method set and the cross-channel quota relations."""
        channels = set(_RETRIEVAL_CHANNELS if self.search_method == "hybrid_search"
                       else self.search_method.split("|"))
        unknown = channels - set(_RETRIEVAL_CHANNELS)
        if not channels or unknown:
            raise ValueError(f"search_method must combine {sorted(_RETRIEVAL_CHANNELS)}")
        hybrid = bool(channels & {"vector_search", "full_text_search"})
        graph = "graph_search" in channels
        if hybrid and self.hybrid_search_config is None:
            raise ValueError("hybrid_search_config is required for vector/full-text retrieval")
        if graph and self.graph_search_config is None:
            raise ValueError("graph_search_config is required for graph retrieval")
        if not hybrid and self.hybrid_search_config is not None:
            raise ValueError("hybrid_search_config must not be sent for pure graph retrieval")
        if not graph and self.graph_search_config is not None:
            raise ValueError("graph_search_config must not be sent without graph retrieval")
        # Compute effective caps the way AIDP fills omitted values.
        h = self.hybrid_search_config.hybrid_top_k if self.hybrid_search_config else None
        g = self.graph_search_config.graph_top_k if self.graph_search_config else None
        effective_g = g if g is not None else min(5, self.topk)
        effective_h = h if h is not None else self.topk - effective_g
        if hybrid and h is not None and h > self.topk:
            raise ValueError("hybrid_top_k must not exceed topk")
        if graph and g is not None and g > self.topk:
            raise ValueError("graph_top_k must not exceed topk")
        if hybrid and graph and effective_h + effective_g > self.topk:
            raise ValueError("hybrid_top_k + graph_top_k must not exceed topk")
        if hybrid and h is not None:
            if "vector_search" in channels and self.hybrid_search_config.vector_candidates < h:
                raise ValueError("vector_candidates must be at least hybrid_top_k")
            if "full_text_search" in channels and self.hybrid_search_config.full_text_candidates < h:
                raise ValueError("full_text_candidates must be at least hybrid_top_k")
        return self


class RemoveFilesBody(BaseModel):
    file_uuids: List[str] = Field(..., min_length=1)


class CountFilesBody(BaseModel):
    """Body of POST .../KnowledgeFiles/Count (all fields optional)."""

    fs_id: Optional[str] = None
    dir_path: Optional[str] = None
    keyword: Optional[str] = Field(default=None, max_length=200)


class DownloadFileBody(BaseModel):
    file_uuid: uuid.UUID = Field(...)


class CreateChunkBody(BaseModel):
    """Body of PUT .../Chunks (add one chunk to a file)."""

    file_uuid: uuid.UUID = Field(...)
    chunk_text: str = Field(..., min_length=1, max_length=10240)


class UpdateChunkBody(BaseModel):
    """Body of PATCH .../Chunks/{chunk_id} (text is the only writable field)."""

    chunk_text: str = Field(..., min_length=1, max_length=10240)


class SummaryStatusBody(BaseModel):
    """Body of POST /_mock/summary-status."""

    kds_id: str
    file_uuid: uuid.UUID
    status: Literal["pending", "success", "failed"]
    summary_text: Optional[str] = None


class FileSummaryBody(BaseModel):
    """Body of POST .../KnowledgeFiles/Summary (2026-11-25 contract)."""

    file_uuid: uuid.UUID


class RemoveChunksBody(BaseModel):
    """Body of DELETE .../Chunks."""

    chunk_ids: List[int] = Field(..., min_length=1, max_length=2000)

class CreateSensitiveWordBody(BaseModel):
    word: str = Field(..., min_length=1, max_length=64)
    mode: Literal["BLACK", "WHITE"]
    description: str = Field(..., min_length=1, max_length=512)

    @model_validator(mode="after")
    def strip_fields(self):
        self.word = self.word.strip()
        self.description = self.description.strip()
        if not self.word or not self.description:
            raise ValueError("word and description must not be blank")
        return self


class UpdateSensitiveWordBody(BaseModel):
    word: Optional[str] = Field(default=None, max_length=64)
    mode: Optional[Literal["BLACK", "WHITE"]] = None
    description: Optional[str] = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def require_a_change(self):
        if self.word is None and self.mode is None and self.description is None:
            raise ValueError("At least one field must be provided")
        if self.word is not None:
            self.word = self.word.strip()
            if not self.word:
                raise ValueError("word must not be blank")
        if self.description is not None:
            self.description = self.description.strip()
            if not self.description:
                raise ValueError("description must not be blank")
        return self



