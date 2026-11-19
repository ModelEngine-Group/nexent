# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Synchronous append batches preserve document source IDs independently of storage keys."""

from contracts.agentos import ModelReference
from contracts.agentos_knowledge import Contract, ModelVersion
from pydantic import Field, JsonValue, model_validator


class KnowledgeDocument(Contract):
    content: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def text_document(self):
        if self.metadata.get("process_source") == "UniversalImageExtractor":
            raise ValueError("Image documents require a pinned image resource")
        return self


class KnowledgeDocumentsAppend(Contract):
    knowledge_id: int = Field(gt=0)
    resource_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: ModelVersion | ModelReference
    documents: list[KnowledgeDocument] = Field(min_length=1, max_length=64)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=64)


class KnowledgeDocumentsAppended(Contract):
    knowledge_id: int = Field(gt=0)
    total_submitted: int = Field(ge=1, le=64)
    total_indexed: int = Field(ge=1, le=64)
    chunk_ids: list[str] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def confirmed_count(self):
        if (self.total_submitted != self.total_indexed or len(self.chunk_ids) != self.total_indexed
            or len(set(self.chunk_ids)) != len(self.chunk_ids) or any(not key for key in self.chunk_ids)):
            raise ValueError("Expected one confirmed physical key per appended document")
        return self
