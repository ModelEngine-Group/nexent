# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only legacy source evidence is not an authorization to execute migration."""

from typing import Annotated, Literal

from contracts.agentos_knowledge import Contract, ObjectReference
from pydantic import Field

INSPECTION_FILES = 'knowledge_source_inspection'
INSPECTION_LEDGER = 'knowledge_source_ledger_inspection'
PENDING_CHECKS = ('legacy_vectors', 'legacy_tasks', 'runtime_visibility', 'model_dimensions')
Issue = Annotated[str, Field(pattern=r'^[A-Z][A-Z0-9_]{0,79}$')]


class SourceFinding(Contract):
    file_id: str = Field(max_length=64)
    lifecycle_revision: int | None = Field(default=None, ge=0)
    source_generation: int | None = Field(default=None, ge=0)
    issues: list[Issue] = Field(default_factory=list, max_length=32)
    candidate_source: ObjectReference | None = None
    observed_size: int | None = Field(default=None, ge=0)


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
