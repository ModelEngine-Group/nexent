# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned deletion scope; Runtime receives only standard File.delete."""

from typing import Literal

from contracts.agentos_knowledge import (
    KnowledgeFileDelete,
    KnowledgeFileReference,
    KnowledgeJobLookup,
    ObjectReference,
    knowledge_job_id,
)
from pydantic import Field, model_validator

DELETION_DATASET = "management_knowledge_deletions"
DELETION_KNOWLEDGE_DATASET = 'management_knowledge_deletion_metadata'


class KnowledgeDeletionIntent(KnowledgeFileReference):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    user_id: str = Field(min_length=1, max_length=100)
    scope: Literal["full", "source_only"]
    index_name: str = Field(min_length=1, max_length=100)
    filename: str = Field(min_length=1, max_length=1024)
    object_name: str | None = Field(default=None, min_length=1, max_length=1024)
    source: ObjectReference | None = None

    @model_validator(mode="after")
    def bounded_source(self):
        if self.source is not None and self.source.space != "files":
            raise ValueError("Expected a pinned knowledge source")
        if self.scope == "source_only" and (self.source is None or self.object_name is None):
            raise ValueError("Source-only deletion requires a confirmed source")
        if len(self.model_dump_json().encode("utf-8")) > 16384:
            raise ValueError("Knowledge deletion intent exceeds 16 KiB")
        return self

    def runtime_request(self):
        if self.scope != "full":
            raise ValueError("Source-only deletion must preserve Runtime vectors")
        return KnowledgeFileDelete(
            **self.model_dump(include={"knowledge_id", "file_id", "file_version"}),
            idempotency_key=f"kb-delete:{self.file_id}:{self.file_version}:full",
        )

    def runtime_lookup(self, tenant_id):
        request = self.runtime_request()
        return KnowledgeJobLookup(
            **request.model_dump(include={"knowledge_id", "file_id", "file_version"}),
            job_id=knowledge_job_id(request, tenant_id, self.user_id),
        )
