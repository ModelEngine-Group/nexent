# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS v1 cleansing artifacts and KnowledgeBase transport contracts."""

import hashlib
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ObjectReference(Contract):
    space: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    key: str = Field(min_length=1, max_length=1024)
    version: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("key")
    @classmethod
    def logical_key(cls, key):
        if (
            key.startswith("/")
            or "\\" in key
            or ":" in key
            or any(p in {"", ".", ".."} for p in key.split("/"))
        ):
            raise ValueError("Expected a logical object key")
        return key


class CleanseBlock(Contract):
    ordinal: int = Field(ge=0)
    kind: Literal["text", "table", "image"]
    content: str = ""
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    object_ref: ObjectReference | None = None
    location: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def checksum(self):
        if self.kind == "image":
            if (
                self.object_ref is None
                or self.sha256 != self.object_ref.sha256
                or self.content
            ):
                raise ValueError("Images require a checksummed object reference")
        elif (
            self.object_ref is not None
            or hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.sha256
        ):
            raise ValueError("Text checksum does not match UTF-8 content")
        return self


class CleanseArtifact(Contract):
    schema_version: Literal[1] = 1
    source: ObjectReference
    parser_version: str = Field(min_length=1, max_length=128)
    blocks: list[CleanseBlock]

    @model_validator(mode="after")
    def ordered_blocks(self):
        if [b.ordinal for b in self.blocks] != list(range(len(self.blocks))):
            raise ValueError("Blocks must have contiguous zero-based ordinals")
        return self


class ModelVersion(Contract):
    model_id: int = Field(gt=0)
    revision: str = Field(min_length=1, max_length=128)


class KnowledgeFileReference(Contract):
    knowledge_id: int = Field(gt=0)
    file_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    file_version: int = Field(ge=0)


class KnowledgeFileUpload(KnowledgeFileReference):
    artifact: ObjectReference
    parser_version: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None
    chunking_strategy: Literal["basic", "by_title", "none"] = "basic"


class KnowledgeFileDelete(KnowledgeFileReference):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class KnowledgeJobLookup(KnowledgeFileReference):
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class KnowledgeJobState(KnowledgeJobLookup):
    status: Literal[
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "deleted",
        "cleanup_pending",
    ]
    error_code: str | None = Field(default=None, max_length=128)
    physical_cleanup_complete: bool = False


class KnowledgeSearch(Contract):
    knowledge_ids: list[int] = Field(min_length=1)
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None
    file_ids: list[str] = Field(default_factory=list)

    @field_validator("knowledge_ids")
    @classmethod
    def valid_scope(cls, values):
        if any(v <= 0 for v in values) or len(values) != len(set(values)):
            raise ValueError("Expected distinct positive knowledge IDs")
        return values

    @field_validator("file_ids")
    @classmethod
    def valid_files(cls, values):
        if len(values) != len(set(values)) or any(
            len(value) != 32 or any(c not in "0123456789abcdef" for c in value)
            for value in values
        ):
            raise ValueError("Expected distinct file IDs")
        return values


class KnowledgeSearchHit(KnowledgeFileReference):
    chunk_id: str = Field(min_length=1, max_length=1024)
    content: str
    score: float
    score_kind: str = Field(min_length=1, max_length=64)
    location: dict[str, JsonValue] = Field(default_factory=dict)


class KnowledgeSearchResult(Contract):
    hits: list[KnowledgeSearchHit]
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None


class FileCleanseRequest(Contract):
    run_id: str = Field(pattern=r"^(debug-)?[0-9a-f]{32}$")
    source: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class FileCleanseLookup(Contract):
    run_id: str = Field(pattern=r"^(debug-)?[0-9a-f]{32}$")
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class FileCleanseState(FileCleanseLookup):
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    artifact: ObjectReference | None = None
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def completed_artifact(self):
        if (self.status == "completed") != (self.artifact is not None):
            raise ValueError("Only completed cleansing has a confirmed artifact")
        return self


class KnowledgeOperation(str, Enum):
    UPLOAD = "/internal/agentos/v1/knowledge/files/upload"
    INSPECT = "/internal/agentos/v1/knowledge/files/inspect"
    DELETE = "/internal/agentos/v1/knowledge/files/delete"
    SEARCH = "/internal/agentos/v1/knowledge/search"
