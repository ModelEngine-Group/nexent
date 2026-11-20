# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned immutable ingestion intent; no credentials or provider setup."""

from datetime import datetime
from typing import Annotated, Literal

from contracts.agentos_knowledge import (
    Contract,
    KnowledgeFileReference,
    KnowledgeFileUpload,
    ModelVersion,
    ObjectReference,
)
from contracts.knowledge_cleanse import KnowledgeCleanseRequest
from pydantic import Field, model_serializer, model_validator

INGESTION_DATASET = "knowledge_ingestion_files"
LOCAL_SOURCE_DATASET = "management_local_sources"
FILE_READ_DATASET = "management_file_lifecycle"
FILE_KNOWLEDGE_READ_DATASET = "management_file_knowledge"


class LegacyFileState(Contract):
    status: Literal['UPLOADED', 'COMPLETED', 'FAILED']
    stage: str | None = None
    processing_attempt: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None
    error_stage: str | None = None
    failed_at: str | None = None
    completed_at: str | None = None
    cleanse_status: str | None = None
    runtime_status: str | None = None
    processed_chunks: int | None = Field(default=None, ge=0)
    total_chunks: int | None = Field(default=None, ge=0)

    @classmethod
    def capture(cls, row):
        values = {name: row.get(name) for name in cls.model_fields}
        for name in ('failed_at', 'completed_at'):
            if isinstance(values[name], datetime): values[name] = values[name].isoformat()
        return cls.model_validate(values)


class LegacySourceState(Contract):
    source_space: str | None = None
    source_key: str | None = None
    source_revision: str | None = None
    source_sha256: str | None = None
    storage_object_id: int | None = Field(default=None, gt=0)
    file_size: int | None = Field(default=None, ge=0)

    @classmethod
    def capture(cls, row):
        return cls.model_validate({name: row.get(name) for name in cls.model_fields})


class LegacySourceBinding(Contract):
    previous: LegacySourceState
    storage_object_id: int = Field(gt=0)
    file_size: int = Field(ge=0)
    previous_object_name: str | None = Field(default=None, max_length=1024)

    @model_serializer(mode='wrap')
    def serialize_binding(self, handler):
        value = handler(self)
        if self.previous_object_name is None:
            value.pop('previous_object_name', None)
        return value

    def bound_values(self, source):
        values = {'source_space': source.space, 'source_key': source.key, 'source_revision': source.version,
            'source_sha256': source.sha256, 'storage_object_id': self.storage_object_id, 'file_size': self.file_size}
        if self.previous_object_name is not None:
            values['object_name'] = source.key
        return values

    def restore_values(self):
        values = self.previous.model_dump()
        if self.previous_object_name is not None:
            values['object_name'] = self.previous_object_name
        return values


class LegacyIngestionSnapshot(Contract):
    schema_version: Literal[1] = 1
    mode: Literal['rebuild_source'] = 'rebuild_source'
    tenant_id: str = Field(min_length=1, max_length=100)
    resource_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    lifecycle_revision: int = Field(ge=0)
    legacy_quiesced: Literal[True]
    previous: LegacyFileState
    original_updated_by: str | None = None
    original_update_time: str | None = None
    task_archive_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    task_references: dict[Literal['process_task_id', 'forward_task_id', 'parent_task_id'],
                          Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')]] = Field(default_factory=dict, max_length=3)
    source_binding: LegacySourceBinding | None = None

    @model_serializer(mode='wrap')
    def serialize_snapshot(self, handler):
        value = handler(self)
        if self.task_archive_sha256 is None: value.pop('task_archive_sha256', None)
        if not self.task_references: value.pop('task_references', None)
        if self.source_binding is None: value.pop('source_binding', None)
        return value

    @classmethod
    def capture(cls, row, *, resource_revision, legacy_quiesced, task_archive_sha256=None, source_binding=None):
        updated = row.get('update_time')
        return cls(tenant_id=row['tenant_id'], resource_revision=resource_revision, lifecycle_revision=row['version'],
                   legacy_quiesced=legacy_quiesced, previous=LegacyFileState.capture(row), original_updated_by=row.get('updated_by'),
                   original_update_time=updated.isoformat() if isinstance(updated, datetime) else updated,
                   task_archive_sha256=task_archive_sha256, source_binding=source_binding,
                   task_references={name: row[name] for name in ('process_task_id', 'forward_task_id', 'parent_task_id') if row.get(name) is not None})


class KnowledgeIngestionIntent(KnowledgeFileReference):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    user_id: str = Field(min_length=1, max_length=100)
    attempt: int = Field(ge=1, le=2**31 - 1)
    source: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)
    parser_version: str = Field(min_length=1, max_length=128)
    embedding_model: ModelVersion
    chunking_strategy: Literal["basic", "by_title", "none"] = "basic"
    legacy_snapshot: LegacyIngestionSnapshot | None = None

    @model_serializer(mode='wrap')
    def serialize_intent(self, handler):
        value = handler(self)
        if self.legacy_snapshot is None: value.pop('legacy_snapshot', None)
        return value

    @model_validator(mode="after")
    def bounded_snapshot(self):
        if self.source.space != "files":
            raise ValueError("Expected a pinned knowledge file source")
        if len(self.model_dump_json().encode("utf-8")) > 16384:
            raise ValueError("Knowledge ingestion intent exceeds 16 KiB")
        return self

    @property
    def idempotency_key(self):
        return f"kb-ingest:{self.file_id}:{self.file_version}:{self.attempt}"

    def _reference(self):
        return self.model_dump(include={"knowledge_id", "file_id", "file_version"})

    def cleanse_request(self):
        return KnowledgeCleanseRequest(
            **self._reference(),
            source=self.source,
            filename=self.filename,
            idempotency_key=self.idempotency_key,
        )

    def runtime_request(self, artifact):
        return KnowledgeFileUpload(
            **self._reference(),
            artifact=artifact,
            parser_version=self.parser_version,
            idempotency_key=self.idempotency_key,
            embedding_model=self.embedding_model,
            chunking_strategy=self.chunking_strategy,
        )
