# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS v1 cleansing artifacts and KnowledgeBase transport contracts."""

import hashlib
import json
from enum import Enum
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

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


class KnowledgeSourceReference(Contract):
    file_ref: KnowledgeFileReference
    image_ref: ObjectReference | None = None
    location: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_snapshot(self):
        if len(self.model_dump_json().encode("utf-8")) > 16384:
            raise ValueError("Knowledge source reference exceeds 16 KiB")
        return self


def validate_knowledge_source_reference(value):
    return None if value is None else KnowledgeSourceReference.model_validate(value).model_dump(mode="json", exclude_none=True)


class KnowledgeContentRequest(KnowledgeFileReference):
    image_ref: ObjectReference | None = None


class KnowledgeContentGrant(KnowledgeContentRequest):
    object_ref: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def exact_image(self):
        if self.object_ref.space != "files" or self.image_ref is not None and self.object_ref != self.image_ref:
            raise ValueError("Content grant must bind the selected file object")
        return self


class KnowledgeFileUpload(KnowledgeFileReference):
    artifact: ObjectReference
    parser_version: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None
    chunking_strategy: Literal["basic", "by_title", "none"] = "basic"


class KnowledgeFileDelete(KnowledgeFileReference):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def knowledge_job_id(request, tenant_id, user_id):
    """Compute the existing Runtime admission identity before an HTTP side effect."""
    if not isinstance(request, (KnowledgeFileUpload, KnowledgeFileDelete)):
        raise TypeError("Expected a knowledge upload or delete request")
    if any(not isinstance(value, str) or not value for value in (tenant_id, user_id)):
        raise ValueError("Expected trusted tenant and actor identities")
    return uuid5(NAMESPACE_URL, json.dumps([
        "runtime-kb-job", tenant_id, user_id, request.knowledge_id, request.file_id,
        request.file_version, "upload" if isinstance(request, KnowledgeFileUpload) else "delete",
        request.idempotency_key,
    ], separators=(",", ":"))).hex


class KnowledgeAuthorizationRequest(KnowledgeFileReference):
    action: Literal["upload", "execute", "inspect", "delete"]
    artifact: ObjectReference | None = None
    parser_version: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def artifact_scope(self):
        execution = self.action in {"upload", "execute"}
        if execution and (self.artifact is None or self.parser_version is None):
            raise ValueError("Execution authorization requires a cleansing artifact")
        if not execution and (
            self.artifact is not None or self.parser_version is not None
        ):
            raise ValueError("Lookup authorization cannot carry execution artifacts")
        return self


class KnowledgeFileGrant(KnowledgeAuthorizationRequest):
    source: ObjectReference | None
    filename: str = Field(min_length=1, max_length=1024)
    collection: str = Field(min_length=1, max_length=100)
    embedding_model_id: int | None = Field(default=None, gt=0)


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
    processed_chunks: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    total_chunks: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)

    @model_validator(mode="after")
    def valid_progress(self):
        if self.processed_chunks is not None and self.total_chunks is not None and self.processed_chunks > self.total_chunks:
            raise ValueError("Confirmed progress cannot exceed the known total")
        return self


class KnowledgeSearchAuthorization(Contract):
    knowledge_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("knowledge_ids")
    @classmethod
    def valid_scope(cls, values):
        if any(v <= 0 for v in values) or len(values) != len(set(values)):
            raise ValueError("Expected distinct positive knowledge IDs")
        return values


class KnowledgeBaseGrant(Contract):
    knowledge_id: int = Field(gt=0)
    collection: str = Field(min_length=1, max_length=100)
    embedding_model_id: int = Field(gt=0)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeSearchGrant(Contract):
    knowledge_bases: list[KnowledgeBaseGrant] = Field(min_length=1, max_length=100)


class KnowledgeSearch(KnowledgeSearchAuthorization):
    query: str = Field(min_length=1)
    search_mode: Literal["accurate", "semantic", "hybrid"] = "semantic"
    top_k: int = Field(default=10, ge=1, le=100)
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None
    file_ids: list[str] = Field(default_factory=list, max_length=1000)
    file_versions: dict[str, int] = Field(default_factory=dict, max_length=1000)
    expected_revisions: dict[int, str] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def pinned_resources(self):
        if self.file_versions and (
            set(self.file_versions) != set(self.file_ids)
            or any(type(value) is not int or value < 0 for value in self.file_versions.values())
        ):
            raise ValueError("Expected a nonnegative version for every selected file")
        if self.expected_revisions and (
            set(self.expected_revisions) != set(self.knowledge_ids)
            or any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                   for value in self.expected_revisions.values())
        ):
            raise ValueError("Expected a SHA256 revision for every requested knowledge resource")
        return self

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
    filename: str = Field(default="", max_length=1024)
    score: float
    score_kind: str = Field(min_length=1, max_length=64)
    location: dict[str, JsonValue] = Field(default_factory=dict)
    score_details: dict[str, JsonValue] = Field(default_factory=dict)
    image_ref: ObjectReference | None = None


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


def cleanse_output_prefix(run: FileCleanseLookup | None = None) -> str:
    """Keep durable KB keys and give temporary run outputs an admitted identity."""
    if run is None:
        return ""
    if not isinstance(run, FileCleanseLookup):
        raise TypeError("Expected a run cleansing lookup")
    checked = FileCleanseLookup.model_validate(run.model_dump())
    return f"run-cleanse/{checked.run_id}/{checked.job_id}/"


class CleanseResult(Contract):
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    artifact: ObjectReference | None = None
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def completed_artifact(self):
        if (self.status == "completed") != (self.artifact is not None):
            raise ValueError("Only completed cleansing has a confirmed artifact")
        return self


class FileCleanseState(FileCleanseLookup, CleanseResult):
    status: Literal["queued", "running", "completed", "failed", "cancelled", "released"]


class FileCleanseReleased(FileCleanseLookup):
    released: Literal[True] = True


class KnowledgeOperation(str, Enum):
    UPLOAD = "/internal/agentos/v1/knowledge/files/upload"
    INSPECT = "/internal/agentos/v1/knowledge/files/inspect"
    DELETE = "/internal/agentos/v1/knowledge/files/delete"
    SEARCH = "/internal/agentos/v1/knowledge/search"
