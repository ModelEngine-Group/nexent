# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only legacy source evidence is not an authorization to execute migration."""

from typing import Annotated, Literal

from contracts.agentos_knowledge import (
    Contract,
    KnowledgeBaseState,
    ModelVersion,
    ObjectReference,
)
from pydantic import Field

INSPECTION_FILES = 'knowledge_source_inspection'
INSPECTION_LEDGER = 'knowledge_source_ledger_inspection'
LEGACY_DOCUMENTS = 'legacy_knowledge_documents'
LEGACY_VECTOR_METADATA = 'legacy_knowledge_vector_metadata'
LEGACY_FILE_CHUNK_FIELDS = ('file_id', 'file_version', 'index', 'chunk_index', 'process_source', 'source_type', 'multi_embedding')
LEGACY_INDEX_OWNER = 'legacy_knowledge_index_owner'
LEGACY_TASKS = 'legacy_knowledge_tasks'
BROKER_INVENTORY = 'legacy_broker_inventory'
LEGACY_INGESTION_INVENTORY = 'legacy_ingestion_inventory'
LEGACY_TASK_REFERENCES = 'legacy_task_references'
PENDING_CHECKS = ('legacy_vectors', 'legacy_tasks', 'runtime_visibility', 'model_dimensions')
Issue = Annotated[str, Field(pattern=r'^[A-Z][A-Z0-9_]{0,79}$')]
SourceDeletionEvidence = Literal['unverified', 'immutable_version', 'confirmed_publisher', 'publisher_evidence_missing']


class SourceFinding(Contract):
    file_id: str = Field(max_length=64)
    lifecycle_revision: int | None = Field(default=None, ge=0)
    source_generation: int | None = Field(default=None, ge=0)
    issues: list[Issue] = Field(default_factory=list, max_length=32)
    candidate_source: ObjectReference | None = None
    observed_size: int | None = Field(default=None, ge=0)
    candidate_storage_object_id: int | None = Field(default=None, gt=0)
    source_deletion_evidence: SourceDeletionEvidence = 'unverified'


class SourceInspectionPage(Contract):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0)
    index_name: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    knowledge_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    files: list[SourceFinding] = Field(max_length=1000)
    next_cursor: str | None = None
    pending_checks: tuple[Literal['legacy_vectors'], Literal['legacy_tasks'],
                          Literal['runtime_visibility'], Literal['model_dimensions']] = PENDING_CHECKS


VECTOR_PENDING_CHECKS = ('source_mapping', 'legacy_tasks', 'runtime_visibility', 'model_dimensions')


class LegacyVectorFinding(Contract):
    document_id_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: str = Field(min_length=1, max_length=128)
    source_reference_hash: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    file_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    chunk_index: int | None = Field(default=None, ge=0)
    dimensions: int | None = Field(default=None, ge=0)
    standalone_candidate: bool = False
    issues: list[Issue] = Field(default_factory=list, max_length=32)


class LegacyVectorPage(Contract):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0)
    index_name: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    knowledge_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    collection_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    collection_dimensions: int | None = Field(default=None, gt=0)
    metric: str | None = Field(default=None, max_length=100)
    documents: list[LegacyVectorFinding] = Field(max_length=1000)


TASK_PENDING_CHECKS = ('unattributed_tasks', 'runtime_visibility', 'model_dimensions', 'source_mapping')


class LegacyTaskFinding(Contract):
    task_id_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    origin: Literal['pg_reference', 'index_metadata']
    status: Literal['PENDING', 'RECEIVED', 'STARTED', 'RETRY', 'SUCCESS', 'FAILURE', 'REVOKED', 'UNKNOWN']
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    file_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    auxiliary_present: list[Literal['progress', 'error', 'cancel', 'chunks', 'parts']] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list, max_length=32)


class LegacyTaskPage(Contract):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0)
    index_name: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    knowledge_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    tasks: list[LegacyTaskFinding] = Field(max_length=1000)
    snapshot: Literal[False] = False


class LegacyTaskValue(Contract):
    binding: Literal['backend', 'general']
    key: str = Field(min_length=1, max_length=256)
    encoding: Literal['raw', 'redis-dump']
    ttl_ms: int = Field(ge=-2)
    value_base64: str | None
    sha256: str | None = Field(pattern=r'^[0-9a-f]{64}$')


class LegacyTaskArchiveFinding(LegacyTaskFinding):
    archive: list[LegacyTaskValue]


class LegacyTaskArchivePage(LegacyTaskPage):
    tasks: list[LegacyTaskArchiveFinding] = Field(max_length=1000)


RUNTIME_PENDING_CHECKS = ('source_mapping', 'legacy_vectors', 'legacy_tasks')


class RuntimeInspectionPage(KnowledgeBaseState):
    schema_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=100)
    actor_id: str = Field(min_length=1, max_length=100)
    index_name: str = Field(min_length=1, max_length=100)
    embedding_model: ModelVersion | None = None
    embedding_dimensions: int | None = Field(default=None, gt=0)
    issues: list[Issue] = Field(default_factory=list, max_length=32)
