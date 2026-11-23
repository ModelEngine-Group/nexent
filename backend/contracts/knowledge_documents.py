# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Synchronous append batches preserve document source IDs independently of storage keys."""

from contracts.agentos import ModelReference
from contracts.agentos_knowledge import Contract, ModelVersion, ObjectReference
from pydantic import Field, JsonValue, model_serializer, model_validator


class KnowledgeDocument(Contract):
    content: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    image_ref: ObjectReference | None = None

    @model_validator(mode="after")
    def image_space(self):
        if self.image_ref is not None and self.image_ref.space != "files":
            raise ValueError("Image documents require the files object space")
        return self


class KnowledgeDocumentsAppend(Contract):
    knowledge_id: int = Field(gt=0)
    resource_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: ModelVersion | ModelReference
    documents: list[KnowledgeDocument] = Field(min_length=1, max_length=64)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=64)
    native_documents: bool = False

    @model_serializer(mode="wrap")
    def serialize_append(self, handler):
        result = handler(self)
        if not self.native_documents:
            result.pop("native_documents", None)
        return result


class KnowledgeDocumentsAppended(Contract):
    knowledge_id: int = Field(gt=0)
    total_submitted: int = Field(ge=1, le=64)
    total_indexed: int = Field(ge=0, le=64)
    total_skipped: int = Field(default=0, ge=0, le=64)
    chunk_ids: list[str] = Field(max_length=64)

    @model_validator(mode="after")
    def confirmed_count(self):
        if (self.total_submitted != self.total_indexed + self.total_skipped or len(self.chunk_ids) != self.total_indexed
            or len(set(self.chunk_ids)) != len(self.chunk_ids) or any(not key for key in self.chunk_ids)):
            raise ValueError("Expected one confirmed physical key per appended document")
        return self
