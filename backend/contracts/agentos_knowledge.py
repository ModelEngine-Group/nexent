# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AgentOS v1 cleansing artifacts and KnowledgeBase transport contracts."""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_serializer,
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
    native_documents: bool = False

    @model_serializer(mode="wrap")
    def serialize_upload(self, handler):
        result = handler(self)
        if not self.native_documents:
            result.pop("native_documents", None)
        return result


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


class KnowledgeFileSourceDisplay(Contract):
    size_bytes: int | None = Field(ge=0, le=2**63-1)
    created_at: str | None = Field(max_length=64)

    @field_validator('created_at')
    @classmethod
    def aware_time(cls, value):
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('Expected an aware source timestamp')
        return value


class KnowledgeFileGrant(KnowledgeAuthorizationRequest):
    source: ObjectReference | None
    source_display: KnowledgeFileSourceDisplay | None
    filename: str = Field(min_length=1, max_length=1024)
    collection: str = Field(min_length=1, max_length=100)
    embedding_model_id: int | None = Field(default=None, gt=0)
    legacy_sources: list[str] = Field(default_factory=list, max_length=8)
    legacy_file_alias: str | None = Field(default=None, min_length=1, max_length=64)

    @model_serializer(mode="wrap")
    def serialize_file_grant(self, handler):
        result = handler(self)
        if not self.legacy_sources:
            result.pop("legacy_sources", None)
        if self.legacy_file_alias is None:
            result.pop("legacy_file_alias", None)
        return result

    @model_validator(mode='after')
    def source_scope(self):
        execution = self.action in {'upload','execute'}
        if self.legacy_sources and (self.action != "delete" or len(set(self.legacy_sources)) != len(self.legacy_sources)
            or any(not 0 < len(value) <= 2048 for value in self.legacy_sources)):
            raise ValueError("Legacy sources require exact, distinct deletion addresses")
        if self.legacy_file_alias is not None and (not self.legacy_sources or self.legacy_file_alias == self.file_id
                or not self.legacy_file_alias.isprintable() or not self.legacy_file_alias.strip()):
            raise ValueError("A historical file alias requires a confirmed deletion source")
        if execution and (self.source is None or self.source_display is None):
            raise ValueError('Execution requires source identity and display')
        if not execution and (self.source is not None or self.source_display is not None):
            raise ValueError('Lookup grants cannot carry source display')
        return self


class KnowledgeJobLookup(KnowledgeFileReference):
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class KnowledgeJobInspection(KnowledgeJobLookup):
    confirm_publication: bool = False


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
    writer_ended: bool | None = Field(default=None, strict=True)
    reconcile_required: bool | None = Field(default=None, strict=True)
    processed_chunks: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    total_chunks: int | None = Field(default=None, ge=0, le=2**31 - 1, strict=True)
    publication_confirmed: bool | None = None

    @model_serializer(mode="wrap")
    def serialize_job_state(self, handler):
        result = handler(self)
        if self.publication_confirmed is None:
            result.pop("publication_confirmed", None)
        return result

    @model_validator(mode="after")
    def valid_progress(self):
        if self.processed_chunks is not None and self.total_chunks is not None and self.processed_chunks > self.total_chunks:
            raise ValueError("Confirmed progress cannot exceed the known total")
        return self


class KnowledgeSearchAuthorization(Contract):
    knowledge_ids: list[int] = Field(min_length=1, max_length=100)
    selected_files: list[KnowledgeFileReference] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def selected_file_scope(self):
        if (len({ref.file_id for ref in self.selected_files}) != len(self.selected_files)
            or any(ref.knowledge_id not in self.knowledge_ids for ref in self.selected_files)):
            raise ValueError("Expected distinct selected files in the authorized knowledge bases")
        return self

    @model_serializer(mode="wrap")
    def serialize_selected_files(self, handler):
        result = handler(self)
        if not self.selected_files:
            result.pop("selected_files", None)
        return result

    @field_validator("knowledge_ids")
    @classmethod
    def valid_scope(cls, values):
        if any(v <= 0 for v in values) or len(values) != len(set(values)):
            raise ValueError("Expected distinct positive knowledge IDs")
        return values


class KnowledgeBaseGrant(Contract):
    knowledge_id: int = Field(gt=0)
    collection: str = Field(min_length=1, max_length=100)
    resource_tenant_id: str = Field(min_length=1, max_length=100)
    embedding_model_id: int = Field(gt=0)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeLegacySearchFile(KnowledgeFileReference):
    addresses: list[str] = Field(min_length=1, max_length=8)
    alias: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def valid_addresses(self):
        if (len(set(self.addresses)) != len(self.addresses) or any(not 0 < len(path) <= 2048 for path in self.addresses)
            or self.alias is not None and (not self.alias.isprintable() or not self.alias.strip() or self.alias == self.file_id)):
            raise ValueError("Invalid historical file scope")
        return self


class KnowledgeSearchGrant(Contract):
    knowledge_bases: list[KnowledgeBaseGrant] = Field(min_length=1, max_length=100)
    legacy_files: list[KnowledgeLegacySearchFile] = Field(default_factory=list, max_length=1000)

    @model_serializer(mode="wrap")
    def serialize_legacy_files(self, handler):
        result = handler(self)
        if not self.legacy_files:
            result.pop("legacy_files", None)
        return result


class KnowledgeSearch(KnowledgeSearchAuthorization):
    query: str = Field(min_length=1)
    search_mode: Literal["accurate", "semantic", "hybrid"] = "semantic"
    weight_accurate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    global_hybrid_candidates: bool = False
    split_multimodal_candidates: bool = False
    merge_display_ids: bool = False
    include_public_document: bool = False
    native_documents: bool = False
    first_collection_embedding: bool = False
    top_k: int = Field(default=10, ge=1, le=100)
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None
    file_ids: list[str] = Field(default_factory=list, max_length=1000)
    file_versions: dict[str, int] = Field(default_factory=dict, max_length=1000)
    expected_revisions: dict[int, str] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def pinned_resources(self):
        if self.selected_files and (not self.native_documents
            or {ref.file_id: ref.file_version for ref in self.selected_files} != self.file_versions):
            raise ValueError("Historical file search requires exact selected file versions")
        if self.native_documents and (
            not self.expected_revisions or self.rerank_model is not None or self.file_ids and not self.file_versions
        ):
            raise ValueError("Native search requires pinned resources and versions for selected files")
        if self.global_hybrid_candidates and (self.search_mode != "hybrid" or self.rerank_model is not None):
            raise ValueError("Global candidates require hybrid search without reranking")
        if self.split_multimodal_candidates and not self.global_hybrid_candidates:
            raise ValueError("Separate media candidates require global hybrid search")
        if self.merge_display_ids and not self.global_hybrid_candidates:
            raise ValueError("Display ID fusion requires global hybrid search")
        if self.first_collection_embedding and not (
            self.global_hybrid_candidates and self.include_public_document and self.expected_revisions
        ):
            raise ValueError("First-collection embedding requires pinned public hybrid search")
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

    @model_serializer(mode="wrap")
    def serialize_search(self, handler):
        result = handler(self)
        if not self.selected_files:
            result.pop("selected_files", None)
        if not self.global_hybrid_candidates:
            result.pop("global_hybrid_candidates", None)
        if not self.split_multimodal_candidates:
            result.pop("split_multimodal_candidates", None)
        if not self.merge_display_ids:
            result.pop("merge_display_ids", None)
        if not self.include_public_document:
            result.pop("include_public_document", None)
        if not self.native_documents:
            result.pop("native_documents", None)
        if not self.first_collection_embedding:
            result.pop("first_collection_embedding", None)
        return result

    @field_validator("file_ids")
    @classmethod
    def valid_files(cls, values):
        if len(values) != len(set(values)) or any(
            len(value) != 32 or any(c not in "0123456789abcdef" for c in value)
            for value in values
        ):
            raise ValueError("Expected distinct file IDs")
        return values


class KnowledgeSearchHit(Contract):
    knowledge_id: int = Field(gt=0)
    file_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    file_version: int | None = Field(default=None, ge=0)
    chunk_id: str = Field(min_length=1, max_length=1024)
    content: JsonValue
    filename: JsonValue = ""
    score: float
    score_kind: str = Field(min_length=1, max_length=64)
    location: dict[str, JsonValue] = Field(default_factory=dict)
    score_details: dict[str, JsonValue] = Field(default_factory=dict)
    image_ref: ObjectReference | None = None
    public_document: dict[str, JsonValue] | None = None

    @model_serializer(mode="wrap")
    def serialize_hit(self, handler):
        result = handler(self)
        if self.public_document is None:
            result.pop("public_document", None)
        return result

    @model_validator(mode="after")
    def complete_file_reference(self):
        if (self.file_id is None) != (self.file_version is None):
            raise ValueError("File identity and version must be present or absent together")
        return self


class KnowledgeSearchResult(Contract):
    hits: list[KnowledgeSearchHit]
    image_hits: list[KnowledgeSearchHit] | None = None
    data_revisions: dict[int, str] = Field(min_length=1, max_length=100)
    embedding_model: ModelVersion
    rerank_model: ModelVersion | None = None

    @model_serializer(mode="wrap")
    def serialize_result(self, handler):
        result = handler(self)
        if self.image_hits is None:
            result.pop("image_hits", None)
        return result

    @field_validator("data_revisions", mode="before")
    @classmethod
    def decode_revision_keys(cls, values):
        if not isinstance(values, dict):
            return values
        decoded = {}
        for key, value in values.items():
            if isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key:
                key = int(key)
            if key in decoded:
                raise ValueError("Duplicate knowledge data revision")
            decoded[key] = value
        return decoded

    @field_validator("data_revisions")
    @classmethod
    def valid_data_revisions(cls, values):
        if any(key <= 0 or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
               for key, value in values.items()):
            raise ValueError("Expected a SHA256 data revision for each queried knowledge resource")
        return values


class KnowledgeSample(Contract):
    knowledge_id: int = Field(gt=0)
    document_limit: int = Field(default=200, ge=1, le=200)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeBaseInspect(Contract):
    knowledge_id: int = Field(gt=0)
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    page_size: int = Field(default=100, ge=1, le=1000)
    cursor: str | None = Field(default=None, min_length=1, max_length=1024)


class KnowledgeManifest(Contract):
    file_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    latest_version: int = Field(ge=-1)
    visible_version: int | None = Field(default=None, ge=0)
    visible_generation: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    tombstone_version: int = Field(ge=-1)
    record_revision: int = Field(gt=0)
    upload_job_reference_present: bool

    @model_validator(mode='after')
    def visible_generation_matches(self):
        if (self.visible_version is None) != (self.visible_generation is None):
            raise ValueError('Visible version and generation must be present together')
        if self.visible_version is not None and not self.tombstone_version < self.visible_version <= self.latest_version:
            raise ValueError('Visible version must exceed the tombstone and be admitted')
        return self


class KnowledgeBaseState(Contract):
    knowledge_id: int = Field(gt=0)
    knowledge_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    manifest_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    embedding_model_id: int = Field(gt=0)
    files: list[KnowledgeManifest] = Field(max_length=1000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=1024)


class KnowledgeSampleChunk(Contract):
    chunk_id: str = Field(min_length=1, max_length=1024)
    chunk_index: int | None = Field(default=None, ge=0)
    content: JsonValue
    embedding: list[float] | None = Field(default=None, min_length=1)
    location: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator('embedding')
    @classmethod
    def finite_embedding(cls, values):
        import math

        if values is not None and any(not math.isfinite(value) for value in values):
            raise ValueError('Expected finite stored embeddings')
        return values


class KnowledgeSampleDocument(Contract):
    file_ref: KnowledgeFileReference | None = None
    standalone_key: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    path_or_url: str | None = None
    filename: JsonValue
    chunks: list[KnowledgeSampleChunk]

    @model_validator(mode="after")
    def one_source(self):
        if (self.file_ref is None) == (self.standalone_key is None):
            raise ValueError("A sample document needs exactly one file or independent source")
        return self


class KnowledgeSampleResult(Contract):
    knowledge_id: int = Field(gt=0)
    knowledge_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model: ModelVersion
    documents: list[KnowledgeSampleDocument] = Field(max_length=200)


class KnowledgeChunksAuthorization(Contract):
    knowledge_id: int = Field(gt=0)


class KnowledgeChunksGrant(KnowledgeChunksAuthorization):
    collection: str = Field(min_length=1, max_length=100)
    resource_tenant_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')


class KnowledgeChunks(KnowledgeChunksAuthorization):
    knowledge_id: int = Field(gt=0)
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    expected_data_revision: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    file_ids: list[str] | None = Field(default=None, max_length=1000)
    standalone_path: str | None = None
    offset: int = Field(default=0, ge=0, le=2**31-1)
    limit: int = Field(default=100, ge=1, le=1000)
    native_documents: bool = False

    @model_validator(mode="after")
    def native_scope(self):
        if self.native_documents and self.file_ids is not None:
            raise ValueError("Native chunks can only be scoped by their source path")
        return self

    @model_serializer(mode="wrap")
    def serialize_chunks(self, handler):
        result = handler(self)
        if not self.native_documents:
            result.pop("native_documents", None)
        return result

    @field_validator('file_ids')
    @classmethod
    def exact_file_scope(cls, values):
        if values is not None and (len(values) != len(set(values)) or any(
            len(value) != 32 or any(c not in '0123456789abcdef' for c in value) for value in values
        )):
            raise ValueError('Expected distinct file IDs')
        return values


class KnowledgeChunk(Contract):
    knowledge_id: int = Field(gt=0)
    file_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    file_version: int | None = Field(default=None, ge=0)
    chunk_id: str = Field(min_length=1, max_length=1024)
    chunk_index: int | None = Field(default=None, ge=0)
    filename: JsonValue = None
    content: JsonValue
    location: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete_file_reference(self):
        missing = sum(value is None for value in (self.file_id, self.file_version, self.chunk_index))
        if missing not in {0, 3}:
            raise ValueError("File identity and position must all be present or absent")
        return self


class KnowledgeChunksResult(Contract):
    knowledge_id: int = Field(gt=0)
    knowledge_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    data_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    total: int = Field(ge=0)
    chunks: list[KnowledgeChunk] = Field(max_length=1000)
    next_offset: int | None = Field(default=None, ge=0)


class FileCleanseRequest(Contract):
    run_id: str = Field(pattern=r"^(debug-)?[0-9a-f]{32}$")
    source: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class FileCleanseLookup(Contract):
    run_id: str = Field(pattern=r"^(debug-)?[0-9a-f]{32}$")
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class KnowledgeCleanseLookup(KnowledgeFileReference):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")


def cleanse_output_prefix(run: FileCleanseLookup | KnowledgeCleanseLookup | None = None) -> str:
    """Scope outputs to the exact admitted run or durable knowledge job."""
    if run is None:
        return ""
    if isinstance(run, KnowledgeCleanseLookup):
        checked = KnowledgeCleanseLookup.model_validate(run.model_dump())
        return f'knowledge-cleanse/{checked.knowledge_id}/{checked.file_id}/{checked.file_version}/{checked.job_id}/'
    if not isinstance(run, FileCleanseLookup):
        raise TypeError("Expected an admitted cleansing lookup")
    checked = FileCleanseLookup.model_validate(run.model_dump())
    return f"run-cleanse/{checked.run_id}/{checked.job_id}/"


class CleanseResult(Contract):
    status: Literal["queued", "running", "completed", "failed", "cancelled", "released"]
    artifact: ObjectReference | None = None
    error_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def completed_artifact(self):
        if (self.status == "completed") != (self.artifact is not None):
            raise ValueError("Only completed cleansing has a confirmed artifact")
        return self


class FileCleanseState(FileCleanseLookup, CleanseResult):
    pass


class FileCleanseReleased(FileCleanseLookup):
    released: Literal[True] = True


class KnowledgeOperation(str, Enum):
    SOURCES = '/internal/agentos/v1/knowledge/bases/sources/list'
    DESCRIBE_COLLECTIONS = '/internal/agentos/v1/knowledge/bases/collections/describe'
    COLLECTION_USAGE = '/internal/agentos/v1/knowledge/bases/collections/usage'
    ENSURE_COLLECTION = '/internal/agentos/v1/knowledge/bases/collection/ensure'
    INSPECT_COLLECTION = '/internal/agentos/v1/knowledge/bases/collection/state'
    DELETE_UNTRACKED_SOURCE = '/internal/agentos/v1/knowledge/documents/delete-untracked-source'
    APPEND_DOCUMENTS = '/internal/agentos/v1/knowledge/documents/append'
    INSPECT_CHUNK = '/internal/agentos/v1/knowledge/chunks/inspect'
    MUTATE_CHUNK = '/internal/agentos/v1/knowledge/chunks/mutate'
    INSPECT_BASE = '/internal/agentos/v1/knowledge/bases/state'
    DELETE_BASE = '/internal/agentos/v1/knowledge/bases/delete'
    INSPECT_BASE_DELETION = '/internal/agentos/v1/knowledge/bases/inspect'
    UPLOAD = "/internal/agentos/v1/knowledge/files/upload"
    INSPECT = "/internal/agentos/v1/knowledge/files/inspect"
    DELETE = "/internal/agentos/v1/knowledge/files/delete"
    SEARCH = "/internal/agentos/v1/knowledge/search"
    SAMPLE = "/internal/agentos/v1/knowledge/sample"
    CHUNKS = "/internal/agentos/v1/knowledge/chunks"
